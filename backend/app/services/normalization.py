from __future__ import annotations

import re
import unicodedata


TOKEN_RE = re.compile(r"[^\w]+", flags=re.UNICODE)
COMBINING_MARK_RE = re.compile(r"[\u0300-\u036f]+")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = COMBINING_MARK_RE.sub("", decomposed)
    normalized = unicodedata.normalize("NFKC", without_marks).lower().replace("_", " ")
    return TOKEN_RE.sub(" ", normalized).strip()


def slugify(value: str) -> str:
    return normalize_text(value).replace(" ", "-") or "unknown"


def canonical_ingredient_name(raw: str) -> str:
    clean = raw.strip().strip(".;:")
    clean = re.sub(r"\s+", " ", clean)
    return clean.upper() if clean.isupper() else clean.title()


def split_ingredients(ingredient_text: str | None) -> list[str]:
    if not ingredient_text:
        return []
    text = ingredient_text.replace("\n", ",")
    parts = [part.strip(" .;:") for part in text.split(",")]
    return [part for part in parts if len(part) > 1]


def split_ewg_ingredients(ingredient_text: str | None) -> list[str]:
    if not ingredient_text:
        return []
    text = ingredient_text.replace("\n", ",")
    text = re.sub(r"\s+[;/]\s+", ", ", text)
    parts = [part.strip(" .;:") for part in text.split(",")]
    return [part for part in parts if len(part) > 1]


def normalize_profile_list(values: list[str] | None) -> set[str]:
    return {normalize_text(value) for value in values or [] if normalize_text(value)}
