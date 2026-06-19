from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Product


def test_health_and_catalog(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ready"

    products = client.get("/api/v1/products")
    assert products.status_code == 200
    body = products.json()
    assert len(body) >= 1
    assert body[0]["product_code"].startswith("prd_")
    assert "ingredient_text" in body[0]


def test_product_and_ingredient_detail(client):
    products = client.get("/api/v1/products").json()
    product_code = products[0]["product_code"]

    detail = client.get(f"/api/v1/products/{product_code}")
    assert detail.status_code == 200
    product = detail.json()
    assert product["product_code"] == product_code
    assert product["ingredients"]
    assert "source_links" in product
    assert "normalized_attributes" in product
    assert "source_conflicts" in product
    assert "source_facts" in product
    assert "source_last_updated_at" in product

    ingredient_code = product["ingredients"][0]["ingredient"]["ingredient_code"]
    ingredient = client.get(f"/api/v1/ingredients/{ingredient_code}")
    assert ingredient.status_code == 200
    assert ingredient.json()["ingredient_code"] == ingredient_code


def test_directory_products_support_filters_facets_and_sort(client):
    products = client.post(
        "/api/v1/products/directory/products",
        json={
            "profile": {"skin_types": ["sensitive"], "sensitivities": ["fragrance"]},
            "limit": 5,
        },
    )
    assert products.status_code == 200
    page = products.json()
    assert page["limit"] == 5
    assert page["offset"] == 0
    assert page["sort"] == "risk_desc"
    assert page["total"] >= 1
    assert page["brand_facets"]
    assert page["category_facets"]
    ranked = page["items"]
    assert ranked
    assert ranked[0]["product"]["product_code"].startswith("prd_")
    assert ranked[0]["severity"] in {"unknown", "minimal", "low", "moderate", "high", "critical"}
    assert "matched_ingredient_count" in ranked[0]
    assert "source_labels" in ranked[0]
    assert "category_labels" in ranked[0]

    if page["total"] > 1:
        second_page = client.post(
            "/api/v1/products/directory/products",
            json={
                "profile": {"skin_types": ["sensitive"], "sensitivities": ["fragrance"]},
                "limit": 1,
                "offset": 1,
            },
        )
        assert second_page.status_code == 200
        second_body = second_page.json()
        assert second_body["offset"] == 1
        assert len(second_body["items"]) <= 1

    brand = page["brand_facets"][0]
    brand_filtered = client.post(
        "/api/v1/products/directory/products",
        json={
            "brand_codes": [brand["code"]],
            "profile": {"skin_types": ["sensitive"], "sensitivities": ["fragrance"]},
            "limit": 5,
        },
    )
    assert brand_filtered.status_code == 200
    brand_body = brand_filtered.json()
    assert brand_body["total"] == brand["product_count"]
    assert any(facet["code"] == brand["code"] and facet["selected"] for facet in brand_body["brand_facets"])

    category = brand_body["category_facets"][0]
    category_filtered = client.post(
        "/api/v1/products/directory/products",
        json={
            "brand_codes": [brand["code"]],
            "category_codes": [category["code"]],
            "profile": {"skin_types": ["sensitive"], "sensitivities": ["fragrance"]},
            "limit": 5,
        },
    )
    assert category_filtered.status_code == 200
    category_body = category_filtered.json()
    assert category_body["total"] == category["product_count"]
    assert any(facet["code"] == category["code"] and facet["selected"] for facet in category_body["category_facets"])

    search_term = ranked[0]["product"]["name"].split()[0]
    searched = client.post(
        "/api/v1/products/directory/products",
        json={
            "q": search_term,
            "sort": "name_asc",
            "profile": {"skin_types": ["sensitive"], "sensitivities": ["fragrance"]},
            "limit": 10,
        },
    )
    assert searched.status_code == 200
    searched_body = searched.json()
    names = [item["product"]["name"].lower() for item in searched_body["items"]]
    assert names == sorted(names)


def test_import_status_and_sources(client):
    status = client.get("/api/v1/imports/status")
    assert status.status_code == 200
    assert status.json()["sources"] >= 1
    assert status.json()["products"] >= 1

    sources = client.get("/api/v1/sources")
    assert sources.status_code == 200
    assert any(source["source_code"] == "src_open_beauty_facts" for source in sources.json())

    terms = client.get("/api/v1/sources/terms")
    assert terms.status_code == 200
    assert isinstance(terms.json(), list)

    conflicts = client.get("/api/v1/sources/conflicts")
    assert conflicts.status_code == 200
    assert isinstance(conflicts.json(), list)


def test_risk_evaluate(client, db_session: Session):
    product = db_session.scalar(select(Product).where(Product.ingredient_text.like("%LIMONENE%")))
    assert product is not None
    response = client.post(
        "/api/v1/risk/evaluate",
        json={
            "product_code": product.product_code,
            "profile": {"sensitivities": ["fragrance"], "skin_types": ["sensitive"]},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["severity"] in {"low", "moderate", "high"}
    assert body["matched_ingredients"]
    assert "not a diagnosis" in body["disclaimer"]
