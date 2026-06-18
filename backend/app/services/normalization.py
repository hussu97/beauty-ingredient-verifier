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
    stop_patterns = (
        r"\bDirections from packaging\b",
        r"\bWarnings from packaging\b",
        r"\bProduct's animal testing policies\b",
        r"\bUnderstanding scores\b",
        r"\bLegal Disclaimer\b",
        r"\bAbout EWG Verified\b",
        r"\bDownload EWG\b",
    )
    stop_indexes = [
        match.start()
        for pattern in stop_patterns
        if (match := re.search(pattern, text, flags=re.IGNORECASE))
    ]
    if stop_indexes:
        text = text[: min(stop_indexes)]
    text = re.sub(r"\s+[;/]\s+", ", ", text)
    parts = []
    junk_re = re.compile(
        r"(learn more|legal disclaimer|download ewg|healthy living app|get updates|"
        r"ratings? below indicate|choking hazard|\bdonate\b)",
        re.IGNORECASE,
    )
    for part in text.split(","):
        clean = re.sub(r"\*+", " ", part).strip(" .;:_")
        clean = re.sub(r"\b(?:to\s+)?learn more\b.*$", "", clean, flags=re.IGNORECASE).strip(" .;:_")
        if len(clean) > 1 and not junk_re.search(clean):
            parts.append(clean)
    return parts


def normalize_profile_list(values: list[str] | None) -> set[str]:
    return {normalize_text(value) for value in values or [] if normalize_text(value)}
