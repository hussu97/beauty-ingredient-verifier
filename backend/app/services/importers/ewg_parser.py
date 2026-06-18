from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from app.services.normalization import normalize_text

PRODUCT_PATH_RE = re.compile(r"/skindeep/products/[^?#]+/?")
INGREDIENT_PATH_RE = re.compile(r"/skindeep/ingredients/[^?#]+/?")
CATEGORY_PATH_RE = re.compile(r"/skindeep/browse/category/[^?#]+/?")
CHALLENGE_TEXT = ("just a moment", "enable javascript and cookies", "cf_chl", "cloudflare")

CONCERN_HEADINGS = {
    "allergies/immunotoxicity",
    "irritation (skin, eyes, or lungs)",
    "developmental/reproductive toxicity",
    "cancer",
    "use restrictions",
    "contamination concerns",
    "organ system toxicity (non-reproductive)",
    "non-reproductive organ system toxicity",
    "neurotoxicity",
    "endocrine disruption",
    "enhanced skin absorption",
    "occupational hazards",
    "persistence and bioaccumulation",
    "ecotoxicology",
    "multiple, additive exposure sources",
    "data gaps",
    "informational",
    "miscellaneous",
}


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    title: str
    h1: str | None
    text: str
    links: list[dict[str, str]]
    images: list[dict[str, str]]
    headings: list[str]
    metadata: dict[str, str] | None = None


def _clean_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _lines(text: str) -> list[str]:
    return [_clean_line(line) for line in text.splitlines() if _clean_line(line)]


def _first_after(lines: list[str], labels: tuple[str, ...]) -> str | None:
    normalized_labels = {normalize_text(label) for label in labels}
    for index, line in enumerate(lines):
        if normalize_text(line).rstrip(":") in normalized_labels:
            for next_line in lines[index + 1 :]:
                if next_line and normalize_text(next_line).rstrip(":") not in normalized_labels:
                    return next_line.strip(": ")
    return None


def _section_text(lines: list[str], start_labels: tuple[str, ...], stop_labels: tuple[str, ...]) -> str | None:
    start_norms = {normalize_text(label).rstrip(":") for label in start_labels}
    stop_norms = {normalize_text(label).rstrip(":") for label in stop_labels}
    start_index = None
    for index, line in enumerate(lines):
        if normalize_text(line).rstrip(":") in start_norms:
            start_index = index + 1
            break
    if start_index is None:
        return None
    values: list[str] = []
    for line in lines[start_index:]:
        normalized = normalize_text(line).rstrip(":")
        if normalized in stop_norms or line.startswith("## "):
            break
        values.append(line.strip(": "))
    return " ".join(values).strip() or None


def _title_product_name(snapshot: PageSnapshot) -> str | None:
    if snapshot.h1 and "skin deep" not in normalize_text(snapshot.h1):
        return snapshot.h1
    title = snapshot.title
    title = re.sub(r"^EWG Skin Deep®?\s*\|\s*", "", title).strip()
    title = re.sub(r"\s+Rating$", "", title).strip()
    return title or None


def _external_id_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.rsplit("/", 1)[-1] if path else url


def _score_from_images(images: list[dict[str, str]], *, prefix: str) -> tuple[int | None, str | None]:
    for image in images:
        alt = image.get("alt", "")
        normalized = normalize_text(alt)
        if normalize_text(prefix) not in normalized:
            continue
        match = re.search(r"(\d{1,2})", alt)
        if match:
            return int(match.group(1)), alt
        return None, alt
    return None, None


