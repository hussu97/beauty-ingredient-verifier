from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    Brand,
    Category,
    Ingredient,
    Product,
    ProductCategory,
    ProductImage,
    ProductIngredient,
    SourceRecord,
)
from app.services.codes import make_code
from app.services.normalization import (
    canonical_ingredient_name,
    normalize_text,
    slugify,
    split_ingredients,
)
from app.services.source_records import upsert_source, upsert_source_record
from app.services.source_fusion import link_ingredient_source, link_product_source, link_product_term

OPEN_BEAUTY_FACTS_SOURCE_CODE = "src_open_beauty_facts"
OPEN_BEAUTY_FACTS_IMAGE_BASE_URL = "https://images.openbeautyfacts.org/images/products"


@dataclass(frozen=True)
class DerivedImage:
    kind: str
    url: str
    width: int | None = None
    height: int | None = None

SAMPLE_PRODUCTS: list[dict[str, Any]] = [
    {
        "code": "3560070791460",
        "product_name": "Solution dentaire active anti-plaque",
        "brands": "Carrefour",
        "categories": "Hygiene, Mouthwash",
        "categories_tags": ["en:hygiene", "en:mouthwash"],
        "ingredients_text": "AQUA, ALCOHOL, GLYCERIN, SORBITOL, SODIUM BENZOATE, POLYSORBATE 20, AROMA, SODIUM SACCHARINE, CETYLPYRIDINIUM CHLORIDE, SODIUM FLUORIDE, CITRIC ACID, LIMONENE, CI 16255.",
        "ingredients": [
            {"text": "AQUA", "rank": 1},
            {"text": "ALCOHOL", "rank": 2},
            {"text": "GLYCERIN", "rank": 3},
            {"text": "SODIUM BENZOATE", "rank": 5},
            {"text": "LIMONENE", "rank": 12},
        ],
        "allergens_tags": ["en:limonene"],
        "image_front_url": "https://images.openbeautyfacts.org/images/products/356/007/079/1460/front_fr.10.400.jpg",
        "image_ingredients_url": "https://images.openbeautyfacts.org/images/products/356/007/079/1460/ingredients_fr.9.400.jpg",
        "last_modified_t": 1491327417,
        "data_quality_warnings_tags": ["en:demo-seed-open-data"],
    },
    {
        "code": "demo-sensitive-cleanser",
        "product_name": "Sensitive Balance Gel Cleanser",
        "brands": "Local Demo Lab",
        "categories": "Skincare, Facial cleanser",
        "categories_tags": ["en:skin-care", "en:facial-cleansers"],
        "ingredients_text": "Aqua, Glycerin, Cocamidopropyl Betaine, Sodium Benzoate, Citric Acid, Parfum, Linalool.",
        "ingredients": [
            {"text": "Aqua", "rank": 1},
            {"text": "Glycerin", "rank": 2},
            {"text": "Cocamidopropyl Betaine", "rank": 3},
            {"text": "Sodium Benzoate", "rank": 4},
            {"text": "Parfum", "rank": 6},
            {"text": "Linalool", "rank": 7},
        ],
        "image_front_url": "https://images.unsplash.com/photo-1556228720-195a672e8a03?auto=format&fit=crop&w=900&q=80",
        "image_ingredients_url": None,
        "last_modified_t": 1781733600,
        "data_quality_warnings_tags": ["en:demo-product-not-commercial"],
    },
    {
        "code": "demo-hair-color",
        "product_name": "Dark Tone Permanent Hair Color",
        "brands": "Local Demo Lab",
        "categories": "Hair care, Hair dye",
        "categories_tags": ["en:hair-care", "en:hair-colorants"],
        "ingredients_text": "Aqua, Cetearyl Alcohol, Ammonium Hydroxide, P-Phenylenediamine, Resorcinol, Sodium Sulfite, Parfum.",
        "ingredients": [
            {"text": "Aqua", "rank": 1},
            {"text": "Cetearyl Alcohol", "rank": 2},
            {"text": "Ammonium Hydroxide", "rank": 3},
            {"text": "P-Phenylenediamine", "rank": 4},
            {"text": "Resorcinol", "rank": 5},
            {"text": "Parfum", "rank": 7},
        ],
        "image_front_url": "https://images.unsplash.com/photo-1522338242992-e1a54906a8da?auto=format&fit=crop&w=900&q=80",
        "image_ingredients_url": None,
        "last_modified_t": 1781733600,
        "data_quality_warnings_tags": ["en:demo-product-not-commercial"],
    },
]


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("text"):
                return str(item["text"])
            if isinstance(item, str) and item.strip():
                return item
        return None
    return str(value)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    mode = "rt" if path.suffix == ".gz" else "r"
    with opener(path, mode, encoding="utf-8") as handle:  # type: ignore[arg-type]
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _iter_parquet(path: Path) -> Iterable[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Install backend[data] to import Parquet exports") from exc
    table = pq.read_table(path)
    for row in table.to_pylist():
        yield row


def _iter_rows(source_path: str | None) -> Iterable[dict[str, Any]]:
    if source_path is None:
        yield from SAMPLE_PRODUCTS
        return
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix == ".parquet":
        yield from _iter_parquet(path)
    elif path.suffix in {".jsonl", ".gz"}:
        yield from _iter_jsonl(path)
    else:
        raise ValueError(f"Unsupported import file type: {path}")


def _timestamp(value: Any) -> datetime | None:
    try:
        if value in (None, ""):
            return None
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError, OSError):
        return None


