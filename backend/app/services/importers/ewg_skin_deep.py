from __future__ import annotations

import csv
import gzip
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Brand,
    Category,
    Ingredient,
    IngredientTermLink,
    Product,
    ProductCategory,
    ProductIngredient,
    RiskRule,
)
from app.services.codes import make_code
from app.services.normalization import (
    canonical_ingredient_name,
    normalize_text,
    slugify,
    split_ewg_ingredients,
)
from app.services.source_fusion import (
    as_list,
    canonical_concern_slug,
    link_ingredient_source,
    link_ingredient_term,
    link_product_source,
    link_product_term,
    upsert_source_fact,
)
from app.services.source_records import upsert_source, upsert_source_record

EWG_SOURCE_CODE = "src_ewg_skin_deep"

PRODUCT_NAME_FIELDS = ("product_name", "name", "product", "title")
BRAND_FIELDS = ("brand", "brand_name", "brands")
BARCODE_FIELDS = ("barcode", "gtin", "upc", "ean", "code")
SOURCE_URL_FIELDS = ("source_url", "url", "ewg_url", "product_url")
UPDATED_AT_FIELDS = ("data_last_updated", "last_updated", "updated_at", "modified_at")
INGREDIENT_TEXT_FIELDS = (
    "ingredients_from_packaging",
    "ingredients_text",
    "ingredient_text",
    "ingredient_list",
)
CATEGORY_FIELDS = ("category", "categories", "product_type", "product_types")


@dataclass(frozen=True)
class ProductMatch:
    product: Product | None
    method: str
    confidence: float


def ensure_ewg_source(db: Session) -> None:
    upsert_source(
        db,
        source_code=EWG_SOURCE_CODE,
        name="EWG Skin Deep",
        kind="authorized-product-and-ingredient-database",
        homepage_url="https://www.ewg.org/skindeep/",
        license_name=None,
        terms_url="https://www.ewg.org/legal-disclaimer",
        reliability="curated-source",
    )


def _jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    clean = value.strip()
    if not clean:
        return value
    if clean[0] not in "[{":
        return value
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return value


def _read_json(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[arg-type]
        payload = json.load(handle)
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                yield row
    elif isinstance(payload, dict):
        rows = payload.get("products") or payload.get("ingredients") or payload.get("items") or payload.get("data")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    yield row
        else:
            yield payload


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[arg-type]
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict):
                    yield row