def _clean_barcode(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return digits if len(digits) in {8, 12, 13, 14} else None


def _barcode_from_snapshot(snapshot: PageSnapshot, lines: list[str]) -> str | None:
    metadata = snapshot.metadata or {}
    for key in ("gtin14", "gtin13", "gtin12", "gtin8", "gtin", "upc", "ean", "barcode"):
        barcode = _clean_barcode(metadata.get(key))
        if barcode:
            return barcode
    label_re = re.compile(
        r"\b(?:barcode|bar code|upc|ean|gtin)(?:\s*(?:code|number|no\.?))?\b",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        if not label_re.search(line):
            continue
        barcode = _clean_barcode(line)
        if barcode:
            return barcode
        if index + 1 < len(lines):
            barcode = _clean_barcode(lines[index + 1])
            if barcode:
                return barcode
    return None


# UI chrome, hazard-level labels and scoring-methodology phrases that render in
# uppercase on EWG pages and otherwise get mistaken for ingredient names.
_INGREDIENT_NAME_JUNK_RE = re.compile(
    r"^(DONATE|GET UPDATES|LEARN MORE|READ MORE|EWG VERIFIED|SEE |VIEW |SHOW |HIDE |HOW WE |WHAT IS |"
    r"(HIGH|MODERATE|LOW|NO|UNKNOWN|MODERATE-HIGH) HAZARD|"
    r"(PRODUCT|INGREDIENT) SCORE|DETERMINE SCORE|"
    r"WEIGHT[- ]OF[- ]EVIDENCE|UNDERSTANDING SCORES?|DATA (AVAILABILITY|GAP))",
    re.IGNORECASE,
)


def _is_junk_ingredient_name(name: str | None) -> bool:
    clean = (name or "").strip()
    return not clean or bool(_INGREDIENT_NAME_JUNK_RE.match(clean))


def _ingredient_sections(lines: list[str], links: list[dict[str, str]], images: list[dict[str, str]]) -> list[dict[str, Any]]:
    ingredient_links = [
        link["href"]
        for link in links
        if INGREDIENT_PATH_RE.search(link.get("href", "")) and "learn more" in normalize_text(link.get("text", ""))
    ]
    score_alts = [image.get("alt", "") for image in images if "ingredient score" in normalize_text(image.get("alt", ""))]
    rows: list[dict[str, Any]] = []
    excluded_names = {
        normalize_text(value)
        for value in (
            "brand",
            "category",
            "data last updated",
            "ingredients from packaging",
            "product's animal testing policies",
            "understanding scores",
        )
    }
    data_indexes = [
        index
        for index, line in enumerate(lines)
        if normalize_text(line).startswith("data availability")
    ]
    for position, index in enumerate(data_indexes):
        name = None
        for previous in reversed(lines[max(0, index - 4) : index]):
            normalized = normalize_text(previous)
            if (
                previous.isupper()
                and len(previous) > 2
                and normalized not in excluded_names
                and "image" not in normalized
                and "availability" not in normalized
                and not _is_junk_ingredient_name(previous)
            ):
                name = previous
                break
        if not name or _is_junk_ingredient_name(name):
            continue
        availability = lines[index].split(":", 1)[-1].strip() if ":" in lines[index] else None
        section_end = data_indexes[position + 1] if position + 1 < len(data_indexes) else len(lines)
        section = lines[index + 1 : section_end]
        functions: list[str] = []
        concerns: list[dict[str, str | None]] = []
        for section_index, section_line in enumerate(section):
            normalized = normalize_text(section_line)
            if normalized.startswith("function s") or normalized.startswith("functions"):
                value = re.sub(r"^FUNCTION\(S\)\s*", "", section_line, flags=re.IGNORECASE)
                value = re.sub(r"^FUNCTIONS?\s*", "", value, flags=re.IGNORECASE)
                functions = [item.strip() for item in value.split(",") if item.strip()]
            if normalized.startswith("concerns"):
                concern_text = " ".join(section[section_index:])
                concern_text = re.sub(r"^CONCERNS\s*", "", concern_text, flags=re.IGNORECASE)
                concern_text = concern_text.split("LEARN MORE", 1)[0]
                for raw_concern in re.split(r"•", concern_text):
                    clean = raw_concern.strip(" ;,.")
                    if not clean:
                        continue
                    level_match = re.search(r"\((low|moderate|high|critical)\)", clean, flags=re.IGNORECASE)
                    concerns.append(
                        {
                            "name": re.sub(r"\((low|moderate|high|critical)\)", "", clean, flags=re.IGNORECASE).strip(),
                            "level": level_match.group(1).lower() if level_match else None,
                        }
                    )
        row: dict[str, Any] = {
            "name": name,
            "data_availability": availability,
            "functions": functions,
            "concerns": concerns,
        }
        score_index = len(rows)
        if score_index < len(score_alts):
            row["score_image_alt"] = score_alts[score_index]
            score_match = re.search(r"(\d{1,2})", score_alts[score_index])
            if score_match:
                row["hazard_score"] = int(score_match.group(1))
        rows.append(row)
    if ingredient_links:
        offset = max(0, len(rows) - len(ingredient_links))
        for index, href in enumerate(ingredient_links):
            target_index = offset + index
            if target_index < len(rows):
                rows[target_index]["ingredient_url"] = href
    return rows


# Unwraps a Cloudflare image-resizing URL (.../cdn-cgi/image/<opts>/<real-url>).
_CDN_CGI_RE = re.compile(r"/cdn-cgi/image/[^/]+/(https?://.+)$", re.IGNORECASE)
# Non-product images to ignore (UI chrome, placeholders, social cards).
_IMAGE_EXCLUDE = ("/icon", "missing_images", "social_share", "_logo", "sprite", "placeholder")
# A complete image URL ending in a real extension. EWG eager-loads the main
# product photo with a full extension, while lazy-loaded recommended products
# carry a truncated ".../original." src — requiring an extension selects the
# genuine product image and rejects the placeholders.
_IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|webp|gif)(?:[?#].*)?$", re.IGNORECASE)


def _select_product_image_url(images: list[dict[str, str]]) -> str | None:
    """Pick the real product photo from a page's images.

    EWG serves the product photo from its content CDN (``/image/contents/<id>/``),
    often wrapped in a Cloudflare resizing URL. We unwrap that, skip score badges,
    UI icons, social-share cards, the "missing image" placeholder, and truncated
    lazy-load srcs, preferring a genuine product-content image. The returned URL
    is downloadable directly for CLIP image indexing.
    """
    for image in images:
        src = (image.get("src") or "").strip()
        if not src:
            continue
        match = _CDN_CGI_RE.search(src)
        if match:
            src = match.group(1)
        lowered = src.lower()
        if "score" in normalize_text(image.get("alt", "")):
            continue
        if any(token in lowered for token in _IMAGE_EXCLUDE) or not _IMAGE_EXT_RE.search(lowered):
            continue
        # EWG product photos always live on the content CDN; anything else
        # (promos, report banners, UI assets) is not the product image.
        if "/image/contents/" in lowered:
            return src
    return None


def parse_product_snapshot(snapshot: PageSnapshot) -> dict[str, Any]:
    lines = _lines(snapshot.text)
    hazard_score, score_alt = _score_from_images(snapshot.images, prefix="Product score")
    product_name = _title_product_name(snapshot)
    payload: dict[str, Any] = {
        "ewg_product_id": _external_id_from_url(snapshot.url),
        "source_url": snapshot.url,
        "product_url": snapshot.url,
        "product_name": product_name,
        "product_page_title": snapshot.title,
        "brand": _first_after(lines, ("Brand",)),
        "barcode": _barcode_from_snapshot(snapshot, lines),
        "category": _first_after(lines, ("Category",)),
        "data_last_updated": _first_after(lines, ("Data last updated", "Data Last Updated")),
        "hazard_score": hazard_score,
        "score_image_alt": score_alt,
        "ewg_verified": "ewg verified" in normalize_text(snapshot.text),
        "ingredients": _ingredient_sections(lines, snapshot.links, snapshot.images),
        "ingredients_from_packaging": _section_text(
            lines,
            ("Ingredients from packaging",),
            ("Product's animal testing policies", "Understanding scores", "More from"),
        ),
        "animal_testing_policy": _first_after(lines, ("Product's animal testing policies",)),
        "animal_testing_summary": _section_text(
            lines,
            ("Product's animal testing policies",),
            ("Understanding scores", "More from", "Download EWG"),
        ),
        "page_headings": snapshot.headings,
        "scraped_at": datetime.now(UTC).isoformat(),
        "scrape_status": "parsed",
    }
    product_data_availability = None
    for line in lines:
        if normalize_text(line).startswith("data availability") and ":" in line:
            product_data_availability = line.split(":", 1)[-1].strip()
            break
    if product_data_availability:
        payload["data_availability"] = product_data_availability
    image_url = _select_product_image_url(snapshot.images)
    if image_url:
        payload["image_url"] = image_url
    return payload


def parse_ingredient_snapshot(snapshot: PageSnapshot) -> dict[str, Any]:
    lines = _lines(snapshot.text)
    name = snapshot.h1 or _title_product_name(snapshot) or ""
    name = re.sub(r"^What is\s+", "", name, flags=re.IGNORECASE).strip()
    hazard_score, score_alt = _score_from_images(snapshot.images, prefix="Ingredient score")
    concerns: list[dict[str, Any]] = []
    concern_references: dict[str, list[dict[str, str]]] = {}
    for index, line in enumerate(lines):
        normalized = normalize_text(line)
        if normalized not in {normalize_text(item) for item in CONCERN_HEADINGS}:
            continue
        heading = line
        refs: list[dict[str, str]] = []
        for row in lines[index + 1 :]:
            if normalize_text(row) in {normalize_text(item) for item in CONCERN_HEADINGS}:
                break
            if row in {"CONCERN REFERENCE", "CONCERN", "REFERENCE"}:
                continue
            if len(row) > 4 and "download ewg" not in normalize_text(row):
                refs.append({"text": row})
        concerns.append({"name": heading, "level": None})
        concern_references[heading] = refs[:25]
    return {
        "ewg_id": _external_id_from_url(snapshot.url),
        "source_url": snapshot.url,
        "ingredient_url": snapshot.url,
        "ingredient_name": name,
        "hazard_score": hazard_score,
        "score_image_alt": score_alt,
        "data_availability": _first_after(lines, ("Data Availability",)),
        "concerns": concerns,
        "concern_references": concern_references,
        "page_headings": snapshot.headings,
        "scraped_at": datetime.now(UTC).isoformat(),
        "scrape_status": "parsed",
    }


def is_challenge_snapshot(snapshot: PageSnapshot) -> bool:
    haystack = normalize_text(f"{snapshot.title}\n{snapshot.text[:2000]}")
    return any(token in haystack for token in CHALLENGE_TEXT)


def product_links_from_snapshot(snapshot: PageSnapshot) -> list[str]:
    links = []
    for link in snapshot.links:
        href = link.get("href", "")
        if PRODUCT_PATH_RE.search(href):
            links.append(href.split("#", 1)[0])
    return list(dict.fromkeys(links))


def category_links_from_snapshot(snapshot: PageSnapshot) -> list[str]:
    links = []
    for link in snapshot.links:
        href = link.get("href", "")
        if CATEGORY_PATH_RE.search(href):
            links.append(href.split("#", 1)[0])
    return list(dict.fromkeys(links))


def next_links_from_snapshot(snapshot: PageSnapshot) -> list[str]:
    links = []
    for link in snapshot.links:
        text = normalize_text(link.get("text", ""))
        href = link.get("href", "")
        if href and ("next" == text or ("page" in href and PRODUCT_PATH_RE.search(href) is None)):
            links.append(href.split("#", 1)[0])
    return list(dict.fromkeys(links))
