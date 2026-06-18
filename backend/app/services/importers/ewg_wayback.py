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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urljoin

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Product, SourceRecord
from app.services.importers.ewg_public_scraper import (
    INGREDIENT_PATH_RE,
    PRODUCT_PATH_RE,
    PageSnapshot,
    _external_id_from_url,
    is_challenge_snapshot,
    parse_ingredient_snapshot,
    parse_product_snapshot,
)
from app.services.importers.ewg_skin_deep import (
    EWG_SOURCE_CODE,
    _upsert_product_image,
    ensure_ewg_source,
    import_ewg_ingredient_payload,
    import_ewg_product_payload,
)
from app.services.normalization import normalize_text, split_ewg_ingredients

CDX_API = "http://web.archive.org/cdx/search/cdx"
WAYBACK_RAW = "https://web.archive.org/web/{timestamp}id_/{url}"
# A far-future timestamp makes Wayback redirect to the most recent capture.
LATEST_TIMESTAMP = "29991231235959"

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

# Titles served when EWG returned its generic landing/listing instead of a page
# (common for removed products archived as a 200 redirect to the database home).
_GENERIC_TITLES = {
    "ewg skin deep® cosmetics database",
    "ewg skin deep cosmetics database",
    "skin deep® cosmetics database",
    "wayback machine",
}


def _deprefix(href: str | None) -> str:
    return _WB_PREFIX_RE.sub("", href or "")


def _looks_like_junk(url: str) -> bool:
    lowered = url.lower()
    if "-height=" in lowered or "-width=" in lowered:
        return True
    return any(lowered.rstrip("/").endswith(suffix) for suffix in _JUNK_SUFFIXES)


def iter_cdx_originals(
    client: httpx.Client,
    *,
    url_pattern: str,
    id_regex: re.Pattern[str],
    from_date: str | None = None,
    page_size: int = 20000,
) -> Iterator[str]:
    """Yield distinct archived EWG page URLs, paginating the CDX index.

    Filters to successful HTML captures (``statuscode:200``) of real
    product/ingredient pages, de-duplicating http/https + trailing-slash variants
    of the same page. Uses CDX ``resumeKey`` pagination so arbitrarily large
    result sets (200k+ products) stream in bounded chunks.
    """
    resume_key: str | None = None
    seen: set[str] = set()
    while True:
        params: dict[str, Any] = {
            "url": url_pattern,
            "output": "json",
            "fl": "original",
            "filter": ["statuscode:200", "mimetype:text/html"],
            "collapse": "urlkey",
            "limit": str(page_size),
            "showResumeKey": "true",
        }
        if from_date:
            params["from"] = from_date
        if resume_key:
            params["resumeKey"] = resume_key
        response = client.get(CDX_API, params=params, timeout=180.0)
        response.raise_for_status()
        rows = response.json() or []
        if rows and rows[0] == ["original"]:
            rows = rows[1:]

        next_key: str | None = None
        data_rows: list[list[str]] = []
        for index, row in enumerate(rows):
            if row == []:  # blank row precedes the resume key
                if index + 1 < len(rows) and rows[index + 1]:
                    next_key = rows[index + 1][0]
                break
            data_rows.append(row)

        emitted = 0
        for row in data_rows:
            if not row:
                continue
            original = row[0]
            if _looks_like_junk(original) or not id_regex.search(original):
                continue
            key = re.sub(r"^https?://", "", original).rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            emitted += 1
            yield original

        if not next_key or (emitted == 0 and not data_rows):
            break
        resume_key = next_key


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


