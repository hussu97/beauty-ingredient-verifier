from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from sqlalchemy.orm import Session

from app.services.importers.ewg_skin_deep import (
    import_ewg_ingredient_payload,
    import_ewg_product_payload,
)
from app.services.normalization import normalize_text

EWG_BASE_URL = "https://www.ewg.org"
PRODUCT_PATH_RE = re.compile(r"/skindeep/products/[^?#]+/?")
INGREDIENT_PATH_RE = re.compile(r"/skindeep/ingredients/[^?#]+/?")
CATEGORY_PATH_RE = re.compile(r"/skindeep/browse/category/[^?#]+/?")
CHALLENGE_TEXT = ("just a moment", "enable javascript and cookies", "cf_chl", "cloudflare")

# A realistic, current desktop Chrome user agent. The default headless Chromium
# UA contains "HeadlessChrome", which Cloudflare blocks on sight.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_LOCALE = "en-US"
DEFAULT_TIMEZONE = "America/New_York"

# Launch switches that strip the most obvious automation fingerprints.
STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process,Translate",
    "--disable-dom-distiller",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
    "--start-maximized",
]
# Switches Playwright normally injects that leak automation; drop them.
STEALTH_IGNORE_DEFAULT_ARGS = ["--enable-automation"]

# Injected before any page script runs to mask the remaining bot signals
# (navigator.webdriver, empty plugin/language lists, missing window.chrome,
# and the headless WebGL vendor strings).
STEALTH_INIT_SCRIPT = """
(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
  Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5].map((i) => ({ name: `Plugin ${i}` })),
  });
  window.chrome = window.chrome || { runtime: {}, app: {}, csi: () => {}, loadTimes: () => {} };
  const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
  if (originalQuery) {
    window.navigator.permissions.query = (parameters) =>
      parameters && parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);
  }
  try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (parameter) {
      if (parameter === 37445) return 'Intel Inc.';
      if (parameter === 37446) return 'Intel Iris OpenGL Engine';
      return getParameter.call(this, parameter);
    };
  } catch (err) { /* WebGL not available */ }
})();
"""
SNAPSHOT_SCRIPT = """() => ({
    url: location.href,
    title: document.title || "",
    h1: document.querySelector("h1")?.innerText?.trim() || null,
    text: document.body?.innerText || "",
    links: Array.from(document.querySelectorAll("a[href]")).map((a) => ({
        href: new URL(a.getAttribute("href"), location.href).href,
        text: (a.innerText || a.getAttribute("aria-label") || "").trim()
    })),
    images: Array.from(document.querySelectorAll("img")).map((img) => ({
        src: img.currentSrc || img.src || "",
        alt: img.alt || ""
    })),
    headings: Array.from(document.querySelectorAll("h1,h2,h3")).map((h) => h.innerText.trim()).filter(Boolean)
})"""
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


class EwgScrapeBlocked(RuntimeError):
    pass


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
            ):
                name = previous
                break
        if not name:
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
    image = next((image for image in snapshot.images if image.get("src") and "score" not in normalize_text(image.get("alt", ""))), None)
    if image:
        payload["image_url"] = image["src"]
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


def _snapshot_from_page(page) -> PageSnapshot:
    data = page.evaluate(SNAPSHOT_SCRIPT)
    return PageSnapshot(**data)


async def _snapshot_from_async_page(page) -> PageSnapshot:
    data = await page.evaluate(SNAPSHOT_SCRIPT)
    return PageSnapshot(**data)


async def _humanize_page(page, *, viewport_height: int = 900) -> None:
    """Perform small, randomized human-like gestures to look less robotic.

    Cloudflare's interstitial scores interaction signals (mouse movement,
    scrolling, dwell time). These gestures also trigger lazy-loaded images and
    ingredient blocks, which improves extraction accuracy.
    """
    try:
        for _ in range(random.randint(2, 4)):
            await page.mouse.move(
                random.randint(20, 1200),
                random.randint(20, viewport_height - 50),
                steps=random.randint(5, 18),
            )
            await page.wait_for_timeout(random.randint(120, 380))
        # Scroll down in a few steps, then part-way back up, to load lazy content.
        for fraction in (0.25, 0.55, 0.85, 1.0, 0.5):
            await page.evaluate(
                "(f) => window.scrollTo({ top: document.body.scrollHeight * f, behavior: 'smooth' })",
                fraction,
            )
            await page.wait_for_timeout(random.randint(250, 600))
    except Exception:
        # Best-effort only; never let a gesture failure abort a scrape.
        pass


