from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Ingredient, Product, ProductIngredient, RiskRule, SourceRecord
from app.services.importers.ewg_public_scraper import (
    PageSnapshot,
    _parse_proxy,
    category_links_from_snapshot,
    is_challenge_snapshot,
    parse_ingredient_snapshot,
    parse_product_snapshot,
    product_links_from_snapshot,
)
from app.services.importers.ewg_skin_deep import import_ewg_product_payload


def test_parse_product_snapshot_extracts_scores_ingredients_and_packaging():
    snapshot = PageSnapshot(
        url="https://www.ewg.org/skindeep/products/9202226-Test_Product/",
        title="EWG Skin Deep® | Example Brand Daily Cream Rating",
        h1="Example Brand Daily Cream",
        text="""
        BRAND
        Example Brand
        CATEGORY
        Facial Moisturizer/Treatment
        DATA LAST UPDATED
        February 2026
        Data Availability: Fair
        WATER
        Data Availability: Robust
        FUNCTION(S) solvent
        CONCERNS
        CAPRYLOHYDROXAMIC ACID
        Data Availability: Limited
        FUNCTION(S) preservative, chelating agent
        CONCERNS • Allergies/immunotoxicity (moderate)
        • Use restrictions (low)
        LEARN MORE ABOUT THIS INGREDIENT
        Ingredients from packaging:
        WATER • CAPRYLOHYDROXAMIC ACID
        Product's animal testing policies
        Unknown
        Leading certifiers have no information.
        Understanding scores
        """,
        links=[
            {
                "href": "https://www.ewg.org/skindeep/ingredients/700000-CAPRYLOHYDROXAMIC_ACID/",
                "text": "LEARN MORE ABOUT THIS INGREDIENT",
            }
        ],
        images=[
            {"src": "https://example.com/product.jpg", "alt": "Product score: 02"},
            {"src": "https://example.com/ingredient-water.png", "alt": "Ingredient score: 01"},
            {"src": "https://example.com/ingredient-cap.png", "alt": "Ingredient score: 03"},
        ],
        headings=["Example Brand Daily Cream", "Ingredients from packaging:"],
    )

    payload = parse_product_snapshot(snapshot)

    assert payload["product_name"] == "Example Brand Daily Cream"
    assert payload["brand"] == "Example Brand"
    assert payload["category"] == "Facial Moisturizer/Treatment"
    assert payload["hazard_score"] == 2
    assert payload["ingredients_from_packaging"] == "WATER • CAPRYLOHYDROXAMIC ACID"
    assert payload["animal_testing_policy"] == "Unknown"
    assert payload["ingredients"][1]["name"] == "CAPRYLOHYDROXAMIC ACID"
    assert payload["ingredients"][1]["hazard_score"] == 3
    assert payload["ingredients"][1]["functions"] == ["preservative", "chelating agent"]
    assert payload["ingredients"][1]["concerns"][0] == {
        "name": "Allergies/immunotoxicity",
        "level": "moderate",
    }
    assert payload["ingredients"][1]["ingredient_url"].endswith("700000-CAPRYLOHYDROXAMIC_ACID/")


def test_parse_ingredient_snapshot_extracts_concern_references():
    snapshot = PageSnapshot(
        url="https://www.ewg.org/skindeep/ingredients/700839-BUTANE/",
        title="EWG Skin Deep® | What is BUTANE",
        h1="What is BUTANE",
        text="""
        What is BUTANE
        Data Availability
        Fair
        Allergies/immunotoxicity
        CONCERN REFERENCE
        Human skin toxicant or allergen - strong evidence Cosmetic Ingredient Review (CIR)
        Irritation (skin, eyes, or lungs)
        CONCERN REFERENCE
        Human any irritant - strong evidence Cosmetic Ingredient Review (CIR)
        Understanding scores
        """,
        links=[],
        images=[{"src": "https://example.com/score.png", "alt": "Ingredient score: 04"}],
        headings=["What is BUTANE", "Allergies/immunotoxicity", "Irritation (skin, eyes, or lungs)"],
    )

    payload = parse_ingredient_snapshot(snapshot)

    assert payload["ingredient_name"] == "BUTANE"
    assert payload["hazard_score"] == 4
    assert {"name": "Allergies/immunotoxicity", "level": None} in payload["concerns"]
    assert payload["concern_references"]["Allergies/immunotoxicity"][0]["text"].startswith(
        "Human skin toxicant"
    )


def test_link_discovery_and_challenge_detection():
    snapshot = PageSnapshot(
        url="https://www.ewg.org/skindeep/browse/category/moisturizer/",
        title="EWG Skin Deep® | Ratings for All Moisturizers",
        h1=None,
        text="Moisturizer Products",
        links=[
            {"href": "https://www.ewg.org/skindeep/browse/category/Facial_moisturizer__treatment/", "text": "Facial Moisturizer/Treatment"},
            {"href": "https://www.ewg.org/skindeep/browse/category/Facial_moisturizer__treatment/#top", "text": "Duplicate"},
            {"href": "https://www.ewg.org/skindeep/products/1-A/", "text": "A"},
            {"href": "https://www.ewg.org/skindeep/products/1-A/#section", "text": "A duplicate"},
            {"href": "https://www.ewg.org/skindeep/ingredients/700839-BUTANE/", "text": "BUTANE"},
        ],
        images=[],
        headings=[],
    )
    assert product_links_from_snapshot(snapshot) == ["https://www.ewg.org/skindeep/products/1-A/"]
    assert category_links_from_snapshot(snapshot) == [
        "https://www.ewg.org/skindeep/browse/category/Facial_moisturizer__treatment/"
    ]
    assert is_challenge_snapshot(
        PageSnapshot(
            url="https://www.ewg.org/skindeep/",
            title="Just a moment...",
            h1=None,
            text="Enable JavaScript and cookies to continue",
            links=[],
            images=[],
            headings=[],
        )
    )