def _barcode_image_path(barcode: str | None) -> str | None:
    if not barcode or not barcode.isdigit():
        return None
    if len(barcode) <= 8:
        return barcode
    parts = [barcode[index : index + 3] for index in range(0, min(len(barcode), 9), 3)]
    if len(barcode) > 9:
        parts.append(barcode[9:])
    return "/".join(part for part in parts if part)


def _candidate_image_keys(images: dict[str, Any], kind: str) -> list[str]:
    exact = [kind, f"{kind}_en", f"{kind}_fr"]
    prefixed = sorted(key for key in images if key.startswith(f"{kind}_") and key not in exact)
    return [key for key in exact if key in images] + prefixed


def _candidate_image_languages(images: dict[str, Any]) -> list[str]:
    exact = ["en", "fr"]
    rest = sorted(key for key in images if key not in exact)
    return [key for key in exact if key in images] + rest


def _numeric_image_keys(images: dict[str, Any]) -> list[str]:
    return sorted((key for key in images if str(key).isdigit()), key=lambda value: int(value))


def _image_size(candidate: dict[str, Any]) -> tuple[int | None, int | None]:
    sizes = candidate.get("sizes") if isinstance(candidate.get("sizes"), dict) else {}
    size_400 = sizes.get("400") if isinstance(sizes.get("400"), dict) else {}
    width = size_400.get("w")
    height = size_400.get("h")
    return (
        int(width) if str(width or "").isdigit() else None,
        int(height) if str(height or "").isdigit() else None,
    )


def _derived_image(payload: dict[str, Any], kind: str) -> DerivedImage | None:
    barcode = str(payload.get("code") or payload.get("barcode") or "").strip()
    image_path = _barcode_image_path(barcode)
    images = payload.get("images")
    if not image_path or not isinstance(images, dict):
        return None

    for key in _candidate_image_keys(images, kind):
        candidate = images.get(key)
        if not isinstance(candidate, dict):
            continue
        revision = candidate.get("rev")
        if not revision:
            continue
        width, height = _image_size(candidate)
        return DerivedImage(
            kind=kind,
            url=f"{OPEN_BEAUTY_FACTS_IMAGE_BASE_URL}/{image_path}/{key}.{revision}.400.jpg",
            width=width,
            height=height,
        )

    selected = images.get("selected")
    if isinstance(selected, dict):
        for selected_key in _candidate_image_keys(selected, kind):
            selected_value = selected.get(selected_key)
            if not isinstance(selected_value, dict):
                continue
            revision = selected_value.get("rev")
            if revision:
                width, height = _image_size(selected_value)
                return DerivedImage(
                    kind=kind,
                    url=(
                        f"{OPEN_BEAUTY_FACTS_IMAGE_BASE_URL}/"
                        f"{image_path}/{selected_key}.{revision}.400.jpg"
                    ),
                    width=width,
                    height=height,
                )
            for language in _candidate_image_languages(selected_value):
                candidate = selected_value.get(language)
                if not isinstance(candidate, dict):
                    continue
                revision = candidate.get("rev")
                if not revision:
                    continue
                width, height = _image_size(candidate)
                image_key = f"{selected_key}_{language}"
                return DerivedImage(
                    kind=kind,
                    url=(
                        f"{OPEN_BEAUTY_FACTS_IMAGE_BASE_URL}/"
                        f"{image_path}/{image_key}.{revision}.400.jpg"
                    ),
                    width=width,
                    height=height,
                )

    if kind != "front":
        return None
    uploaded = images.get("uploaded") if isinstance(images.get("uploaded"), dict) else images
    for image_id in _numeric_image_keys(uploaded):
        candidate = uploaded.get(image_id)
        if not isinstance(candidate, dict):
            continue
        width, height = _image_size(candidate)
        return DerivedImage(
            kind="uploaded",
            url=f"{OPEN_BEAUTY_FACTS_IMAGE_BASE_URL}/{image_path}/{image_id}.400.jpg",
            width=width,
            height=height,
        )
    return None