async def _attempt_turnstile_click(page) -> bool:
    """Best-effort click of a Cloudflare Turnstile checkbox.

    EWG fronts Skin Deep with a Turnstile managed challenge. When it renders an
    interactive checkbox, moving the mouse to it and clicking can clear the
    challenge. Returns True if a click was issued. This does NOT defeat the
    environment-scored variant on its own; it is one human-like signal among the
    stealth/profile measures.
    """
    frame = next(
        (f for f in page.frames if "challenges.cloudflare.com" in (f.url or "")),
        None,
    )
    if frame is None:
        return False
    # Preferred: click the real checkbox element inside the Turnstile frame. This
    # is far more reliable than guessing coordinates and adapts to layout shifts.
    for selector in ("input[type=checkbox]", "label"):
        try:
            locator = frame.locator(selector)
            if await locator.count():
                await locator.first.click(timeout=5000)
                return True
        except Exception:
            continue
    # Fallback: move the mouse to the checkbox region and click by coordinates.
    try:
        owner = await frame.frame_element()
        box = await owner.bounding_box()
        if not box:
            return False
        x = box["x"] + 30
        y = box["y"] + 30  # checkbox sits ~30px from the frame's top-left
        await page.mouse.move(x - random.randint(30, 60), y - random.randint(5, 15), steps=10)
        await page.mouse.move(x, y, steps=random.randint(8, 14))
        await page.wait_for_timeout(random.randint(200, 450))
        await page.mouse.click(x, y, delay=random.randint(60, 130))
        return True
    except Exception:
        return False


async def _settle_page(page) -> None:
    """Wait for the page to reach a stable, fully-rendered state."""
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        # networkidle can time out on chatty pages; the content is usually ready.
        pass


def _ensure_async_playwright() -> tuple[Any, str]:
    """Return ``(async_playwright, engine_name)``, preferring patchright.

    Patchright is a drop-in Playwright fork that patches the CDP ``Runtime.enable``
    leak Cloudflare Turnstile keys off of, so it clears EWG's challenge where
    vanilla Playwright cannot. We fall back to stock Playwright if it is absent.
    """
    try:
        from patchright.async_api import async_playwright

        return async_playwright, "patchright"
    except ImportError:
        pass
    try:
        from playwright.async_api import async_playwright

        return async_playwright, "playwright"
    except ImportError as exc:
        raise RuntimeError(
            "A browser engine is required for scraping. Install backend[data] and run "
            "`patchright install chromium` (preferred) or `python -m playwright install chromium`."
        ) from exc


def _parse_proxy(proxy_url: str | None) -> dict[str, str] | None:
    """Turn a ``scheme://user:pass@host:port`` URL into Playwright proxy kwargs.

    A clean (e.g. residential) egress IP is the most reliable way past a Cloudflare
    Turnstile challenge once the default IP's reputation has been flagged.
    """
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    if not parsed.hostname:
        raise ValueError(f"Invalid proxy URL: {proxy_url!r}")
    scheme = parsed.scheme or "http"
    server = f"{scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    proxy: dict[str, str] = {"server": server}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


def _empty_counts() -> dict[str, int]:
    return {
        "pages_seen": 0,
        "category_pages": 0,
        "product_pages": 0,
        "ingredient_pages": 0,
        "products": 0,
        "ingredients": 0,
        "skipped": 0,
        "challenge_pages": 0,
    }