def test_wayback_snapshot_and_junk_filters():
    from app.services.importers.ewg_wayback import (
        _looks_like_junk,
        is_generic_listing,
        snapshot_from_html,
    )

    html = """
    <html><head><title>EWG Skin Deep® | Example Cream</title></head>
    <body>
      <h1>Example Cream</h1>
      <img src="/web/20240101000000im_/https://www.ewg.org/score.png" alt="Product score: 03"/>
      <a href="/web/20240101id_/https://www.ewg.org/skindeep/ingredients/700000-WATER/">Water</a>
    </body></html>
    """
    snapshot = snapshot_from_html(html, "https://www.ewg.org/skindeep/products/123-Example_Cream/")
    assert snapshot.title == "EWG Skin Deep® | Example Cream"
    assert snapshot.h1 == "Example Cream"
    # Wayback prefixes are stripped from links and image sources.
    assert snapshot.images[0]["src"] == "https://www.ewg.org/score.png"
    assert snapshot.links[0]["href"] == "https://www.ewg.org/skindeep/ingredients/700000-WATER/"
    assert not is_generic_listing(snapshot)

    generic = snapshot_from_html(
        "<html><head><title>EWG Skin Deep® Cosmetics Database</title></head><body></body></html>",
        "https://www.ewg.org/skindeep/products/1-Gone/",
    )
    assert is_generic_listing(generic)

    assert _looks_like_junk("https://www.ewg.org/skindeep/products/9-X-height=440/")
    assert _looks_like_junk("https://www.ewg.org/skindeep/products/gtm.js")
    assert not _looks_like_junk("https://www.ewg.org/skindeep/products/999984-Real_Product/")


def test_parse_proxy_variants():
    assert _parse_proxy(None) is None
    assert _parse_proxy("http://u:p@1.2.3.4:8080") == {
        "server": "http://1.2.3.4:8080",
        "username": "u",
        "password": "p",
    }
    assert _parse_proxy("socks5://host:1080") == {"server": "socks5://host:1080"}


def test_scrape_to_db_pipeline_end_to_end(db_session: Session):
    """Snapshot -> parse -> import -> DB, the path every scraper engine feeds.

    Exercises the data flow without a live fetch (which is gated by the target's
    Cloudflare challenge), proving products, ingredients, links and EWG-derived
    risk rules land in the database.
    """
    snapshot = PageSnapshot(
        url="https://www.ewg.org/skindeep/products/9202226-Test_Product/",
        title="EWG Skin Deep® | Example Brand Daily Cream Rating",
        h1="Example Brand Daily Cream",
        text="""
        BRAND
        Example Brand
        CATEGORY
        Facial Moisturizer/Treatment
        DATA LAST UPDATED
        February 2026
        Data Availability: Fair
        WATER
        Data Availability: Robust
        FUNCTION(S) solvent
        CONCERNS
        CAPRYLOHYDROXAMIC ACID
        Data Availability: Limited
        FUNCTION(S) preservative, chelating agent
        CONCERNS • Allergies/immunotoxicity (moderate)
        • Use restrictions (low)
        LEARN MORE ABOUT THIS INGREDIENT
        Ingredients from packaging:
        WATER • CAPRYLOHYDROXAMIC ACID
        Product's animal testing policies
        Unknown
        Understanding scores
        """,
        links=[
            {
                "href": "https://www.ewg.org/skindeep/ingredients/700000-CAPRYLOHYDROXAMIC_ACID/",
                "text": "LEARN MORE ABOUT THIS INGREDIENT",
            }
        ],
        images=[
            {"src": "https://example.com/product.jpg", "alt": "Product score: 02"},
            {"src": "https://example.com/ingredient-water.png", "alt": "Ingredient score: 01"},
            {"src": "https://example.com/ingredient-cap.png", "alt": "Ingredient score: 03"},
        ],
        headings=["Example Brand Daily Cream"],
    )

    payload = parse_product_snapshot(snapshot)
    product = import_ewg_product_payload(db_session, payload, dry_run=False)
    db_session.commit()

    assert product is not None
    assert product.name == "Example Brand Daily Cream"

    stored = db_session.scalar(select(Product).where(Product.product_code == product.product_code))
    assert stored is not None

    ingredient_names = {
        link.ingredient.canonical_name.lower()
        for link in db_session.scalars(select(ProductIngredient)).all()
        if link.ingredient
    }
    assert any("caprylohydroxamic" in name for name in ingredient_names)
    assert db_session.scalar(select(SourceRecord).where(SourceRecord.record_type == "product")) is not None

    # The moderate allergy concern should have seeded an EWG-sourced risk rule.
    rules = db_session.scalars(
        select(RiskRule).where(RiskRule.evidence_kind == "ewg-skin-deep-concern")
    ).all()
    assert rules
    assert any("allerg" in (rule.title or "").lower() for rule in rules)
    assert db_session.scalar(select(Ingredient)) is not None
