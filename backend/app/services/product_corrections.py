from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Ingredient, Product, ProductIngredient
from app.services.codes import make_code
from app.services.normalization import canonical_ingredient_name, normalize_text, split_ingredients
from app.services.source_records import upsert_source, upsert_source_record


MAC_COSMETICS_SOURCE_CODE = "src_mac_cosmetics"


@dataclass(frozen=True)
class ProductIngredientCorrection:
    product_code: str
    barcode: str
    name: str
    category_text: str
    source_url: str
    source_title: str
    ingredient_text: str


SOURCE_BACKED_PRODUCT_CORRECTIONS = [
    ProductIngredientCorrection(
        product_code="prd_7e395068110222",
        barcode="0773602603084",
        name="Fix+ Setting Spray",
        category_text="Makeup Setting Spray, Face Mist",
        source_url=(
            "https://www.maccosmetics.com/product/31845/126092/products/makeup/face/"
            "makeup-setting-sprays/fix-setting-spray"
        ),
        source_title="MAC Cosmetics Fix+ Setting Spray",
        ingredient_text=(
            "Water\\Aqua\\Eau, Glycerin, Butylene Glycol, Cucumis Sativus (Cucumber) "
            "Fruit Extract, Chamomilla Recutita (Matricaria) Extract, Camellia Sinensis "
            "Leaf Extract, Tocopheryl Acetate, Caffeine, Panthenol, Arginine, "
            "Peg-40 Hydrogenated Castor Oil, Ppg-26-Buteth-26, Fragrance (Parfum), "
            "Disodium Edta, Phenoxyethanol"
        ),
    )
]


def _ensure_mac_cosmetics_source(db: Session) -> None:
    upsert_source(
        db,
        source_code=MAC_COSMETICS_SOURCE_CODE,
        name="MAC Cosmetics",
        kind="brand-official-product-page",
        homepage_url="https://www.maccosmetics.com/",
        license_name=None,
        terms_url="https://www.maccosmetics.com/terms-conditions",
        reliability="brand-official",
    )


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


def apply_source_backed_product_corrections(db: Session) -> int:
    _ensure_mac_cosmetics_source(db)
    corrected = 0
    for correction in SOURCE_BACKED_PRODUCT_CORRECTIONS:
        product = db.get(Product, correction.product_code)
        if product is None:
            continue

        ingredients = split_ingredients(correction.ingredient_text)
        if not ingredients:
            continue

        record = upsert_source_record(
            db,
            source_code=MAC_COSMETICS_SOURCE_CODE,
            external_id=f"{correction.barcode}:ingredients",
            record_type="product-ingredient-correction",
            source_url=correction.source_url,
            payload={
                "barcode": correction.barcode,
                "product_code": correction.product_code,
                "title": correction.source_title,
                "product_name": correction.name,
                "category_text": correction.category_text,
                "ingredients_text": correction.ingredient_text,
                "correction_reason": "Open Beauty Facts ingredient text was incomplete/truncated.",
            },
        )

        product.name = correction.name
        product.normalized_name = normalize_text(correction.name)
        product.category_text = correction.category_text
        product.ingredient_text = correction.ingredient_text
        product.source_record_code = record.source_record_code
        product.confidence_score = max(product.confidence_score, 0.9)
        warnings = set(product.data_quality_warnings or [])
        warnings.add("source_corrected_open_beauty_facts_incomplete_ingredients")
        product.data_quality_warnings = sorted(warnings)

        db.execute(delete(ProductIngredient).where(ProductIngredient.product_code == product.product_code))
        db.flush()

        for index, raw_name in enumerate(ingredients, start=1):
            ingredient = _upsert_ingredient(db, raw_name, record.source_record_code)
            db.add(
                ProductIngredient(
                    product_ingredient_code=make_code(
                        "ping",
                        f"{product.product_code}:{ingredient.ingredient_code}",
                    ),
                    product_code=product.product_code,
                    ingredient_code=ingredient.ingredient_code,
                    raw_name=raw_name,
                    rank=index,
                    source_record_code=record.source_record_code,
                )
            )
        corrected += 1
    return corrected