async def _collect_ewg_payloads(
    *,
    urls: list[str],
    user_data_dir: Path,
    max_products: int,
    max_pages: int,
    max_ingredient_pages: int,
    scrape_ingredient_pages: bool,
    headless: bool,
    delay_seconds: float,
    browser_workers: int,
    include_category_links: bool,
    challenge_wait_seconds: int,
    user_agent: str = DEFAULT_USER_AGENT,
    locale: str = DEFAULT_LOCALE,
    timezone_id: str = DEFAULT_TIMEZONE,
    proxy_url: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    async_playwright, engine = _ensure_async_playwright()
    proxy = _parse_proxy(proxy_url)
    workers = max(1, min(browser_workers, 8))
    counts = _empty_counts()
    lock = asyncio.Lock()
    product_payloads: list[dict[str, Any]] = []
    ingredient_payloads: list[dict[str, Any]] = []
    product_urls: list[str] = []
    seen_product_urls: set[str] = set()
    ingredient_urls: list[str] = []
    seen_ingredient_urls: set[str] = set()
    blocked_message: str | None = None

    user_data_dir.mkdir(parents=True, exist_ok=True)
    viewport_height = 900

    if engine == "patchright":
        # Patchright patches automation leaks at the protocol level. Its docs are
        # explicit that adding the usual stealth args, a spoofed user agent, or JS
        # init scripts REDUCES stealth, so we pass a minimal config and let it use a
        # real Chrome profile. channel="chrome" is preferred; fall back to chromium.
        launch_kwargs: dict[str, Any] = dict(
            headless=headless,
            no_viewport=True,
            locale=locale,
            timezone_id=timezone_id,
        )
        channels_to_try = ["chrome", "chromium", None]
    else:
        launch_kwargs = dict(
            headless=headless,
            args=STEALTH_LAUNCH_ARGS,
            ignore_default_args=STEALTH_IGNORE_DEFAULT_ARGS,
            user_agent=user_agent,
            locale=locale,
            timezone_id=timezone_id,
            viewport={"width": 1365, "height": viewport_height},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "Sec-Ch-Ua": '"Chromium";v="126", "Google Chrome";v="126", "Not.A/Brand";v="24"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"macOS"',
                "Upgrade-Insecure-Requests": "1",
            },
        )
        # The full Chromium build's "new" headless mode is far less detectable than
        # the default headless_shell. Prefer channel="chromium", then the bundled build.
        channels_to_try = ["chromium", None]

    if proxy:
        launch_kwargs["proxy"] = proxy

    async with async_playwright() as playwright:
        context = None
        last_error: Exception | None = None
        for channel in channels_to_try:
            kwargs = dict(launch_kwargs)
            if channel is not None:
                kwargs["channel"] = channel
            try:
                context = await playwright.chromium.launch_persistent_context(
                    str(user_data_dir), **kwargs
                )
                break
            except Exception as exc:  # channel not installed → try the next
                last_error = exc
        if context is None:
            raise RuntimeError(
                f"Could not launch a browser with engine '{engine}'. Install a browser "
                "with `patchright install chrome` or `playwright install chromium`."
            ) from last_error
        # Only the vanilla-Playwright path needs the manual JS stealth shim;
        # patchright handles this at a lower level and JS overrides hurt it.
        if engine != "patchright":
            await context.add_init_script(STEALTH_INIT_SCRIPT)

        async def _post_challenge_snapshot(page) -> PageSnapshot:
            # Only scroll/move once we're past the challenge: gestures during the
            # Turnstile evaluation disrupt its auto-pass, but afterwards they load
            # lazy images and ingredient blocks for more accurate extraction.
            await _settle_page(page)
            await _humanize_page(page, viewport_height=viewport_height)
            return await _snapshot_from_async_page(page)

        async def visit(page, url: str) -> PageSnapshot:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(random.randint(2000, 3200))
            snapshot = await _snapshot_from_async_page(page)
            if not is_challenge_snapshot(snapshot):
                return await _post_challenge_snapshot(page)

            # Cloudflare's Turnstile challenge auto-clears within a few seconds once
            # the browser fingerprint passes (patchright + a real Chrome profile).
            # While it is evaluating we stay still — no scrolling — and only nudge the
            # checkbox if one is rendered. Poll in both headless and headed modes.
            if challenge_wait_seconds > 0:
                deadline = asyncio.get_running_loop().time() + challenge_wait_seconds
                while asyncio.get_running_loop().time() < deadline:
                    try:
                        await _attempt_turnstile_click(page)
                        await page.wait_for_timeout(random.randint(2500, 4000))
                        snapshot = await _snapshot_from_async_page(page)
                    except Exception as exc:
                        raise EwgScrapeBlocked(
                            "The browser was closed before the EWG challenge cleared. "
                            "Re-run and leave the browser open until the command finishes."
                        ) from exc
                    if not is_challenge_snapshot(snapshot):
                        return await _post_challenge_snapshot(page)
            async with lock:
                counts["challenge_pages"] += 1
            raise EwgScrapeBlocked(
                "EWG returned a browser challenge page that did not clear within "
                f"{challenge_wait_seconds}s. Increase --challenge-wait-seconds, reduce "
                "--browser-workers to 1, or re-run with --headed and the same --user-data-dir "
                "to clear it manually once (the persisted profile is reused afterwards)."
            )

        async def collect_listing_pages() -> None:
            nonlocal blocked_message
            page_queue: asyncio.Queue[str | None] = asyncio.Queue()
            scheduled_pages: set[str] = set()
            for raw_url in urls:
                if len(scheduled_pages) >= max_pages:
                    break
                url = urljoin(EWG_BASE_URL, raw_url)
                if url not in scheduled_pages:
                    scheduled_pages.add(url)
                    await page_queue.put(url)

            async def schedule_pages(candidates: list[str]) -> None:
                async with lock:
                    for candidate in candidates:
                        url = urljoin(EWG_BASE_URL, candidate)
                        if len(scheduled_pages) >= max_pages:
                            break
                        if url in scheduled_pages:
                            continue
                        scheduled_pages.add(url)
                        await page_queue.put(url)

            async def worker() -> None:
                nonlocal blocked_message
                page = await context.new_page()
                try:
                    while True:
                        url = await page_queue.get()
                        try:
                            if url is None:
                                return
                            if blocked_message:
                                continue
                            snapshot = await visit(page, url)
                            async with lock:
                                counts["pages_seen"] += 1
                                if CATEGORY_PATH_RE.search(url):
                                    counts["category_pages"] += 1
                                for product_url in product_links_from_snapshot(snapshot):
                                    if len(product_urls) >= max_products:
                                        break
                                    if product_url not in seen_product_urls:
                                        seen_product_urls.add(product_url)
                                        product_urls.append(product_url)
                            page_candidates = next_links_from_snapshot(snapshot)
                            if include_category_links:
                                page_candidates.extend(category_links_from_snapshot(snapshot))
                            await schedule_pages(page_candidates)
                            await asyncio.sleep(delay_seconds * random.uniform(0.7, 1.6))
                        except EwgScrapeBlocked as exc:
                            blocked_message = str(exc)
                        finally:
                            page_queue.task_done()
                finally:
                    await page.close()

            tasks = [asyncio.create_task(worker()) for _ in range(workers)]
            await page_queue.join()
            for _ in tasks:
                await page_queue.put(None)
            await asyncio.gather(*tasks)
            if blocked_message:
                raise EwgScrapeBlocked(blocked_message)

        async def collect_product_pages() -> None:
            nonlocal blocked_message
            product_queue: asyncio.Queue[str | None] = asyncio.Queue()
            for url in product_urls[:max_products]:
                await product_queue.put(url)

            async def worker() -> None:
                nonlocal blocked_message
                page = await context.new_page()
                try:
                    while True:
                        url = await product_queue.get()
                        try:
                            if url is None:
                                return
                            if blocked_message:
                                continue
                            snapshot = await visit(page, url)
                            payload = parse_product_snapshot(snapshot)
                            # If the key fields didn't render, give the page one more
                            # settle + scroll pass and re-parse before accepting it.
                            if not payload.get("product_name") or payload.get("hazard_score") is None:
                                await _settle_page(page)
                                await _humanize_page(page, viewport_height=viewport_height)
                                await page.wait_for_timeout(random.randint(800, 1500))
                                retry_snapshot = await _snapshot_from_async_page(page)
                                retry_payload = parse_product_snapshot(retry_snapshot)
                                if retry_payload.get("product_name"):
                                    payload = retry_payload
                            async with lock:
                                product_payloads.append(payload)
                                counts["product_pages"] += 1
                                for row in payload.get("ingredients", []):
                                    ingredient_url = row.get("ingredient_url")
                                    if (
                                        ingredient_url
                                        and ingredient_url not in seen_ingredient_urls
                                        and len(ingredient_urls) < max_ingredient_pages
                                    ):
                                        seen_ingredient_urls.add(ingredient_url)
                                        ingredient_urls.append(ingredient_url)
                            await asyncio.sleep(delay_seconds * random.uniform(0.7, 1.6))
                        except EwgScrapeBlocked as exc:
                            blocked_message = str(exc)
                        finally:
                            product_queue.task_done()
                finally:
                    await page.close()

            tasks = [asyncio.create_task(worker()) for _ in range(workers)]
            await product_queue.join()
            for _ in tasks:
                await product_queue.put(None)
            await asyncio.gather(*tasks)
            if blocked_message:
                raise EwgScrapeBlocked(blocked_message)

        async def collect_ingredient_pages() -> None:
            nonlocal blocked_message
            if not scrape_ingredient_pages or max_ingredient_pages <= 0:
                return
            ingredient_queue: asyncio.Queue[str | None] = asyncio.Queue()
            for url in ingredient_urls[:max_ingredient_pages]:
                await ingredient_queue.put(url)

            async def worker() -> None:
                nonlocal blocked_message
                page = await context.new_page()
                try:
                    while True:
                        url = await ingredient_queue.get()
                        try:
                            if url is None:
                                return
                            if blocked_message:
                                continue
                            snapshot = await visit(page, url)
                            payload = parse_ingredient_snapshot(snapshot)
                            async with lock:
                                ingredient_payloads.append(payload)
                                counts["ingredient_pages"] += 1
                            await asyncio.sleep(delay_seconds * random.uniform(0.7, 1.6))
                        except EwgScrapeBlocked as exc:
                            blocked_message = str(exc)
                        finally:
                            ingredient_queue.task_done()
                finally:
                    await page.close()

            tasks = [asyncio.create_task(worker()) for _ in range(workers)]
            await ingredient_queue.join()
            for _ in tasks:
                await ingredient_queue.put(None)
            await asyncio.gather(*tasks)
            if blocked_message:
                raise EwgScrapeBlocked(blocked_message)

        try:
            await collect_listing_pages()
            await collect_product_pages()
            await collect_ingredient_pages()
        finally:
            await context.close()

    return product_payloads, ingredient_payloads, counts


