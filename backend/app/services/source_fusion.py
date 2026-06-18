from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    CanonicalTerm,
    Ingredient,
    IngredientSourceLink,
    IngredientTermLink,
    Product,
    ProductSourceLink,
    ProductTermLink,
    SourceRecordFact,
    SourceRecord,
    TermAlias,
)
from app.services.codes import make_code
from app.services.normalization import normalize_text, slugify


CONCERN_BUCKET_ALIASES = {
    "allergies immunotoxicity": "allergy-immunotoxicity",
    "allergies and immunotoxicity": "allergy-immunotoxicity",
    "allergy immunotoxicity": "allergy-immunotoxicity",
    "irritation skin eyes or lungs": "irritation",
    "developmental and reproductive toxicity": "reproductive-developmental",
    "developmental reproductive toxicity": "reproductive-developmental",
    "developmental reproductive": "reproductive-developmental",
    "non reproductive organ system toxicity": "organ-system-toxicity",
    "organ system toxicity non reproductive": "organ-system-toxicity",
    "use restrictions": "use-restriction",
    "enhanced skin absorption": "enhanced-absorption",
    "persistence and bioaccumulation": "persistence-bioaccumulation",
    "contamination concerns": "contamination",
}

CONCERN_LABELS = {
    "allergy-immunotoxicity": "Allergy / immunotoxicity",
    "irritation": "Irritation",
    "reproductive-developmental": "Reproductive / developmental toxicity",
    "endocrine-disruption": "Endocrine disruption",
    "cancer": "Cancer",
    "use-restriction": "Use restriction",
    "contamination": "Contamination",
    "organ-system-toxicity": "Organ system toxicity",
    "neurotoxicity": "Neurotoxicity",
    "enhanced-absorption": "Enhanced skin absorption",
    "occupational-hazard": "Occupational hazard",
    "ecotoxicity": "Ecotoxicity",
    "persistence-bioaccumulation": "Persistence / bioaccumulation",
}


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        for key in ("name", "label", "value", "text", "title"):
            if value.get(key):
                return [str(value[key])]
        return []
    if isinstance(value, Iterable):
        values: list[str] = []
        for item in value:
            if isinstance(item, dict):
                for key in ("name", "label", "value", "text", "title"):
                    if item.get(key):
                        values.append(str(item[key]))
                        break
            elif item is not None and str(item).strip():
                values.append(str(item))
        return values
    return [str(value)]


def canonical_concern_slug(raw_value: str) -> str:
    normalized = normalize_text(raw_value)
    if normalized in CONCERN_BUCKET_ALIASES:
        return CONCERN_BUCKET_ALIASES[normalized]
    slug = slugify(raw_value)
    return {
        "endocrine-disruption": "endocrine-disruption",
        "cancer": "cancer",
        "neurotoxicity": "neurotoxicity",
        "ecotoxicity": "ecotoxicity",
        "occupational-hazards": "occupational-hazard",
        "occupational-hazard": "occupational-hazard",
    }.get(slug, slug)


def canonical_term_label(term_type: str, raw_value: str, slug: str) -> str:
    if term_type == "concern":
        return CONCERN_LABELS.get(slug, raw_value.strip().title())
    cleaned = raw_value.replace("en:", "").replace("-", " ").strip()
    return cleaned.title() if cleaned.islower() else cleaned


def upsert_canonical_term(
    db: Session,
    *,
    term_type: str,
    raw_value: str,
    source_code: str | None = None,
    description: str | None = None,
) -> CanonicalTerm | None:
    clean = str(raw_value or "").strip()
    if not clean:
        return None
    slug = canonical_concern_slug(clean) if term_type == "concern" else slugify(clean)
    term = db.scalar(
        select(CanonicalTerm).where(
            CanonicalTerm.term_type == term_type,
            CanonicalTerm.slug == slug,
        )
    )
    if term is None:
        term = CanonicalTerm(
            term_code=make_code("term", f"{term_type}:{slug}"),
            term_type=term_type,
            slug=slug,
            label=canonical_term_label(term_type, clean, slug),
            description=description,
        )
        db.add(term)
        db.flush()
    elif description and not term.description:
        term.description = description

    normalized_alias = normalize_text(clean)
    alias_code = make_code("talias", f"{term.term_code}:{source_code or 'any'}:{normalized_alias}")
    if normalized_alias and db.get(TermAlias, alias_code) is None:
        db.add(
            TermAlias(
                alias_code=alias_code,
                term_code=term.term_code,
                source_code=source_code,
                alias=clean,
                normalized_alias=normalized_alias,
            )
        )
    return term


