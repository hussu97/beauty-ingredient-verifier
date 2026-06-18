"""Import EWG Skin Deep data from the Internet Archive Wayback Machine.

EWG fronts ewg.org with a Cloudflare Turnstile challenge that is gated by egress
IP reputation, so direct headless scraping is unreliable. archive.org is *not*
behind Cloudflare, mirrors the full EWG Skin Deep product and ingredient pages,
and is reachable over plain HTTP with no browser. EWG Skin Deep is entirely a
cosmetics/beauty database, so every ``/skindeep/products/`` URL is a beauty
product — the CDX index hands us the whole catalogue directly, no category
crawling required.

The archived HTML is parsed into the same :class:`PageSnapshot` the browser
scraper produces, so the existing ``parse_*`` / ``import_*`` pipeline is reused
unchanged.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import httpx
from sqlalchemy.orm import Session

from app.services.importers.ewg_public_scraper import (
    INGREDIENT_PATH_RE,
    PRODUCT_PATH_RE,
    PageSnapshot,
    is_challenge_snapshot,
    parse_ingredient_snapshot,
    parse_product_snapshot,
)
from app.services.importers.ewg_skin_deep import (
    ensure_ewg_source,
    import_ewg_ingredient_payload,
    import_ewg_product_payload,
)

CDX_API = "http://web.archive.org/cdx/search/cdx"
WAYBACK_RAW = "https://web.archive.org/web/{timestamp}id_/{url}"

# Rewrites a Wayback URL prefix back to the original target URL. Handles both the
# absolute (https://web.archive.org/web/...) and relative (/web/...) forms, plus
# any capture-mode modifier (id_, im_, if_, cs_, js_, oe_, ...).
_WB_PREFIX_RE = re.compile(
    r"^(?:https?://web\.archive\.org)?/web/\d+(?:[a-z]{2}_)?/", re.IGNORECASE
)
# Junk captures to skip: thumbnail variants, assets, the bare listing root.
_JUNK_SUFFIXES = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".json")
_PRODUCT_ID_RE = re.compile(r"/skindeep/products/\d+[-/]")
_INGREDIENT_ID_RE = re.compile(r"/skindeep/ingredients/\d+[-/]")


def _deprefix(href: str | None) -> str:
    return _WB_PREFIX_RE.sub("", href or "")


def _looks_like_junk(url: str) -> bool:
    lowered = url.lower()
    if "-height=" in lowered or "-width=" in lowered:
        return True
    return any(lowered.rstrip("/").endswith(suffix) for suffix in _JUNK_SUFFIXES)


def cdx_capture_urls(
    client: httpx.Client,
    *,
    url_pattern: str,
    id_regex: re.Pattern[str],
    limit: int,
    from_date: str | None = None,
) -> list[tuple[str, str]]:
    """Return ``(original_url, timestamp)`` for archived EWG pages.

    Uses ``collapse=urlkey`` so each distinct page yields a single capture, and
    filters to successful HTML responses that look like real product/ingredient
    pages (not thumbnails, assets, or removed 404/410 records).
    """
    params = {
        "url": url_pattern,
        "output": "json",
        "fl": "original,timestamp",
        "filter": ["statuscode:200", "mimetype:text/html"],
        "collapse": "urlkey",
        "limit": str(limit),
    }
    if from_date:
        params["from"] = from_date
    response = client.get(CDX_API, params=params, timeout=120.0)
    response.raise_for_status()
    rows = response.json()
    captures: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in rows[1:] if rows and rows[0] and rows[0][0] == "original" else rows:
        if not row or len(row) < 2:
            continue
        original, timestamp = row[0], row[1]
        if _looks_like_junk(original) or not id_regex.search(original):
            continue
        # Collapse http/https + trailing-slash duplicates of the same page.
        key = re.sub(r"^https?://", "", original).rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        captures.append((original, timestamp))
    return captures


def snapshot_from_html(html: str, url: str) -> PageSnapshot:
    """Build a PageSnapshot from static archived HTML (mirrors the JS snapshot)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    h1_el = soup.find("h1")
    h1 = h1_el.get_text(" ", strip=True) if h1_el else None
    text = soup.get_text("\n")
    links = [
        {"href": urljoin(url, _deprefix(a.get("href"))), "text": a.get_text(" ", strip=True)}
        for a in soup.select("a[href]")
    ]
    images = [
        {"src": _deprefix(img.get("src")), "alt": img.get("alt") or ""}
        for img in soup.find_all("img")
    ]
    headings = [
        h.get_text(" ", strip=True) for h in soup.select("h1,h2,h3") if h.get_text(strip=True)
    ]
    return PageSnapshot(
        url=url, title=title, h1=h1, text=text, links=links, images=images, headings=headings
    )


