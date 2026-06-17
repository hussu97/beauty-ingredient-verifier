from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Product, ProductImage, ProductIngredient, SourceRecord
from app.services.importers.open_beauty_facts import (
    backfill_open_beauty_facts_images,
    import_open_beauty_facts,
    import_product_payload,
)
from app.services.product_corrections import apply_source_backed_product_corrections


def test_open_beauty_facts_import_is_idempotent(db_session: Session):
    before_products = db_session.scalar(select(func.count()).select_from(Product))
    before_records = db_session.scalar(select(func.count()).select_from(SourceRecord))

    import_open_beauty_facts(db_session, source_path=None, limit=2)
    db_session.commit()
    import_open_beauty_facts(db_session, source_path=None, limit=2)
    db_session.commit()

    after_products = db_session.scalar(select(func.count()).select_from(Product))
    after_records = db_session.scalar(select(func.count()).select_from(SourceRecord))
    links = db_session.scalar(select(func.count()).select_from(ProductIngredient))

    assert after_products == before_products
    assert after_records == before_records
    assert links and links > 0


def test_source_backed_product_correction_replaces_truncated_mac_ingredients(db_session: Session):
    product = import_product_payload(
        db_session,
        {
            "code": "0773602603084",
            "product_name": "Skin Care",
            "brands": "MAC",
            "categories": "skin",
            "categories_tags": ["en:skin"],
            "ingredients_text": "Allerg",
            "ingredients": [{"text": "Allerg", "rank": 1}],
            "images": {
                "ingredients_en": {
                    "rev": "7",
                    "sizes": {"400": {"w": 300, "h": 400}},
                },
            },
        },
    )
    db_session.flush()

    assert product is not None
    assert [link.raw_name for link in product.ingredients] == ["Allerg"]

    corrected = apply_source_backed_product_corrections(db_session)
    db_session.flush()

    db_session.refresh(product)
    links = db_session.scalars(
        select(ProductIngredient)
        .where(ProductIngredient.product_code == product.product_code)
        .order_by(ProductIngredient.rank)
    ).all()

    assert corrected == 1
    assert product.name == "Fix+ Setting Spray"
    assert product.ingredient_text and "Glycerin" in product.ingredient_text
    assert product.source_record_code is not None
    assert "source_corrected_open_beauty_facts_incomplete_ingredients" in product.data_quality_warnings
    assert len(links) == 15
    assert links[0].raw_name == "Water\\Aqua\\Eau"
    assert "Fragrance (Parfum)" in {link.raw_name for link in links}
    assert all(link.raw_name != "Allerg" for link in links)


def test_open_beauty_facts_bulk_images_are_derived(db_session: Session):
    product = import_product_payload(
        db_session,
        {
            "code": "0018787788059",
            "product_name": "All-One Rose Pure-Castile Bar Soap",
            "brands": "Dr. Bronner's",
            "categories": "Hygiene, Soaps",
            "categories_tags": ["en:hygiene", "en:soaps"],
            "ingredients_text": "Organic Coconut Oil, Water, Natural Rose Fragrance",
            "ingredients": [{"text": "Organic Coconut Oil", "rank": 1}],
            "images": {
                "front_en": {
                    "rev": "17",
                    "sizes": {"400": {"w": 400, "h": 260}},
                },
                "ingredients_en": {
                    "rev": "35",
                    "sizes": {"400": {"w": 400, "h": 49}},
                },
            },
        },
    )
    db_session.flush()

    images = db_session.scalars(
        select(ProductImage).where(ProductImage.product_code == product.product_code)
    ).all()
    assert {image.kind for image in images} == {"front", "ingredients"}
    assert images[0].url.startswith(
        "https://images.openbeautyfacts.org/images/products/001/878/778/8059/"
    )
    assert any("front_en.17.400.jpg" in image.url for image in images)