def link_product_source(
    db: Session,
    *,
    product: Product,
    record: SourceRecord,
    external_id: str,
    match_method: str,
    match_confidence: float,
    source_updated_at: datetime | None = None,
    active: bool = True,
) -> ProductSourceLink:
    code = make_code("psl", f"{product.product_code}:{record.source_record_code}")
    link = db.get(ProductSourceLink, code)
    if link is None:
        link = ProductSourceLink(
            product_source_link_code=code,
            product_code=product.product_code,
            source_record_code=record.source_record_code,
            source_code=record.source_code,
            external_id=external_id,
            source_url=record.source_url,
            match_method=match_method,
            match_confidence=match_confidence,
            source_updated_at=source_updated_at,
            active=active,
        )
        db.add(link)
    else:
        link.external_id = external_id
        link.source_url = record.source_url
        link.match_method = match_method
        link.match_confidence = match_confidence
        link.source_updated_at = source_updated_at
        link.active = active
    return link


def link_ingredient_source(
    db: Session,
    *,
    ingredient: Ingredient,
    record: SourceRecord,
    external_id: str,
    match_method: str,
    match_confidence: float,
    active: bool = True,
) -> IngredientSourceLink:
    code = make_code("isl", f"{ingredient.ingredient_code}:{record.source_record_code}")
    link = db.get(IngredientSourceLink, code)
    if link is None:
        link = IngredientSourceLink(
            ingredient_source_link_code=code,
            ingredient_code=ingredient.ingredient_code,
            source_record_code=record.source_record_code,
            source_code=record.source_code,
            external_id=external_id,
            source_url=record.source_url,
            match_method=match_method,
            match_confidence=match_confidence,
            active=active,
        )
        db.add(link)
    else:
        link.external_id = external_id
        link.source_url = record.source_url
        link.match_method = match_method
        link.match_confidence = match_confidence
        link.active = active
    return link


def link_product_term(
    db: Session,
    *,
    product: Product,
    record: SourceRecord,
    term_type: str,
    raw_value: str,
    confidence_score: float = 0.8,
) -> ProductTermLink | None:
    term = upsert_canonical_term(
        db,
        term_type=term_type,
        raw_value=raw_value,
        source_code=record.source_code,
    )
    if term is None:
        return None
    code = make_code("ptl", f"{product.product_code}:{term.term_code}:{record.source_record_code}")
    link = db.get(ProductTermLink, code)
    if link is None:
        link = ProductTermLink(
            product_term_link_code=code,
            product_code=product.product_code,
            term_code=term.term_code,
            source_record_code=record.source_record_code,
            source_code=record.source_code,
            raw_value=raw_value,
            confidence_score=confidence_score,
        )
        db.add(link)
    else:
        link.raw_value = raw_value
        link.confidence_score = confidence_score
    return link


def link_ingredient_term(
    db: Session,
    *,
    ingredient: Ingredient,
    record: SourceRecord,
    term_type: str,
    raw_value: str,
    confidence_score: float = 0.8,
) -> IngredientTermLink | None:
    term = upsert_canonical_term(
        db,
        term_type=term_type,
        raw_value=raw_value,
        source_code=record.source_code,
    )
    if term is None:
        return None
    code = make_code("itl", f"{ingredient.ingredient_code}:{term.term_code}:{record.source_record_code}")
    link = db.get(IngredientTermLink, code)
    if link is None:
        link = IngredientTermLink(
            ingredient_term_link_code=code,
            ingredient_code=ingredient.ingredient_code,
            term_code=term.term_code,
            source_record_code=record.source_record_code,
            source_code=record.source_code,
            raw_value=raw_value,
            confidence_score=confidence_score,
        )
        db.add(link)
    else:
        link.raw_value = raw_value
        link.confidence_score = confidence_score
    return link