def _derived_images(payload: dict[str, Any]) -> list[DerivedImage]:
    images: list[DerivedImage] = []
    derived_front = _derived_image(payload, "front")
    derived_ingredients = _derived_image(payload, "ingredients")
    if derived_front is not None:
        images.append(derived_front)
    elif payload.get("image_front_url"):
        images.append(DerivedImage(kind="front", url=str(payload["image_front_url"])))
    if derived_ingredients is not None:
        images.append(derived_ingredients)
    elif payload.get("image_ingredients_url"):
        images.append(DerivedImage(kind="ingredients", url=str(payload["image_ingredients_url"])))
    return images


def _upsert_product_images(
    db: Session,
    product: Product,
    source_record_code: str,
    images: list[DerivedImage],
) -> int:
    added = 0
    for image in images:
        image_code = make_code("img", f"{product.product_code}:{image.kind}:{image.url}")
        if db.get(ProductImage, image_code) is None:
            db.add(
                ProductImage(
                    image_code=image_code,
                    product_code=product.product_code,
                    kind=image.kind,
                    url=image.url,
                    width=image.width,
                    height=image.height,
                    source_record_code=source_record_code,
                )
            )
            added += 1
    return added


def ensure_open_beauty_facts_source(db: Session) -> None:
    upsert_source(
        db,
        source_code=OPEN_BEAUTY_FACTS_SOURCE_CODE,
        name="Open Beauty Facts",
        kind="open-product-database",
        homepage_url="https://world.openbeautyfacts.org/",
        license_name="ODbL / DbCL; images CC BY-SA",
        terms_url="https://world.openbeautyfacts.org/terms-of-use",
        reliability="crowdsourced-open-data",
    )


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
        brand.name = clean
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


def _upsert_ingredient(db: Session, raw_name: str, source_record_code: str) -> Ingredient:
    canonical = canonical_ingredient_name(raw_name)
    normalized = normalize_text(canonical)
    ingredient = db.scalar(select(Ingredient).where(Ingredient.normalized_name == normalized))
    if ingredient is None:
        ingredient = Ingredient(
            ingredient_code=make_code("ing", normalized),
            canonical_name=canonical,
            normalized_name=normalized,
            inci_name=canonical.upper(),
            functions=[],
            regulatory_status="unknown",
            source_record_code=source_record_code,
        )
        db.add(ingredient)
        db.flush()
    else:
        ingredient.source_record_code = ingredient.source_record_code or source_record_code
    return ingredient


