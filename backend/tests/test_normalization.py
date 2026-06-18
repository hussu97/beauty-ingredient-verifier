from app.services.normalization import normalize_text, split_ewg_ingredients, split_ingredients


def test_normalize_text_and_ingredient_split():
    assert normalize_text("P-Phenylenediamine / Résorcinol") == "p phenylenediamine resorcinol"
    assert normalize_text("Бархатные ручки") == "бархатные ручки"
    assert split_ingredients("Aqua, Glycerin; Parfum") == ["Aqua", "Glycerin; Parfum"]


def test_split_ewg_ingredients_trims_page_chrome():
    text = (
        "Aqua/Water/Eau, DONATE, Glycerin, Glyceryl Arachidonate, Sodium Palmitoyl Proline Learn More, "
        "Sodium Benzoate Directions from packaging Pump a small amount onto hands. "
        "Legal Disclaimer About EWG Verified"
    )

    assert split_ewg_ingredients(text) == [
        "Aqua/Water/Eau",
        "Glycerin",
        "Glyceryl Arachidonate",
        "Sodium Palmitoyl Proline",
        "Sodium Benzoate",
    ]
