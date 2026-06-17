from app.services.normalization import normalize_text, split_ingredients


def test_normalize_text_and_ingredient_split():
    assert normalize_text("P-Phenylenediamine / Résorcinol") == "p phenylenediamine resorcinol"
    assert split_ingredients("Aqua, Glycerin; Parfum") == ["Aqua", "Glycerin; Parfum"]