def _fusion_normalize_product(payload: dict[str, Any]) -> dict[str, Any]:
    """Clean the ingredient list against the authoritative packaging INCI.

    The structured per-ingredient parse can pick up stray UI text on archived
    pages. The packaging INCI list is clean and uses the same vocabulary as Open
    Beauty Facts, so we keep only structured rows (which carry EWG hazard scores)
    whose name actually appears in the INCI, and otherwise fall back to the INCI
    names. This guarantees real, OBF-normalizable ingredients for source fusion.
    """
    inci = split_ewg_ingredients(payload.get("ingredients_from_packaging") or "")
    if not inci:
        return payload
    inci_norm = [normalize_text(name) for name in inci]
    inci_tokens = [set(name.split()) for name in inci_norm]

    def _matches(name: str | None) -> bool:
        target = normalize_text(name)
        if not target:
            return False
        target_tokens = set(target.split())
        for norm, tokens in zip(inci_norm, inci_tokens):
            if not norm:
                continue
            if target == norm or target in norm or norm in target:
                return True
            if target_tokens and tokens:
                overlap = len(target_tokens & tokens) / len(target_tokens | tokens)
                if overlap >= 0.5:
                    return True
        return False

    validated = [row for row in (payload.get("ingredients") or []) if _matches(row.get("name"))]
    if len(validated) >= max(3, len(inci) // 2):
        payload["ingredients"] = validated
    else:
        payload["ingredients"] = [{"name": name, "rank": i} for i, name in enumerate(inci, 1)]
    return payload


def is_generic_listing(snapshot: PageSnapshot) -> bool:
    title = (snapshot.title or "").strip().lower()
    if title in _GENERIC_TITLES:
        return True
    # A real product/ingredient page has an EWG hazard score image; the generic
    # landing page does not.
    has_score = any("score" in (img.get("alt") or "").lower() for img in snapshot.images)
    return not has_score and "|" not in (snapshot.title or "")


def fetch_latest_snapshot(client: httpx.Client, original: str) -> PageSnapshot | None:
    """Fetch the most recent archived capture of a page as a PageSnapshot."""
    raw_url = WAYBACK_RAW.format(timestamp=LATEST_TIMESTAMP, url=original)
    try:
        response = client.get(raw_url, timeout=60.0, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if response.status_code != 200 or not response.text:
        return None
    # Resolve to the actual archived URL Wayback redirected to, falling back to
    # the requested original so downstream IDs/links stay on ewg.org.
    resolved = _deprefix(str(response.url)) or original
    snapshot = snapshot_from_html(response.text, resolved)
    if is_challenge_snapshot(snapshot) or is_generic_listing(snapshot):
        return None
    return snapshot


def _existing_external_ids(db: Session, record_type: str) -> set[str]:
    rows = db.scalars(
        select(SourceRecord.external_id).where(
            SourceRecord.source_code == EWG_SOURCE_CODE,
            SourceRecord.record_type == record_type,
        )
    ).all()
    return {value for value in rows if value}


def _append_payload(output_path: Path, kind: str, payload: dict[str, Any]) -> None:
    with output_path.open("a", encoding="utf-8") as handle:
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
    skip_existing: bool = True,
    commit_every: int = 50,
    fetch_workers: int = 1,
    progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int]:
    """Discover and import EWG Skin Deep pages from the Wayback Machine.

    Args:
        max_products: cap on product pages; 0 means the entire catalogue.
        max_ingredients: cap on ingredient pages; 0 with scrape_ingredients means all.
        skip_existing: skip pages already imported (makes long runs resumable).
        commit_every: commit to the DB after this many imports so progress persists.
        request_delay: polite per-worker delay between archive.org requests.
        fetch_workers: parallel archive.org fetch threads. Fetch+parse run
            concurrently; DB imports stay serial (SQLite is single-writer).
        from_date: optional CDX ``from`` filter (e.g. "2023"); latest capture is
            always fetched regardless.
    """
    ensure_ewg_source(db)
    if not dry_run:
        db.commit()
    counts = {
        "products": 0,
        "ingredients": 0,
        "skipped_existing": 0,
        "skipped": 0,
        "fetch_failures": 0,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": "BeautyProductVerifier/0.1 (research; contact local-dev@example.com)"}

    def _run(
        *,
        url_pattern: str,
        id_regex: re.Pattern[str],
        path_re: re.Pattern[str],
        record_type: str,
        cap: int,
        kind: str,
        parse: Callable[[PageSnapshot], dict[str, Any]],
        do_import: Callable[[dict[str, Any]], bool],
    ) -> None:
        existing = _existing_external_ids(db, record_type) if skip_existing else set()
        state = {"processed_since_commit": 0, "imported": 0}
        workers = max(1, fetch_workers)

        def _ingest(snapshot: PageSnapshot | None) -> None:
            if snapshot is None:
                counts["fetch_failures"] += 1
                return
            if not path_re.search(snapshot.url):
                counts["skipped"] += 1
                return
            if cap and state["imported"] >= cap:
                return
            payload = parse(snapshot)
            if output_path:
                _append_payload(output_path, kind, payload)
            if dry_run:
                counts[f"{kind}s"] += 1
                state["imported"] += 1
            elif do_import(payload):
                counts[f"{kind}s"] += 1
                state["imported"] += 1
                state["processed_since_commit"] += 1
                if state["processed_since_commit"] >= commit_every:
                    db.commit()
                    state["processed_since_commit"] = 0
            else:
                counts["skipped"] += 1
            if progress is not None:
                progress(counts)

        with httpx.Client(headers=headers) as client:

            def _candidates() -> Iterator[str]:
                for original in iter_cdx_originals(
                    client, url_pattern=url_pattern, id_regex=id_regex, from_date=from_date
                ):
                    if skip_existing and _external_id_from_url(original) in existing:
                        counts["skipped_existing"] += 1
                        continue
                    yield original

            def _fetch(original: str) -> PageSnapshot | None:
                # Per-worker delay keeps the aggregate request rate polite.
                if request_delay:
                    time.sleep(request_delay)
                return fetch_latest_snapshot(client, original)

            source = _candidates()
            exhausted = False
            inflight: dict[Any, str] = {}

            with ThreadPoolExecutor(max_workers=workers) as pool:

                def _submit() -> None:
                    nonlocal exhausted
                    try:
                        original = next(source)
                    except StopIteration:
                        exhausted = True
                        return
                    inflight[pool.submit(_fetch, original)] = original

                window = workers * 3
                while True:
                    while (
                        not exhausted
                        and len(inflight) < window
                        and not (cap and state["imported"] >= cap)
                    ):
                        _submit()
                    if not inflight:
                        break
                    done, _ = wait(inflight, return_when=FIRST_COMPLETED)
                    for future in done:
                        inflight.pop(future, None)
                        try:
                            snapshot = future.result()
                        except Exception:
                            counts["fetch_failures"] += 1
                            continue
                        # DB import happens here, in the main thread, serially.
                        _ingest(snapshot)
        if not dry_run:
            db.commit()

    _run(
        url_pattern="ewg.org/skindeep/products/*",
        id_regex=_PRODUCT_ID_RE,
        path_re=PRODUCT_PATH_RE,
        record_type="product",
        cap=max_products,
        kind="product",
        parse=lambda snapshot: _fusion_normalize_product(parse_product_snapshot(snapshot)),
        do_import=lambda payload: import_ewg_product_payload(
            db, payload, review_threshold=review_threshold, dry_run=False
        )
        is not None,
    )

    if scrape_ingredients:
        _run(
            url_pattern="ewg.org/skindeep/ingredients/*",
            id_regex=_INGREDIENT_ID_RE,
            path_re=INGREDIENT_PATH_RE,
            record_type="ingredient",
            cap=max_ingredients,
            kind="ingredient",
            parse=parse_ingredient_snapshot,
            do_import=lambda payload: import_ewg_ingredient_payload(db, payload, dry_run=False)
            is not None,
        )

    return counts


def backfill_wayback_images(
    db: Session,
    *,
    max_items: int = 0,
    fetch_workers: int = 8,
    request_delay: float = 0.2,
    commit_every: int = 100,
    progress: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int]:
    """Add product images to already-imported EWG products that have none.

    Re-fetches each product's latest archived page, extracts the real product
    photo, and creates a front ProductImage row (pending CLIP embedding). Use
    after an import that predates image support; safe to re-run (idempotent).
    """
    ensure_ewg_source(db)
    counts = {"checked": 0, "images_added": 0, "no_image": 0, "fetch_failures": 0}
    rows = db.execute(
        select(Product.product_code, SourceRecord.source_url)
        .join(SourceRecord, Product.source_record_code == SourceRecord.source_record_code)
        .where(
            SourceRecord.source_code == EWG_SOURCE_CODE,
            SourceRecord.record_type == "product",
            ~Product.images.any(),
        )
    ).all()
    targets = [(code, url) for code, url in rows if url]
    if max_items:
        targets = targets[:max_items]

    headers = {"User-Agent": "BeautyProductVerifier/0.1 (research; contact local-dev@example.com)"}
    processed_since_commit = 0
    with httpx.Client(headers=headers) as client:

        def _fetch(item: tuple[str, str]) -> tuple[str, PageSnapshot | None]:
            if request_delay:
                time.sleep(request_delay)
            return item[0], fetch_latest_snapshot(client, item[1])

        source = iter(targets)
        exhausted = False
        inflight: dict[Any, tuple[str, str]] = {}
        with ThreadPoolExecutor(max_workers=max(1, fetch_workers)) as pool:

            def _submit() -> None:
                nonlocal exhausted
                try:
                    item = next(source)
                except StopIteration:
                    exhausted = True
                    return
                inflight[pool.submit(_fetch, item)] = item

            window = max(1, fetch_workers) * 3
            while True:
                while not exhausted and len(inflight) < window:
                    _submit()
                if not inflight:
                    break
                done, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for future in done:
                    inflight.pop(future, None)
                    counts["checked"] += 1
                    try:
                        product_code, snapshot = future.result()
                    except Exception:
                        counts["fetch_failures"] += 1
                        continue
                    if snapshot is None:
                        counts["fetch_failures"] += 1
                        continue
                    image_url = parse_product_snapshot(snapshot).get("image_url")
                    if not image_url:
                        counts["no_image"] += 1
                        continue
                    product = db.get(Product, product_code)
                    if product is None:
                        continue
                    _upsert_product_image(
                        db,
                        product=product,
                        url=str(image_url),
                        source_record_code=product.source_record_code or "",
                    )
                    counts["images_added"] += 1
                    processed_since_commit += 1
                    if processed_since_commit >= commit_every:
                        db.commit()
                        processed_since_commit = 0
                    if progress is not None:
                        progress(counts)
        db.commit()
    return counts