def upsert_source_fact(
    db: Session,
    *,
    record: SourceRecord,
    entity_kind: str,
    field_name: str,
    value: Any,
    fact_type: str = "attribute",
    label: str | None = None,
    product: Product | None = None,
    ingredient: Ingredient | None = None,
    source_url: str | None = None,
    confidence_score: float = 0.8,
) -> SourceRecordFact | None:
    if value in (None, "", []):
        return None
    if isinstance(value, (dict, list)):
        value_json = value
        value_text = None
        normalized_value = normalize_text(label or field_name)
    else:
        value_text = str(value).strip()
        if not value_text:
            return None
        value_json = {"value": value_text}
        normalized_value = normalize_text(value_text)[:500] or normalize_text(label or field_name)

    code = make_code(
        "fact",
        ":".join(
            [
                record.source_record_code,
                entity_kind,
                product.product_code if product else "",
                ingredient.ingredient_code if ingredient else "",
                fact_type,
                field_name,
                normalized_value or "",
            ]
        ),
    )
    fact = db.get(SourceRecordFact, code)
    if fact is None:
        fact = SourceRecordFact(
            fact_code=code,
            source_record_code=record.source_record_code,
            source_code=record.source_code,
            entity_kind=entity_kind,
            product_code=product.product_code if product else None,
            ingredient_code=ingredient.ingredient_code if ingredient else None,
            fact_type=fact_type,
            field_name=field_name,
            label=label,
            value_text=value_text,
            value_json=value_json,
            normalized_value=normalized_value,
            source_url=source_url or record.source_url,
            confidence_score=confidence_score,
        )
        db.add(fact)
    else:
        fact.label = label
        fact.value_text = value_text
        fact.value_json = value_json
        fact.source_url = source_url or record.source_url
        fact.confidence_score = confidence_score
    return fact


def normalized_product_attributes(product: Product) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for link in product.term_links:
        term = link.term
        if term is None:
            continue
        key = (term.term_type, term.slug)
        item = grouped.setdefault(
            key,
            {
                "term_code": term.term_code,
                "term_type": term.term_type,
                "slug": term.slug,
                "label": term.label,
                "source_codes": set(),
                "confidence_score": 0.0,
            },
        )
        item["source_codes"].add(link.source_code)
        item["confidence_score"] = max(item["confidence_score"], link.confidence_score)
    return [
        {**item, "source_codes": sorted(item["source_codes"])}
        for item in sorted(grouped.values(), key=lambda value: (value["term_type"], value["label"]))
    ]


def product_source_conflicts(product: Product) -> list[dict[str, Any]]:
    values_by_field: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    def add_value(field: str, source_code: str, source_name: str, value: Any, source_url: str | None) -> None:
        if value is None:
            return
        display_value = ", ".join(as_list(value)) if not isinstance(value, str) else value
        clean = display_value.strip()
        normalized = normalize_text(clean)
        if not normalized:
            return
        values_by_field[field][normalized] = {
            "source_code": source_code,
            "source_name": source_name,
            "value": clean,
            "source_url": source_url,
        }

    add_value("name", "canonical", "Catalog display", product.name, None)
    if product.brand:
        add_value("brand", "canonical", "Catalog display", product.brand.name, None)
    add_value("category_text", "canonical", "Catalog display", product.category_text, None)
    add_value("ingredient_text", "canonical", "Catalog display", product.ingredient_text, None)

    for link in product.source_links:
        record = link.source_record
        if record is None or not isinstance(record.payload, dict):
            continue
        payload = record.payload
        source_name = link.source.name if link.source else link.source_code
        add_value("name", link.source_code, source_name, first_payload_value(payload, PRODUCT_NAME_FIELDS), link.source_url)
        add_value("brand", link.source_code, source_name, first_payload_value(payload, BRAND_FIELDS), link.source_url)
        add_value("category_text", link.source_code, source_name, first_payload_value(payload, CATEGORY_FIELDS), link.source_url)
        add_value("ingredient_text", link.source_code, source_name, first_payload_value(payload, INGREDIENT_TEXT_FIELDS), link.source_url)

    conflicts = []
    for field, values in values_by_field.items():
        non_catalog = [value for value in values.values() if value["source_code"] != "canonical"]
        if len(values) > 1 and non_catalog:
            conflicts.append(
                {
                    "field": field,
                    "display_value": getattr(product, field, None) if hasattr(product, field) else None,
                    "source_values": sorted(values.values(), key=lambda item: item["source_name"]),
                }
            )
    return sorted(conflicts, key=lambda item: item["field"])


PRODUCT_NAME_FIELDS = ("product_name", "name", "product", "title")
BRAND_FIELDS = ("brand", "brand_name", "brands")
CATEGORY_FIELDS = ("category", "categories", "product_type", "product_types")
INGREDIENT_TEXT_FIELDS = (
    "ingredients_from_packaging",
    "ingredients_text",
    "ingredient_text",
    "ingredient_list",
)


def first_payload_value(payload: dict[str, Any], fields: Iterable[str]) -> Any:
    for field in fields:
        value = payload.get(field)
        if value not in (None, "", []):
            return value
    return None
