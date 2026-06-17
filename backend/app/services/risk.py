from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.models import Product, RiskEvaluation, RiskRule, SourceRecord
from app.services.codes import make_code
from app.services.normalization import normalize_text
from app.services.profile_options import canonical_profile_value, canonical_profile_values

SEVERITY_LABELS = {
    0: "unknown",
    1: "minimal",
    2: "low",
    3: "moderate",
    4: "high",
    5: "critical",
}

CLINICAL_KEYS = {
    "skin_types",
    "hair_types",
    "scalp_types",
    "age_band",
    "allergies",
    "sensitivities",
    "pregnancy",
    "lactation",
    "conditions",
}

PRODUCT_FILTER_KEYS = {
    "product_text_keywords",
    "product_category_keywords",
    "product_name_keywords",
    "exclude_product_text_keywords",
}


def _profile_values(profile: dict[str, Any], key: str) -> set[str]:
    value = profile.get(key)
    if value is None:
        return set()
    if isinstance(value, list):
        return canonical_profile_values(key, [str(item) for item in value])
    if isinstance(value, bool):
        return {str(value).lower()} if value else set()
    return {canonical_profile_value(key, str(value))}


def _contains_any(text: str, values: list[str] | tuple[str, ...] | set[str] | None) -> bool:
    if not values:
        return False
    normalized_text = f" {normalize_text(text)} "
    for value in values:
        normalized_value = normalize_text(str(value))
        if normalized_value and f" {normalized_value} " in normalized_text:
            return True
    return False


def _product_context(product: Product) -> tuple[str, str, str]:
    category_parts = [product.category_text or ""]
    for link in product.categories:
        if link.category:
            category_parts.extend([link.category.name, link.category.slug])
    category_text = " ".join(category_parts)
    name_text = product.name or ""
    return name_text, category_text, f"{name_text} {category_text}"


def _product_filters_apply(product: Product, applies_to: dict[str, Any]) -> bool:
    name_text, category_text, all_text = _product_context(product)
    if _contains_any(all_text, applies_to.get("exclude_product_text_keywords")):
        return False
    if applies_to.get("product_name_keywords") and not _contains_any(
        name_text, applies_to.get("product_name_keywords")
    ):
        return False
    if applies_to.get("product_category_keywords") and not _contains_any(
        category_text, applies_to.get("product_category_keywords")
    ):
        return False
    if applies_to.get("product_text_keywords") and not _contains_any(
        all_text, applies_to.get("product_text_keywords")
    ):
        return False
    return True


def _rule_applies(rule: RiskRule, product: Product, profile: dict[str, Any]) -> bool:
    applies_to = rule.applies_to or {}
    if not applies_to:
        return True
    if not _product_filters_apply(product, applies_to):
        return False
    if applies_to.get("always") is True:
        return True
    checked = False
    for key, expected in applies_to.items():
        if key not in CLINICAL_KEYS:
            continue
        checked = True
        expected_values = canonical_profile_values(key, [str(item) for item in expected or []])
        if key in {"pregnancy", "lactation"}:
            if profile.get(key) and "true" in expected_values:
                return True
            continue
        if _profile_values(profile, key) & expected_values:
            return True
    return not checked


def evaluate_loaded_product_risk(
    db: Session,
    product: Product,
    profile: dict[str, Any],
    *,
    persist: bool,
) -> dict[str, Any]:
    ingredient_codes = [link.ingredient_code for link in product.ingredients]
    rules = db.scalars(
        select(RiskRule).where(RiskRule.ingredient_code.in_(ingredient_codes), RiskRule.active.is_(True))
    ).all()
    matched: list[RiskRule] = [rule for rule in rules if _rule_applies(rule, product, profile)]

    score = max([rule.severity_score for rule in matched], default=0)
    severity = SEVERITY_LABELS.get(score, "unknown")
    matched_rule_codes = [rule.risk_rule_code for rule in matched]
    side_effects = sorted({effect for rule in matched for effect in rule.side_effects})
    source_records = {
        record.source_record_code: record
        for record in db.scalars(
            select(SourceRecord).where(
                SourceRecord.source_record_code.in_([rule.source_record_code for rule in matched])
            )
        ).all()
    }
    matched_ingredients = []
    for rule in sorted(matched, key=lambda item: item.severity_score, reverse=True):
        record = source_records.get(rule.source_record_code)
        matched_ingredients.append(
            {
            "ingredient_code": rule.ingredient_code,
            "ingredient_name": rule.ingredient.canonical_name,
            "rule_code": rule.risk_rule_code,
            "title": rule.title,
            "summary": rule.summary,
            "severity": rule.severity,
            "severity_score": rule.severity_score,
            "side_effects": rule.side_effects,
            "confidence_score": rule.confidence_score,
            "evidence_kind": rule.evidence_kind,
            "source_record_code": rule.source_record_code,
            "source_url": record.source_url if record else None,
        }
        )
    explanation = (
        "No source-backed risk rules matched this profile. Unknown does not mean risk-free."
        if not matched
        else f"{len(matched)} source-backed ingredient rule(s) matched this profile."
    )
    evaluation_code = make_code("eval")
    if persist:
        evaluation = RiskEvaluation(
            evaluation_code=evaluation_code,
            product_code=product.product_code,
            profile={key: profile.get(key) for key in CLINICAL_KEYS if key in profile},
            severity=severity,
            score=score,
            matched_rule_codes=matched_rule_codes,
            explanation=explanation,
        )
        db.add(evaluation)
        try:
            db.flush()
            evaluation_code = evaluation.evaluation_code
        except OperationalError:
            db.rollback()
    return {
        "evaluation_code": evaluation_code,
        "product_code": product.product_code,
        "product_name": product.name,
        "severity": severity,
        "score": score,
        "side_effects": side_effects,
        "matched_rule_codes": matched_rule_codes,
        "matched_ingredients": matched_ingredients,
        "explanation": explanation,
        "disclaimer": "This is an evidence-backed screening tool, not a diagnosis or medical advice.",
    }


def evaluate_product_risk(db: Session, product_code: str, profile: dict[str, Any]) -> dict[str, Any]:
    product = db.get(Product, product_code)
    if product is None:
        raise ValueError("Product not found")
    return evaluate_loaded_product_risk(db, product, profile, persist=True)