def scrape_ewg_skin_deep(
    db: Session,
    *,
    urls: list[str],
    user_data_dir: Path,
    max_products: int = 25,
    max_pages: int = 10,
    max_ingredient_pages: int = 50,
    scrape_ingredient_pages: bool = True,
    headless: bool = True,
    delay_seconds: float = 2.0,
    review_threshold: float = 0.82,
    dry_run: bool = False,
    output_path: Path | None = None,
    browser_workers: int = 1,
    include_category_links: bool = False,
    challenge_wait_seconds: int = 0,
    user_agent: str = DEFAULT_USER_AGENT,
    locale: str = DEFAULT_LOCALE,
    timezone_id: str = DEFAULT_TIMEZONE,
    proxy_url: str | None = None,
) -> dict[str, int]:
    product_payloads, ingredient_payloads, counts = asyncio.run(
        _collect_ewg_payloads(
            urls=urls,
            user_data_dir=user_data_dir,
            max_products=max_products,
            max_pages=max_pages,
            max_ingredient_pages=max_ingredient_pages,
            scrape_ingredient_pages=scrape_ingredient_pages,
            headless=headless,
            delay_seconds=delay_seconds,
            browser_workers=browser_workers,
            include_category_links=include_category_links,
            challenge_wait_seconds=challenge_wait_seconds,
            user_agent=user_agent,
            locale=locale,
            timezone_id=timezone_id,
            proxy_url=proxy_url,
        )
    )
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as output_handle:
            for payload in product_payloads:
                output_handle.write(json.dumps({"kind": "product", "payload": payload}, ensure_ascii=False) + "\n")
            for payload in ingredient_payloads:
                output_handle.write(json.dumps({"kind": "ingredient", "payload": payload}, ensure_ascii=False) + "\n")

    if dry_run:
        counts["products"] = len(product_payloads)
        counts["ingredients"] = len(ingredient_payloads)
        return counts

    counts["products"] = 0
    counts["ingredients"] = 0
    for payload in product_payloads:
        imported = import_ewg_product_payload(
            db,
            payload,
            review_threshold=review_threshold,
            dry_run=False,
        )
        counts["products" if imported is not None else "skipped"] += 1
    for payload in ingredient_payloads:
        imported_ingredient = import_ewg_ingredient_payload(
            db,
            payload,
            dry_run=False,
        )
        if imported_ingredient is not None:
            counts["ingredients"] += 1
    return counts
