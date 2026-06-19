from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import RiskRule
from app.services import profile_options
from app.services.enrichment import seed_reference_sources_and_rules
from app.services.importers.open_beauty_facts import import_product_payload
from app.services.profile_options import (
    canonical_profile_value,
    canonical_profile_values,
    load_profile_options,
)
from app.services.risk import evaluate_product_risk
from app.services.risk_rules_library import TRUSTED_RISK_RULES


CLINICAL_LIST_FIELDS = {
    "skin_types",
    "scalp_types",
    "age_band",
    "allergies",
    "sensitivities",
    "conditions",
}

PRODUCT_KEYWORDS_BY_RULE = {
    "fda-ppd-hair-dye-sensitizer": "Intense hair dye colorant",
    "fda-eye-area-hair-dye-warning": "Eyebrow lash hair dye",
    "sccs-resorcinol-hair-dye-context": "Hair dye colorant",
    "fda-aha-sun-sensitivity": "Face serum exfoliant",
    "fda-aha-sensitive-skin": "Face serum exfoliant",
    "fda-bha-sun-irritation-warning": "Acne face toner",
    "fda-skin-lightening-hydroquinone-mercury": "Skin lightening dark spot brightening cream",
    "sccs-arbutin-hydroquinone-trace-context": "Brightening dark spot cream",
    "sccs-mi-leave-on-hair-context": "Leave-on hair serum",
    "fda-formaldehyde-hair-smoothing": "Keratin hair smoothing treatment",
}


def test_backend_profile_options_copy_matches_shared_vocabulary():
    backend_root = Path(__file__).resolve().parents[1]
    repo_root = backend_root.parent
    assert (backend_root / "shared" / "profile-options.json").read_text(encoding="utf-8") == (
        repo_root / "shared" / "profile-options.json"
    ).read_text(encoding="utf-8")


def test_profile_options_loader_uses_backend_copy_when_repo_shared_is_unavailable(monkeypatch):
    backend_root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        profile_options,
        "PROFILE_OPTIONS_PATHS",
        (
            backend_root / "missing" / "profile-options.json",
            backend_root / "shared" / "profile-options.json",
        ),
    )
    profile_options.load_profile_options.cache_clear()
    profile_options.profile_alias_index.cache_clear()

    assert profile_options.load_profile_options()["version"] == "2026-06-18.1"

    profile_options.load_profile_options.cache_clear()
    profile_options.profile_alias_index.cache_clear()


def _first_ingredient_name(rule: dict) -> str:
    return str(rule["ingredient_names"][0])


def _product_for_rule(db_session: Session, rule: dict):
    external_id = rule["external_id"]
    product_name = PRODUCT_KEYWORDS_BY_RULE.get(external_id, f"Rule coverage {rule['title']}")
    return import_product_payload(
        db_session,
        {
            "code": f"risk-coverage-{external_id}",
            "product_name": product_name,
            "brands": "Rule Coverage Lab",
            "categories": product_name,
            "categories_tags": ["en:rule-coverage"],
            "ingredients_text": f"Aqua, {_first_ingredient_name(rule)}",
            "ingredients": [{"text": "Aqua", "rank": 1}, {"text": _first_ingredient_name(rule), "rank": 2}],
        },
    )


def _profile_for(field: str, value: str) -> dict:
    if field in {"pregnancy", "lactation"}:
        return {field: value == "true"}
    if field == "age_band":
        return {"age_band": canonical_profile_value(field, value)}
    return {field: [canonical_profile_value(field, value)]}


def _rule_titles(result: dict) -> set[str]:
    return {match["title"] for match in result["matched_ingredients"]}


def test_profile_option_vocabulary_covers_every_rule_value():
    options = load_profile_options()
    for rule in TRUSTED_RISK_RULES:
        applies_to = rule["applies_to"]
        for field in CLINICAL_LIST_FIELDS:
            expected_values = applies_to.get(field, [])
            for expected in expected_values:
                canonical = canonical_profile_value(field, str(expected))
                selectable = {
                    option["value"]
                    for option in options["fields"][field]["options"]
                }
                assert canonical in selectable, f"{rule['external_id']} references unsupported {field}={expected}"


def test_every_selectable_profile_value_is_used_by_a_rule():
    used: dict[str, set[str]] = {field: set() for field in CLINICAL_LIST_FIELDS}
    for rule in TRUSTED_RISK_RULES:
        for field in CLINICAL_LIST_FIELDS:
            used[field] |= canonical_profile_values(field, [str(item) for item in rule["applies_to"].get(field, [])])

    options = load_profile_options()
    for field in CLINICAL_LIST_FIELDS:
        selectable = {option["value"] for option in options["fields"][field]["options"]}
        assert selectable <= used[field], f"{field} exposes values with no source-backed rule: {selectable - used[field]}"


def test_each_rule_profile_value_and_alias_matches_seeded_rules(db_session: Session):
    seed_reference_sources_and_rules(db_session)
    options = load_profile_options()

    for rule in TRUSTED_RISK_RULES:
        product = _product_for_rule(db_session, rule)
        seed_reference_sources_and_rules(db_session)
        db_session.flush()

        applies_to = rule["applies_to"]
        expected_active_rule = db_session.query(RiskRule).filter(
            RiskRule.title == rule["title"],
            RiskRule.active.is_(True),
        ).first()
        assert expected_active_rule is not None, rule["title"]

        if applies_to.get("always") is True:
            assert rule["title"] in _rule_titles(evaluate_product_risk(db_session, product.product_code, {}))

        for field in CLINICAL_LIST_FIELDS:
            for expected in applies_to.get(field, []):
                profile = _profile_for(field, str(expected))
                result = evaluate_product_risk(db_session, product.product_code, profile)
                assert rule["title"] in _rule_titles(result), f"{rule['title']} did not match {field}={expected}"

                canonical = canonical_profile_value(field, str(expected))
                option = next(
                    item for item in options["fields"][field]["options"] if item["value"] == canonical
                )
                for alias in option.get("aliases", []):
                    alias_profile = _profile_for(field, alias)
                    alias_result = evaluate_product_risk(db_session, product.product_code, alias_profile)
                    assert rule["title"] in _rule_titles(alias_result), (
                        f"{rule['title']} did not match alias {field}={alias}"
                    )

        for field in {"pregnancy", "lactation"}:
            if field in applies_to:
                result = evaluate_product_risk(db_session, product.product_code, {field: True})
                assert rule["title"] in _rule_titles(result), f"{rule['title']} did not match {field}=true"