def test_open_beauty_facts_short_barcode_images_are_not_split(db_session: Session):
    product = import_product_payload(
        db_session,
        {
            "code": "00032831",
            "product_name": "Sinful colors Gorgeous 804",
            "brands": "Mirage Cosmetics",
            "categories": "Makeup, Nail polish",
            "ingredients_text": "Citric Acid, Isopropyl Alcohol",
            "ingredients": [{"text": "Citric Acid", "rank": 1}],
            "images": {
                "front_fr": {
                    "rev": "6",
                    "sizes": {"400": {"w": 300, "h": 400}},
                },
            },
        },
    )
    db_session.flush()

    image = db_session.scalar(
        select(ProductImage).where(ProductImage.product_code == product.product_code)
    )

    assert image is not None
    assert image.url == (
        "https://images.openbeautyfacts.org/images/products/00032831/front_fr.6.400.jpg"
    )


def test_open_beauty_facts_nested_selected_images_are_derived(db_session: Session):
    product = import_product_payload(
        db_session,
        {
            "code": "8690506492076",
            "product_name": "Arko Nem Değerli Yağlar Hindistan Cevizi Yağı İçeren Bakım Kremi",
            "brands": "Arko",
            "categories": "Skin care",
            "ingredients_text": "Aqua, Paraffinum Liquidum",
            "ingredients": [{"text": "Aqua", "rank": 1}],
            "images": {
                "selected": {
                    "front": {
                        "tr": {
                            "rev": 6,
                            "sizes": {"400": {"w": 193, "h": 400}},
                        },
                    },
                    "ingredients": {
                        "tr": {
                            "rev": 7,
                            "sizes": {"400": {"w": 400, "h": 280}},
                        },
                    },
                },
                "uploaded": {
                    "1": {
                        "sizes": {"400": {"w": 400, "h": 400}},
                    },
                },
            },
        },
    )
    db_session.flush()

    images = db_session.scalars(
        select(ProductImage).where(ProductImage.product_code == product.product_code)
    ).all()

    assert {image.kind for image in images} == {"front", "ingredients"}
    assert any("front_tr.6.400.jpg" in image.url for image in images)
    assert any(image.width == 193 and image.height == 400 for image in images)


def test_open_beauty_facts_uploaded_image_fallback_is_derived(db_session: Session):
    product = import_product_payload(
        db_session,
        {
            "code": "4068134031402",
            "product_name": "Feuchtes Toilettenpapier",
            "brands": "Penny",
            "ingredients_text": "Aqua",
            "ingredients": [{"text": "Aqua", "rank": 1}],
            "images": {
                "uploaded": {
                    "1": {
                        "sizes": {"400": {"w": 400, "h": 400}},
                    },
                    "2": {
                        "sizes": {"400": {"w": 300, "h": 400}},
                    },
                },
            },
        },
    )
    db_session.flush()

    image = db_session.scalar(
        select(ProductImage).where(ProductImage.product_code == product.product_code)
    )

    assert image is not None
    assert image.kind == "uploaded"
    assert image.url == (
        "https://images.openbeautyfacts.org/images/products/406/813/403/1402/1.400.jpg"
    )


def test_backfill_open_beauty_facts_images_repairs_existing_source_records(db_session: Session):
    product = import_product_payload(
        db_session,
        {
            "code": "4005900107037",
            "product_name": "Creme Soft",
            "brands": "Nivea",
            "ingredients_text": "Aqua, Glycerin",
            "ingredients": [{"text": "Aqua", "rank": 1}],
            "images": {
                "selected": {
                    "front": {
                        "de": {
                            "rev": 3,
                            "sizes": {"400": {"w": 240, "h": 400}},
                        },
                    },
                },
            },
        },
    )
    db_session.flush()
    db_session.query(ProductImage).filter(ProductImage.product_code == product.product_code).delete()
    db_session.flush()

    added = backfill_open_beauty_facts_images(db_session)
    db_session.flush()
    image = db_session.scalar(
        select(ProductImage).where(ProductImage.product_code == product.product_code)
    )

    assert added == 1
    assert image is not None
    assert image.url == (
        "https://images.openbeautyfacts.org/images/products/400/590/010/7037/front_de.3.400.jpg"
    )