def _read_csv(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield {key: _jsonish(value) for key, value in row.items() if key}


def _read_parquet(path: Path) -> Iterable[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Install backend[data] to import Parquet exports") from exc
    table = pq.read_table(path)
    for row in table.to_pylist():
        yield row


def _iter_rows(source_path: str) -> Iterable[dict[str, Any]]:
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(path)
    suffixes = set(path.suffixes)
    if ".parquet" in suffixes:
        yield from _read_parquet(path)
    elif ".csv" in suffixes:
        yield from _read_csv(path)
    elif ".jsonl" in suffixes or path.name.endswith(".jsonl.gz"):
        yield from _read_jsonl(path)
    elif ".json" in suffixes or path.name.endswith(".json.gz"):
        yield from _read_json(path)
    else:
        raise ValueError(f"Unsupported EWG import file type: {path}")


def _first(payload: dict[str, Any], fields: Iterable[str]) -> Any:
    for field in fields:
        value = _jsonish(payload.get(field))
        if value not in (None, "", []):
            return value
    return None


def _first_text(payload: dict[str, Any], fields: Iterable[str]) -> str | None:
    value = _first(payload, fields)
    if value is None:
        return None
    values = as_list(value)
    return values[0].strip() if values else None


def _external_id(payload: dict[str, Any], *, fallback_name: str | None = None) -> str:
    for field in ("ewg_id", "ewg_product_id", "product_id", "ingredient_id", "id", "external_id"):
        value = payload.get(field)
        if value not in (None, ""):
            return str(value).strip()
    source_url = _first_text(payload, SOURCE_URL_FIELDS)
    if source_url:
        match = re.search(r"/(?:products|ingredients)/([^/?#]+)/?", source_url)
        if match:
            return match.group(1)
        return source_url.rstrip("/").rsplit("/", 1)[-1]
    barcode = _first_text(payload, BARCODE_FIELDS)
    if barcode:
        return barcode
    return normalize_text(fallback_name or json.dumps(payload, sort_keys=True))[:240]


def _timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int) or str(value).isdigit():
        try:
            return datetime.fromtimestamp(int(value), UTC)
        except (ValueError, OSError):
            return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%B %Y", "%b %Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def _upsert_brand(db: Session, name: str, source_record_code: str) -> Brand | None:
    clean = name.strip()
    if not clean:
        return None
    normalized = normalize_text(clean)
    brand = db.scalar(select(Brand).where(Brand.normalized_name == normalized))
    if brand is None:
        brand = Brand(
            brand_code=make_code("brd", normalized),
            name=clean,
            normalized_name=normalized,
            source_record_code=source_record_code,
        )
        db.add(brand)
        db.flush()
    else:
        brand.source_record_code = brand.source_record_code or source_record_code
    return brand


def _upsert_category(db: Session, raw: str) -> Category:
    name = raw.replace("en:", "").replace("-", " ").strip().title()
    slug = slugify(raw)
    category = db.scalar(select(Category).where(Category.slug == slug))
    if category is None:
        category = Category(category_code=make_code("cat", slug), name=name, slug=slug)
        db.add(category)
        db.flush()
    return category


def _upsert_ingredient(
    db: Session,
    raw_name: str,
    source_record_code: str,
    *,
    cas_number: str | None = None,
) -> Ingredient:
    canonical = canonical_ingredient_name(raw_name)
    normalized = normalize_text(canonical)
    ingredient = db.scalar(select(Ingredient).where(Ingredient.normalized_name == normalized))
    if ingredient is None:
        ingredient = Ingredient(
            ingredient_code=make_code("ing", normalized),
            canonical_name=canonical,
            normalized_name=normalized,
            inci_name=canonical.upper(),
            cas_number=cas_number,
            functions=[],
            regulatory_status="ewg-mentioned",
            source_record_code=source_record_code,
        )
        db.add(ingredient)
        db.flush()
    else:
        ingredient.source_record_code = ingredient.source_record_code or source_record_code
        ingredient.cas_number = ingredient.cas_number or cas_number
    return ingredient


def _ingredient_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    structured = _jsonish(payload.get("ingredients"))
    if isinstance(structured, list):
        rows = [row for row in structured if isinstance(row, dict)]
        if rows:
            return rows
        return [{"name": str(row)} for row in structured if str(row).strip()]
    ingredient_text = _first_text(payload, INGREDIENT_TEXT_FIELDS)
    return [{"name": value} for value in split_ewg_ingredients(ingredient_text)]


def _ingredient_name(row: dict[str, Any]) -> str | None:
    for field in ("name", "ingredient_name", "text", "inci_name", "canonical_name"):
        value = row.get(field)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _ingredient_external_id(row: dict[str, Any], raw_name: str) -> str:
    for field in ("ewg_id", "ingredient_id", "id", "external_id"):
        value = row.get(field)
        if value not in (None, ""):
            return str(value).strip()
    return normalize_text(raw_name)


def _category_values(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in CATEGORY_FIELDS:
        values.extend(as_list(_jsonish(payload.get(field))))
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _ingredient_fingerprint(values: list[str]) -> set[str]:
    return {normalize_text(value) for value in values if normalize_text(value)}


def _product_ingredient_names(product: Product) -> list[str]:
    return [link.ingredient.normalized_name for link in product.ingredients if link.ingredient]


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _find_matching_product(
    db: Session,
    *,
    barcode: str | None,
    name: str,
    brand: Brand | None,
    categories: list[str],
    ingredient_names: list[str],
    review_threshold: float,
) -> ProductMatch:
    if barcode:
        product = db.scalar(select(Product).where(Product.barcode == barcode))
        if product is not None:
            return ProductMatch(product=product, method="barcode_exact", confidence=1.0)

    if brand is None:
        return ProductMatch(product=None, method="new_ewg_product", confidence=0)

    candidates = db.scalars(select(Product).where(Product.brand_code == brand.brand_code)).all()
    if not candidates:
        return ProductMatch(product=None, method="new_ewg_product", confidence=0)

    category_fingerprint = _ingredient_fingerprint(categories)
    ingredient_fingerprint = _ingredient_fingerprint(ingredient_names)
    best_product: Product | None = None
    best_score = 0.0
    for candidate in candidates:
        name_score = fuzz.token_set_ratio(name, candidate.name) / 100
        if name_score < 0.78:
            continue
        candidate_categories = _ingredient_fingerprint([candidate.category_text or ""])
        category_score = _jaccard(category_fingerprint, candidate_categories) if category_fingerprint else 0.5
        candidate_ingredients = set(_product_ingredient_names(candidate))
        ingredient_score = _jaccard(ingredient_fingerprint, candidate_ingredients) if ingredient_fingerprint else 0.4
        if ingredient_fingerprint and candidate_ingredients and ingredient_score < 0.25:
            continue
        score = (name_score * 0.55) + (ingredient_score * 0.3) + (category_score * 0.15)
        if score > best_score:
            best_score = score
            best_product = candidate

    if best_product is not None and best_score >= review_threshold:
        return ProductMatch(product=best_product, method="brand_name_ingredient_fuzzy", confidence=best_score)
    return ProductMatch(product=None, method="new_ewg_product", confidence=best_score)


def _first_ingredient_text(payload: dict[str, Any], rows: list[dict[str, Any]]) -> str | None:
    text = _first_text(payload, INGREDIENT_TEXT_FIELDS)
    if text:
        return text
    names = [_ingredient_name(row) for row in rows]
    clean_names = [name for name in names if name]
    return ", ".join(clean_names) if clean_names else None


def _booleanish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return normalize_text(str(value)) in {"true", "yes", "1", "ewg verified", "verified"}


def _link_product_terms(db: Session, product: Product, record, payload: dict[str, Any]) -> None:
    for category in _category_values(payload):
        link_product_term(
            db,
            product=product,
            record=record,
            term_type="category",
            raw_value=category,
            confidence_score=0.9,
        )
    term_fields = {
        "product_form": ("form", "product_form", "composition", "format"),
        "exposure_type": ("exposure_type", "use_type", "application_type"),
        "body_area": ("body_area", "body_areas", "exposed_body_area", "exposed_areas"),
        "claim": ("claims", "special_claims", "label_claims"),
        "warning": ("warnings", "directions", "directions_for_use"),
        "target_context": ("target_demographic", "marketed_for", "target_user"),
        "data_availability": ("data_availability", "data_availability_rating"),
    }
    for term_type, fields in term_fields.items():
        for field in fields:
            for value in as_list(_jsonish(payload.get(field))):
                link_product_term(
                    db,
                    product=product,
                    record=record,
                    term_type=term_type,
                    raw_value=value,
                    confidence_score=0.86,
                )
    for value in as_list(_jsonish(payload.get("certifications"))):
        link_product_term(
            db,
            product=product,
            record=record,
            term_type="certification",
            raw_value=value,
            confidence_score=0.9,
        )
    if _booleanish(payload.get("ewg_verified") or payload.get("verified")):
        link_product_term(
            db,
            product=product,
            record=record,
            term_type="certification",
            raw_value="EWG Verified",
            confidence_score=0.92,
        )
    for concern in _concern_items(payload.get("concerns") or payload.get("ingredient_concerns")):
        link_product_term(
            db,
            product=product,
            record=record,
            term_type="concern",
            raw_value=concern["name"],
            confidence_score=0.84,
        )


def _persist_product_facts(db: Session, product: Product, record, payload: dict[str, Any]) -> None:
    fact_fields = {
        "hazard_score": "rating",
        "hazard_score_label": "rating",
        "data_availability": "rating",
        "data_availability_score": "rating",
        "ewg_verified": "certification",
        "animal_testing_policy": "policy",
        "animal_testing_summary": "policy",
        "image_url": "media",
        "product_page_title": "page",
        "scraped_at": "scrape",
        "scrape_status": "scrape",
        "page_headings": "page",
        "score_image_alt": "rating",
    }
    for field, fact_type in fact_fields.items():
        upsert_source_fact(
            db,
            record=record,
            entity_kind="product",
            product=product,
            fact_type=fact_type,
            field_name=field,
            label=field.replace("_", " ").title(),
            value=payload.get(field),
            confidence_score=0.82,
        )
    for field in (
        "claims",
        "warnings",
        "directions",
        "target_demographic",
        "exposure_type",
        "product_form",
        "body_area",
        "certifications",
    ):
        upsert_source_fact(
            db,
            record=record,
            entity_kind="product",
            product=product,
            fact_type="attribute",
            field_name=field,
            label=field.replace("_", " ").title(),
            value=payload.get(field),
            confidence_score=0.78,
        )


def _persist_ingredient_facts(
    db: Session,
    ingredient: Ingredient,
    record,
    row: dict[str, Any],
) -> None:
    for field, fact_type in {
        "hazard_score": "rating",
        "data_availability": "rating",
        "ingredient_url": "page",
        "score_image_alt": "rating",
        "concern_references": "evidence",
    }.items():
        upsert_source_fact(
            db,
            record=record,
            entity_kind="ingredient",
            ingredient=ingredient,
            fact_type=fact_type,
            field_name=field,
            label=field.replace("_", " ").title(),
            value=row.get(field),
            source_url=row.get("ingredient_url") or record.source_url,
            confidence_score=0.78,
        )


def _concern_items(value: Any) -> list[dict[str, str | None]]:
    items: list[dict[str, str | None]] = []
    if isinstance(value, list):
        for raw in value:
            if isinstance(raw, dict):
                name = raw.get("name") or raw.get("concern") or raw.get("label") or raw.get("category")
                if not name:
                    continue
                level = raw.get("level") or raw.get("rating") or raw.get("severity")
                items.append({"name": str(name), "level": str(level).lower() if level else None})
            elif raw is not None:
                level = None
                name = str(raw)
                match = re.search(r"\((low|moderate|high|critical)\)", name, flags=re.IGNORECASE)
                if match:
                    level = match.group(1).lower()
                    name = re.sub(r"\((low|moderate|high|critical)\)", "", name, flags=re.IGNORECASE).strip()
                if name:
                    items.append({"name": name, "level": level})
    else:
        for item in as_list(_jsonish(value)):
            level = None
            name = item
            match = re.search(r"\((low|moderate|high|critical)\)", item, flags=re.IGNORECASE)
            if match:
                level = match.group(1).lower()
                name = re.sub(r"\((low|moderate|high|critical)\)", "", item, flags=re.IGNORECASE).strip()
            if name:
                items.append({"name": name, "level": level})
    return list({(item["name"], item["level"]): item for item in items}.values())


def _concern_severity(level: str | None, concern_slug: str) -> tuple[str, int]:
    if level in {"critical", "high"}:
        return "high", 4
    if level == "moderate":
        return "moderate", 3
    if concern_slug in {"cancer", "reproductive-developmental", "contamination"}:
        return "moderate", 3
    return "low", 2


def _applies_to_for_concern(concern_slug: str) -> dict[str, Any] | None:
    if concern_slug in {"allergy-immunotoxicity", "irritation", "enhanced-absorption"}:
        return {
            "skin_types": ["sensitive"],
            "scalp_types": ["sensitive"],
            "conditions": ["eczema", "contact dermatitis", "rosacea"],
        }
    if concern_slug == "reproductive-developmental":
        return {"pregnancy": ["true"], "lactation": ["true"]}
    if concern_slug in {
        "cancer",
        "contamination",
        "use-restriction",
        "neurotoxicity",
        "organ-system-toxicity",
    }:
        return {"always": True}
    return None


def _seed_ewg_risk_rule(
    db: Session,
    *,
    ingredient: Ingredient,
    record,
    concern_name: str,
    level: str | None,
) -> None:
    concern_slug = canonical_concern_slug(concern_name)
    applies_to = _applies_to_for_concern(concern_slug)
    if applies_to is None:
        return
    severity, score = _concern_severity(level, concern_slug)
    title = f"EWG concern: {concern_name.strip().title()}"
    code = make_code("rr", f"ewg:{record.source_record_code}:{ingredient.ingredient_code}:{concern_slug}")
    summary = (
        f"EWG Skin Deep lists {concern_name.strip()} as a concern for this ingredient. "
        "This rule uses EWG as source evidence and does not treat the concern as a diagnosis."
    )
    rule = db.get(RiskRule, code)
    if rule is None:
        rule = RiskRule(
            risk_rule_code=code,
            ingredient_code=ingredient.ingredient_code,
            source_record_code=record.source_record_code,
            title=title,
            summary=summary,
            severity=severity,
            severity_score=score,
            side_effects=[concern_name.strip().lower()],
            applies_to=applies_to,
            evidence_kind="ewg-skin-deep-concern",
            confidence_score=0.55 if severity == "low" else 0.62,
            version="1",
            active=True,
        )
        db.add(rule)
    else:
        rule.title = title
        rule.summary = summary
        rule.severity = severity
        rule.severity_score = score
        rule.side_effects = [concern_name.strip().lower()]
        rule.applies_to = applies_to
        rule.evidence_kind = "ewg-skin-deep-concern"
        rule.confidence_score = 0.55 if severity == "low" else 0.62
        rule.active = True


def _upsert_product_ingredient(
    db: Session,
    *,
    product: Product,
    ingredient: Ingredient,
    raw_name: str,
    rank: int,
    source_record_code: str,
) -> None:
    link_code = make_code("ping", f"{product.product_code}:{ingredient.ingredient_code}")
    link = db.get(ProductIngredient, link_code)
    if link is None:
        db.add(
            ProductIngredient(
                product_ingredient_code=link_code,
                product_code=product.product_code,
                ingredient_code=ingredient.ingredient_code,
                raw_name=raw_name,
                rank=rank,
                source_record_code=source_record_code,
            )
        )
    else:
        link.source_record_code = link.source_record_code or source_record_code


def import_ewg_product_payload(
    db: Session,
    payload: dict[str, Any],
    *,
    review_threshold: float = 0.82,
    dry_run: bool = False,
) -> Product | None:
    ensure_ewg_source(db)
    name = _first_text(payload, PRODUCT_NAME_FIELDS)
    if not name:
        return None
    brand_name = _first_text(payload, BRAND_FIELDS) or ""
    barcode = _first_text(payload, BARCODE_FIELDS)
    source_url = _first_text(payload, SOURCE_URL_FIELDS)
    source_updated_at = _timestamp(_first(payload, UPDATED_AT_FIELDS))
    external_id = _external_id(payload, fallback_name=name)

    if dry_run:
        return None

    record = upsert_source_record(
        db,
        source_code=EWG_SOURCE_CODE,
        external_id=external_id,
        record_type="product",
        payload=payload,
        source_url=source_url or f"https://www.ewg.org/skindeep/products/{external_id}/",
    )
    brand = _upsert_brand(db, brand_name, record.source_record_code)
    rows = _ingredient_rows(payload)
    ingredient_names = [name for row in rows if (name := _ingredient_name(row))]
    category_values = _category_values(payload)
    ingredient_text = _first_ingredient_text(payload, rows)
    match = _find_matching_product(
        db,
        barcode=barcode,
        name=name,
        brand=brand,
        categories=category_values,
        ingredient_names=ingredient_names,
        review_threshold=review_threshold,
    )
    product = match.product
    if product is None:
        product = Product(
            product_code=make_code("prd", f"ewg:{external_id}"),
            barcode=barcode,
            name=name,
            normalized_name=normalize_text(name),
            brand_code=brand.brand_code if brand else None,
            source_record_code=record.source_record_code,
            category_text=", ".join(category_values) or None,
            ingredient_text=ingredient_text,
            data_quality_warnings=[],
            confidence_score=0.88,
            last_source_update_at=source_updated_at,
        )
        db.add(product)
        match = ProductMatch(product=product, method="new_ewg_product", confidence=max(match.confidence, 0.88))
    else:
        product.source_record_code = product.source_record_code or record.source_record_code
        product.last_source_update_at = max(
            [date for date in [product.last_source_update_at, source_updated_at] if date],
            default=product.last_source_update_at,
        )
        product.confidence_score = max(product.confidence_score, min(0.95, match.confidence))
        if ingredient_text and not product.ingredient_text:
            product.ingredient_text = ingredient_text
        if category_values and not product.category_text:
            product.category_text = ", ".join(category_values)

    link_product_source(
        db,
        product=product,
        record=record,
        external_id=external_id,
        match_method=match.method,
        match_confidence=match.confidence,
        source_updated_at=source_updated_at,
    )
    _link_product_terms(db, product, record, payload)
    _persist_product_facts(db, product, record, payload)

    for raw_category in category_values:
        category = _upsert_category(db, raw_category)
        if not any(link.category_code == category.category_code for link in product.categories):
            product.categories.append(
                ProductCategory(
                    product_code=product.product_code,
                    category_code=category.category_code,
                )
            )

    for index, row in enumerate(rows, start=1):
        raw_name = _ingredient_name(row)
        if not raw_name:
            continue
        ingredient = _upsert_ingredient(
            db,
            raw_name,
            record.source_record_code,
            cas_number=str(row.get("cas_number") or row.get("cas") or "") or None,
        )
        link_ingredient_source(
            db,
            ingredient=ingredient,
            record=record,
            external_id=_ingredient_external_id(row, raw_name),
            match_method="ewg_ingredient",
            match_confidence=0.9,
        )
        functions = as_list(row.get("functions") or row.get("function"))
        if functions:
            existing = set(ingredient.functions or [])
            ingredient.functions = sorted(existing | set(functions))
        for function_name in functions:
            link_ingredient_term(
                db,
                ingredient=ingredient,
                record=record,
                term_type="ingredient_function",
                raw_value=function_name,
                confidence_score=0.86,
            )
        _persist_ingredient_facts(db, ingredient, record, row)
        concern_values = row.get("concerns") or row.get("common_concerns") or row.get("concern_buckets")
        for concern in _concern_items(concern_values):
            link_ingredient_term(
                db,
                ingredient=ingredient,
                record=record,
                term_type="concern",
                raw_value=concern["name"] or "",
                confidence_score=0.84,
            )
            _seed_ewg_risk_rule(
                db,
                ingredient=ingredient,
                record=record,
                concern_name=concern["name"] or "",
                level=concern["level"],
            )
        _upsert_product_ingredient(
            db,
            product=product,
            ingredient=ingredient,
            raw_name=raw_name,
            rank=index,
            source_record_code=record.source_record_code,
        )
    return product


def import_ewg_ingredient_payload(db: Session, payload: dict[str, Any], *, dry_run: bool = False) -> Ingredient | None:
    ensure_ewg_source(db)
    raw_name = _first_text(payload, ("ingredient_name", "name", "canonical_name", "inci_name"))
    if not raw_name:
        return None
    if dry_run:
        return None
    external_id = _external_id(payload, fallback_name=raw_name)
    source_url = _first_text(payload, SOURCE_URL_FIELDS)
    record = upsert_source_record(
        db,
        source_code=EWG_SOURCE_CODE,
        external_id=external_id,
        record_type="ingredient",
        payload=payload,
        source_url=source_url or f"https://www.ewg.org/skindeep/ingredients/{external_id}/",
    )
    ingredient = _upsert_ingredient(
        db,
        raw_name,
        record.source_record_code,
        cas_number=_first_text(payload, ("cas_number", "cas")),
    )
    link_ingredient_source(
        db,
        ingredient=ingredient,
        record=record,
        external_id=external_id,
        match_method="ewg_ingredient",
        match_confidence=0.95,
    )
    for synonym in as_list(payload.get("synonyms")):
        link_ingredient_term(
            db,
            ingredient=ingredient,
            record=record,
            term_type="ingredient_synonym",
            raw_value=synonym,
            confidence_score=0.78,
        )
    for function_name in as_list(payload.get("functions") or payload.get("function")):
        link_ingredient_term(
            db,
            ingredient=ingredient,
            record=record,
            term_type="ingredient_function",
            raw_value=function_name,
            confidence_score=0.86,
        )
    for concern in _concern_items(payload.get("concerns") or payload.get("common_concerns")):
        link_ingredient_term(
            db,
            ingredient=ingredient,
            record=record,
            term_type="concern",
            raw_value=concern["name"] or "",
            confidence_score=0.84,
        )
        _seed_ewg_risk_rule(
            db,
            ingredient=ingredient,
            record=record,
            concern_name=concern["name"] or "",
            level=concern["level"],
        )
    _persist_ingredient_facts(db, ingredient, record, payload)
    return ingredient


def _looks_like_ingredient_payload(payload: dict[str, Any]) -> bool:
    if any(field in payload for field in PRODUCT_NAME_FIELDS):
        return False
    return any(field in payload for field in ("ingredient_name", "canonical_name", "inci_name"))


def import_ewg_skin_deep(
    db: Session,
    source_path: str,
    *,
    limit: int = 1000,
    review_threshold: float = 0.82,
    dry_run: bool = False,
) -> dict[str, int]:
    ensure_ewg_source(db)
    counts = {"products": 0, "ingredients": 0, "skipped": 0}
    for row in _iter_rows(source_path):
        if counts["products"] + counts["ingredients"] >= limit:
            break
        if _looks_like_ingredient_payload(row):
            imported_ingredient = import_ewg_ingredient_payload(db, row, dry_run=dry_run)
            counts["ingredients" if imported_ingredient is not None else "skipped"] += 1
            continue
        imported_product = import_ewg_product_payload(
            db,
            row,
            review_threshold=review_threshold,
            dry_run=dry_run,
        )
        counts["products" if imported_product is not None else "skipped"] += 1
    return counts


def ingredient_concern_terms(db: Session, ingredient_code: str) -> list[str]:
    rows = db.scalars(
        select(IngredientTermLink).where(IngredientTermLink.ingredient_code == ingredient_code)
    ).all()
    return sorted({row.term.slug for row in rows if row.term and row.term.term_type == "concern"})