# Titles served when EWG returned its generic landing/listing instead of a page
# (common for removed products archived as a 200 redirect to the database home).
_GENERIC_TITLES = {
    "ewg skin deep® cosmetics database",
    "ewg skin deep cosmetics database",
    "skin deep® cosmetics database",
    "wayback machine",
}


def is_generic_listing(snapshot: PageSnapshot) -> bool:
    title = (snapshot.title or "").strip().lower()
    if title in _GENERIC_TITLES:
        return True
    # A real product/ingredient page has an EWG hazard score image; the generic
    # landing page does not.
    has_score = any("score" in (img.get("alt") or "").lower() for img in snapshot.images)
    return not has_score and "|" not in (snapshot.title or "")


def fetch_snapshot(client: httpx.Client, original: str, timestamp: str) -> PageSnapshot | None:
    """Fetch a raw archived page and return its PageSnapshot, or None on failure."""
    raw_url = WAYBACK_RAW.format(timestamp=timestamp, url=original)
    try:
        response = client.get(raw_url, timeout=60.0, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if response.status_code != 200 or not response.text:
        return None
    snapshot = snapshot_from_html(response.text, original)
    # An archived page that captured a challenge or the generic listing is useless.
    if is_challenge_snapshot(snapshot) or is_generic_listing(snapshot):
        return None
    return snapshot


def _write_payloads(output_path: Path, kind: str, payloads: Iterable[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps({"kind": kind, "payload": payload}, ensure_ascii=False) + "\n")


def import_ewg_from_wayback(
    db: Session,
    *,
    max_products: int = 100,
    max_ingredients: int = 0,
    scrape_ingredients: bool = False,
    review_threshold: float = 0.82,
    dry_run: bool = False,
    output_path: Path | None = None,
    request_delay: float = 0.5,
    from_date: str | None = None,
    progress: Any | None = None,
) -> dict[str, int]:
    """Discover and import EWG Skin Deep pages from the Wayback Machine.

    Args:
        max_products: cap on product pages to fetch (the CDX index lists 200k+).
        max_ingredients: cap on standalone ingredient pages (when scrape_ingredients).
        scrape_ingredients: also import dedicated ingredient pages.
        request_delay: polite delay between archive.org requests.
        from_date: optional CDX ``from`` filter (e.g. "2023") to prefer recent data.
    """
    ensure_ewg_source(db)
    counts = {
        "product_urls": 0,
        "ingredient_urls": 0,
        "products": 0,
        "ingredients": 0,
        "skipped": 0,
        "fetch_failures": 0,
    }
    headers = {"User-Agent": "BeautyProductVerifier/0.1 (research; contact local-dev@example.com)"}
    with httpx.Client(headers=headers) as client:
        product_captures = cdx_capture_urls(
            client,
            url_pattern="ewg.org/skindeep/products/*",
            id_regex=_PRODUCT_ID_RE,
            limit=max_products * 4 if max_products else 200000,
            from_date=from_date,
        )[:max_products]
        counts["product_urls"] = len(product_captures)

        for original, timestamp in product_captures:
            snapshot = fetch_snapshot(client, original, timestamp)
            if snapshot is None:
                counts["fetch_failures"] += 1
                continue
            if not PRODUCT_PATH_RE.search(snapshot.url):
                counts["skipped"] += 1
                continue
            payload = parse_product_snapshot(snapshot)
            if output_path:
                _write_payloads(output_path, "product", [payload])
            if not dry_run:
                imported = import_ewg_product_payload(
                    db, payload, review_threshold=review_threshold, dry_run=False
                )
                counts["products" if imported is not None else "skipped"] += 1
            else:
                counts["products"] += 1
            if progress is not None:
                progress(counts)
            time.sleep(request_delay)

        if scrape_ingredients and max_ingredients > 0:
            ingredient_captures = cdx_capture_urls(
                client,
                url_pattern="ewg.org/skindeep/ingredients/*",
                id_regex=_INGREDIENT_ID_RE,
                limit=max_ingredients * 4,
                from_date=from_date,
            )[:max_ingredients]
            counts["ingredient_urls"] = len(ingredient_captures)
            for original, timestamp in ingredient_captures:
                snapshot = fetch_snapshot(client, original, timestamp)
                if snapshot is None:
                    counts["fetch_failures"] += 1
                    continue
                if not INGREDIENT_PATH_RE.search(snapshot.url):
                    counts["skipped"] += 1
                    continue
                payload = parse_ingredient_snapshot(snapshot)
                if output_path:
                    _write_payloads(output_path, "ingredient", [payload])
                if not dry_run:
                    imported = import_ewg_ingredient_payload(db, payload, dry_run=False)
                    if imported is not None:
                        counts["ingredients"] += 1
                else:
                    counts["ingredients"] += 1
                time.sleep(request_delay)

    return counts