def test_fragrance_pattern_rule_matches_natural_fragrance_ingredient(db_session: Session):
    product = import_product_payload(
        db_session,
        {
            "code": "risk-fragrance-pattern",
            "product_name": "Rose face cream",
            "brands": "Rule Test Lab",
            "categories": "Skin care, Face cream",
            "categories_tags": ["en:skin-care", "en:face-cream"],
            "ingredients_text": "Aqua, Glycerin, Natural Rose Fragrance",
            "ingredients": [
                {"text": "Aqua", "rank": 1},
                {"text": "Glycerin", "rank": 2},
                {"text": "Natural Rose Fragrance", "rank": 3},
            ],
        },
    )
    seed_reference_sources_and_rules(db_session)
    db_session.flush()

    result = evaluate_product_risk(
        db_session,
        product.product_code,
        {"sensitivities": ["fragrance"], "skin_types": ["sensitive"]},
    )

    assert result["severity"] == "moderate"
    assert any(item["ingredient_name"] == "Natural Rose Fragrance" for item in result["matched_ingredients"])
    assert all(item["source_url"] for item in result["matched_ingredients"])


def test_evaluation_tolerates_malformed_rule_side_effects(db_session: Session):
    product = import_product_payload(
        db_session,
        {
            "code": "risk-fragrance-null-effects",
            "product_name": "Rose face cream",
            "brands": "Rule Test Lab",
            "categories": "Skin care, Face cream",
            "categories_tags": ["en:skin-care", "en:face-cream"],
            "ingredients_text": "Aqua, Natural Rose Fragrance",
            "ingredients": [{"text": "Aqua", "rank": 1}, {"text": "Natural Rose Fragrance", "rank": 2}],
        },
    )
    seed_reference_sources_and_rules(db_session)
    db_session.flush()
    rules = db_session.query(RiskRule).filter(RiskRule.title == "Fragrance allergen sensitivity").all()
    assert rules
    for rule in rules:
        rule.side_effects = None

    result = evaluate_product_risk(
        db_session,
        product.product_code,
        {"sensitivities": ["fragrance"], "skin_types": ["sensitive"]},
    )

    assert result["severity"] == "moderate"
    assert result["side_effects"] == []
    assert result["matched_ingredients"][0]["side_effects"] == []


def test_evaluation_returns_result_when_audit_persistence_fails(db_session: Session, monkeypatch):
    product = import_product_payload(
        db_session,
        {
            "code": "risk-fragrance-audit-failure",
            "product_name": "Rose face cream",
            "brands": "Rule Test Lab",
            "categories": "Skin care, Face cream",
            "categories_tags": ["en:skin-care", "en:face-cream"],
            "ingredients_text": "Aqua, Natural Rose Fragrance",
            "ingredients": [{"text": "Aqua", "rank": 1}, {"text": "Natural Rose Fragrance", "rank": 2}],
        },
    )
    seed_reference_sources_and_rules(db_session)
    db_session.flush()
    product_code = product.product_code

    def fail_flush(*_args, **_kwargs):
        raise SQLAlchemyError("audit table unavailable")

    monkeypatch.setattr(db_session, "flush", fail_flush)

    result = evaluate_product_risk(
        db_session,
        product_code,
        {"sensitivities": ["fragrance"], "skin_types": ["sensitive"]},
    )

    assert result["product_code"] == product_code
    assert result["severity"] == "moderate"
    assert result["matched_ingredients"]


def test_product_metadata_gates_formaldehyde_hair_smoothing_rule(db_session: Session):
    hair_product = import_product_payload(
        db_session,
        {
            "code": "risk-formaldehyde-hair",
            "product_name": "Keratin smoothing treatment",
            "brands": "Rule Test Lab",
            "categories": "Hair care, Hair smoothing",
            "categories_tags": ["en:hair-care", "en:hair-smoothing"],
            "ingredients_text": "Aqua, Formaldehyde",
            "ingredients": [{"text": "Aqua", "rank": 1}, {"text": "Formaldehyde", "rank": 2}],
        },
    )
    hand_product = import_product_payload(
        db_session,
        {
            "code": "risk-formaldehyde-hand",
            "product_name": "Gentle hand wash",
            "brands": "Rule Test Lab",
            "categories": "Hygiene, Hand wash",
            "categories_tags": ["en:hygiene", "en:hand-wash"],
            "ingredients_text": "Aqua, Formaldehyde",
            "ingredients": [{"text": "Aqua", "rank": 1}, {"text": "Formaldehyde", "rank": 2}],
        },
    )
    seed_reference_sources_and_rules(db_session)
    db_session.flush()

    hair_result = evaluate_product_risk(db_session, hair_product.product_code, {})
    hand_result = evaluate_product_risk(db_session, hand_product.product_code, {})

    assert hair_result["severity"] == "critical"
    assert any("Hair smoothing" in item["title"] for item in hair_result["matched_ingredients"])
    assert hand_result["severity"] == "unknown"
