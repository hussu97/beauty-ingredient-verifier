from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Ingredient, RiskRule, SourceRecord
from app.services.codes import make_code
from app.services.normalization import normalize_text
from app.services.risk_rules_library import REFERENCE_SOURCES, TRUSTED_RISK_RULES
from app.services.source_records import upsert_source, upsert_source_record


RISK_LIBRARY_VERSION = "2026-06-17.2"


def _pattern_matches(normalized_name: str, pattern: str) -> bool:
    normalized_pattern = normalize_text(pattern)
    if not normalized_pattern:
        return False
    if len(normalized_pattern) < 4:
        return normalized_name == normalized_pattern
    return (
        normalized_name == normalized_pattern
        or normalized_name.startswith(f"{normalized_pattern} ")
        or normalized_name.endswith(f" {normalized_pattern}")
        or f" {normalized_pattern} " in f" {normalized_name} "
    )


def _ensure_ingredient(db: Session, raw_name: str, source_record_code: str) -> Ingredient:
    normalized = normalize_text(raw_name)
    ingredient = db.scalar(select(Ingredient).where(Ingredient.normalized_name == normalized))
    if ingredient is None:
        ingredient = Ingredient(
            ingredient_code=make_code("ing", normalized),
            canonical_name=raw_name,
            normalized_name=normalized,
            inci_name=raw_name.upper(),
            functions=[],
            regulatory_status="source-mentioned",
            source_record_code=source_record_code,
        )
        db.add(ingredient)
        db.flush()
    else:
        ingredient.source_record_code = ingredient.source_record_code or source_record_code
    return ingredient


def _matching_ingredients(db: Session, rule: dict, source_record_code: str) -> list[Ingredient]:
    matched: dict[str, Ingredient] = {}
    for raw_name in rule.get("ingredient_names", []):
        ingredient = _ensure_ingredient(db, str(raw_name), source_record_code)
        matched[ingredient.ingredient_code] = ingredient

    patterns = [str(pattern) for pattern in rule.get("ingredient_name_patterns", [])]
    if patterns:
        all_ingredients = db.scalars(select(Ingredient)).all()
        for ingredient in all_ingredients:
            if any(_pattern_matches(ingredient.normalized_name, pattern) for pattern in patterns):
                matched[ingredient.ingredient_code] = ingredient
    return list(matched.values())


def seed_reference_sources_and_rules(db: Session) -> int:
    for source in REFERENCE_SOURCES:
        upsert_source(db, **source)

    inserted_or_updated = 0
    active_rule_codes: set[str] = set()
    for rule in TRUSTED_RISK_RULES:
        record = upsert_source_record(
            db,
            source_code=rule["source_code"],
            external_id=rule["external_id"],
            record_type="risk-rule-reference",
            payload={
                key: value
                for key, value in rule.items()
                if key not in {"ingredient_names", "ingredient_name_patterns"}
            }
            | {"library_version": RISK_LIBRARY_VERSION},
            source_url=rule.get("source_url"),
        )
        for ingredient in _matching_ingredients(db, rule, record.source_record_code):
            code = make_code("rr", f"{rule['external_id']}:{ingredient.ingredient_code}")
            active_rule_codes.add(code)
            risk = db.get(RiskRule, code)
            if risk is None:
                risk = RiskRule(
                    risk_rule_code=code,
                    ingredient_code=ingredient.ingredient_code,
                    source_record_code=record.source_record_code,
                    title=rule["title"],
                    summary=rule["summary"],
                    severity=rule["severity"],
                    severity_score=rule["severity_score"],
                    side_effects=rule["side_effects"],
                    applies_to=rule["applies_to"],
                    evidence_kind=rule["evidence_kind"],
                    confidence_score=rule["confidence_score"],
                    version="1",
                    active=True,
                )
                db.add(risk)
            else:
                risk.title = rule["title"]
                risk.summary = rule["summary"]
                risk.severity = rule["severity"]
                risk.severity_score = rule["severity_score"]
                risk.side_effects = rule["side_effects"]
                risk.applies_to = rule["applies_to"]
                risk.evidence_kind = rule["evidence_kind"]
                risk.confidence_score = rule["confidence_score"]
                risk.source_record_code = record.source_record_code
                risk.active = True
            inserted_or_updated += 1

    generated_rules = db.scalars(
        select(RiskRule)
        .join(SourceRecord, RiskRule.source_record_code == SourceRecord.source_record_code)
        .where(SourceRecord.record_type == "risk-rule-reference")
    ).all()
    for risk in generated_rules:
        if risk.risk_rule_code not in active_rule_codes:
            risk.active = False
    return inserted_or_updated


def enrich_with_pubchem(db: Session, limit: int = 25) -> int:
    source = "src_pubchem"
    count = 0
    ingredients = db.scalars(
        select(Ingredient)
        .where(Ingredient.pubchem_cid.is_(None))
        .order_by(Ingredient.created_at.desc())
        .limit(limit)
    ).all()
    for ingredient in ingredients:
        try:
            cid_response = httpx.get(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{ingredient.canonical_name}/cids/JSON",
                timeout=8,
            )
            if cid_response.status_code != 200:
                continue
            cids = cid_response.json().get("IdentifierList", {}).get("CID", [])
            if not cids:
                continue
            cid = str(cids[0])
            record = upsert_source_record(
                db,
                source_code=source,
                external_id=f"compound:{cid}",
                record_type="compound",
                payload={"cid": cid, "matched_name": ingredient.canonical_name},
                source_url=f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
            )
            ingredient.pubchem_cid = cid
            ingredient.source_record_code = ingredient.source_record_code or record.source_record_code
            count += 1
        except (httpx.HTTPError, ValueError):
            continue
    return count


def enrich_ingredients(db: Session, *, pubchem_live: bool = False, limit: int = 25) -> int:
    count = seed_reference_sources_and_rules(db)
    if pubchem_live:
        count += enrich_with_pubchem(db, limit=limit)
    return count