def import_product_payload(db: Session, payload: dict[str, Any], *, source_url: str | None = None) -> Product | None:
    ensure_open_beauty_facts_source(db)
    barcode = str(payload.get("code") or payload.get("barcode") or "").strip() or None
    name = _coerce_text(payload.get("product_name")) or _coerce_text(payload.get("generic_name"))
    if not name:
        return None

    external_id = barcode or normalize_text(f"{payload.get('brands')}:{name}")
    record = upsert_source_record(
        db,
        source_code=OPEN_BEAUTY_FACTS_SOURCE_CODE,
        external_id=external_id,
        record_type="product",
        payload=payload,
        source_url=source_url or (f"https://world.openbeautyfacts.org/product/{barcode}" if barcode else None),
    )
    brand_name = _coerce_text(payload.get("brands")) or ""
    brand = _upsert_brand(db, brand_name.split(",")[0], record.source_record_code)

    product_code = make_code("prd", f"obf:{external_id}")
    product = db.get(Product, product_code)
    ingredient_text = _coerce_text(payload.get("ingredients_text"))
    if product is None:
        product = Product(
            product_code=product_code,
            barcode=barcode,
            name=name,
            normalized_name=normalize_text(name),
            brand_code=brand.brand_code if brand else None,
            source_record_code=record.source_record_code,
            category_text=_coerce_text(payload.get("categories")),
            ingredient_text=ingredient_text,
            data_quality_warnings=list(payload.get("data_quality_warnings_tags") or []),
            confidence_score=0.72 if barcode else 0.55,
            last_source_update_at=_timestamp(payload.get("last_modified_t")),
        )
        db.add(product)
    else:
        product.barcode = barcode or product.barcode
        product.name = name
        product.normalized_name = normalize_text(name)
        product.brand_code = brand.brand_code if brand else product.brand_code
        product.source_record_code = record.source_record_code
        product.category_text = _coerce_text(payload.get("categories"))
        product.ingredient_text = ingredient_text
        product.data_quality_warnings = list(payload.get("data_quality_warnings_tags") or [])
        product.last_source_update_at = _timestamp(payload.get("last_modified_t"))

    link_product_source(
        db,
        product=product,
        record=record,
        external_id=external_id,
        match_method="open_beauty_facts_primary",
        match_confidence=1.0,
        source_updated_at=_timestamp(payload.get("last_modified_t")),
    )

    if product.category_text:
        for raw_category in [part.strip() for part in product.category_text.split(",") if part.strip()]:
            link_product_term(
                db,
                product=product,
                record=record,
                term_type="category",
                raw_value=raw_category,
                confidence_score=0.72,
            )
    for warning in payload.get("data_quality_warnings_tags") or []:
        link_product_term(
            db,
            product=product,
            record=record,
            term_type="data_quality",
            raw_value=str(warning),
            confidence_score=0.7,
        )

    for raw_category in payload.get("categories_tags") or []:
        category = _upsert_category(db, str(raw_category))
        exists = any(link.category_code == category.category_code for link in product.categories)
        if not exists:
            product.categories.append(ProductCategory(product_code=product.product_code, category_code=category.category_code))
        link_product_term(
            db,
            product=product,
            record=record,
            term_type="category",
            raw_value=str(raw_category),
            confidence_score=0.76,
        )

    structured = payload.get("ingredients")
    ingredient_rows: list[dict[str, Any]]
    if isinstance(structured, str):
        try:
            parsed = json.loads(structured)
            ingredient_rows = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            ingredient_rows = []
    elif isinstance(structured, list):
        ingredient_rows = [row for row in structured if isinstance(row, dict)]
    else:
        ingredient_rows = []

    if not ingredient_rows:
        ingredient_rows = [{"text": value, "rank": index + 1} for index, value in enumerate(split_ingredients(ingredient_text))]

    for index, row in enumerate(ingredient_rows):
        raw = str(row.get("text") or row.get("id") or "").strip()
        if not raw:
            continue
        ingredient = _upsert_ingredient(db, raw, record.source_record_code)
        link_ingredient_source(
            db,
            ingredient=ingredient,
            record=record,
            external_id=str(row.get("id") or row.get("text") or raw),
            match_method="open_beauty_facts_ingredient",
            match_confidence=0.78,
        )
        link_code = make_code("ping", f"{product.product_code}:{ingredient.ingredient_code}")
        link = db.get(ProductIngredient, link_code)
        if link is None:
            link = ProductIngredient(
                product_ingredient_code=link_code,
                product_code=product.product_code,
                ingredient_code=ingredient.ingredient_code,
                raw_name=raw,
                rank=row.get("rank") or index + 1,
                percent_min=row.get("percent_min"),
                percent_max=row.get("percent_max"),
                percent_estimate=row.get("percent_estimate"),
                source_record_code=record.source_record_code,
            )
            db.add(link)

    _upsert_product_images(db, product, record.source_record_code, _derived_images(payload))
    return product


def backfill_open_beauty_facts_images(db: Session, limit: int | None = None) -> int:
    query = (
        select(Product, SourceRecord)
        .join(SourceRecord, Product.source_record_code == SourceRecord.source_record_code)
        .where(SourceRecord.source_code == OPEN_BEAUTY_FACTS_SOURCE_CODE)
        .order_by(Product.product_code)
    )
    if limit is not None:
        query = query.limit(limit)

    added = 0
    for product, record in db.execute(query):
        if not isinstance(record.payload, dict):
            continue
        added += _upsert_product_images(
            db,
            product,
            record.source_record_code,
            _derived_images(record.payload),
        )
    return added


def import_open_beauty_facts(db: Session, source_path: str | None, limit: int = 1000) -> int:
    count = 0
    for row in _iter_rows(source_path):
        if count >= limit:
            break
        product = import_product_payload(db, row)
        if product is not None:
            count += 1
    return count


def lookup_open_beauty_facts_barcode(db: Session, barcode: str) -> Product | None:
    settings = get_settings()
    if not settings.enable_live_open_beauty_facts_lookup:
        return None
    fields = ",".join(
        [
            "code",
            "product_name",
            "brands",
            "categories",
            "categories_tags",
            "ingredients_text",
            "ingredients",
            "allergens_tags",
            "image_front_url",
            "image_ingredients_url",
            "last_modified_t",
            "data_quality_warnings_tags",
        ]
    )
    url = f"https://world.openbeautyfacts.org/api/v2/product/{barcode}.json"
    response = httpx.get(
        url,
        params={"fields": fields},
        headers={"User-Agent": settings.open_beauty_facts_user_agent},
        timeout=8,
    )
    if response.status_code != 200:
        return None
    payload = response.json()
    if payload.get("status") != 1:
        return None
    return import_product_payload(db, payload.get("product") or {}, source_url=url)
