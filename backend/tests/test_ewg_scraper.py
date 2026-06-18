from app.services.importers.ewg_public_scraper import (
    PageSnapshot,
    category_links_from_snapshot,
    is_challenge_snapshot,
    parse_ingredient_snapshot,
    parse_product_snapshot,
    product_links_from_snapshot,
)


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
