from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from sqlalchemy.orm import Session

from app.db.init_db import init_db
from app.db.session import engine
from app.config import get_settings
from app.services.adverse_events import refresh_risk_signals
from app.services.enrichment import enrich_ingredients
from app.services.image_index import (
    image_index_status,
    index_images,
    run_resumable_image_index,
    set_image_index_paused,
)
from app.services.importers.open_beauty_facts import (
    backfill_open_beauty_facts_images,
    import_open_beauty_facts,
)
from app.services.importers.ewg_skin_deep import import_ewg_skin_deep
from app.services.importers.ewg_public_scraper import (
    DEFAULT_USER_AGENT,
    EwgScrapeBlocked,
    scrape_ewg_skin_deep,
)
from app.services.product_corrections import apply_source_backed_product_corrections

app = typer.Typer(help="Beauty Product Verifier maintenance CLI")
console = Console()


def _session() -> Session:
    init_db(get_settings())
    return Session(engine)


@app.command("import-open-beauty-facts")
def import_open_beauty_facts_command(
    source_path: Path | None = typer.Option(
        None,
        "--source-path",
        help="Local Open Beauty Facts .jsonl/.jsonl.gz/.parquet export. Omit for source-backed demo sample.",
    ),
    limit: int = typer.Option(1000, "--limit", min=1),
) -> None:
    with _session() as db:
        count = import_open_beauty_facts(db, str(source_path) if source_path else None, limit=limit)
        db.commit()
    console.print(f"Imported or updated {count} Open Beauty Facts product(s).")


@app.command("backfill-open-beauty-facts-images")
def backfill_open_beauty_facts_images_command(
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Optional number of Open Beauty Facts products to inspect.",
    ),
) -> None:
    with _session() as db:
        count = backfill_open_beauty_facts_images(db, limit=limit)
        db.commit()
    console.print(f"Added {count} Open Beauty Facts product image row(s).")


@app.command("import-ewg-skin-deep")
def import_ewg_skin_deep_command(
    source_path: Path | None = typer.Option(
        None,
        "--source-path",
        help="Authorized EWG Skin Deep .json/.jsonl/.csv/.parquet export. Defaults to BPV_EWG_SOURCE_PATH.",
    ),
    limit: int = typer.Option(1000, "--limit", min=1),
    review_threshold: float = typer.Option(
        0.82,
        "--review-threshold",
        min=0.0,
        max=1.0,
        help="Minimum confidence for merging non-barcode matches with existing products.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate/read the export without writing rows."),
) -> None:
    settings = get_settings()
    selected_path = str(source_path) if source_path else settings.ewg_source_path
    if not selected_path:
        raise typer.BadParameter("Provide --source-path or set BPV_EWG_SOURCE_PATH.")
    with _session() as db:
        counts = import_ewg_skin_deep(
            db,
            selected_path,
            limit=limit,
            review_threshold=review_threshold,
            dry_run=dry_run,
        )
        if dry_run:
            db.rollback()
        else:
            db.commit()
    console.print_json(data=counts | {"dry_run": dry_run})


@app.command("scrape-ewg-skin-deep")
def scrape_ewg_skin_deep_command(
    url: list[str] | None = typer.Option(
        None,
        "--url",
        help="EWG Skin Deep browse, product, or ingredient URL. Repeat for multiple seeds.",
    ),
    all_categories: bool = typer.Option(
        False,
        "--all-categories",
        help="Start from the Skin Deep landing page and discover all browse/category links.",
    ),
    max_products: int = typer.Option(25, "--max-products", min=1),
    max_pages: int = typer.Option(10, "--max-pages", min=1),
    max_ingredient_pages: int = typer.Option(50, "--max-ingredient-pages", min=0),
    scrape_ingredient_pages: bool = typer.Option(
        True,
        "--scrape-ingredient-pages/--no-scrape-ingredient-pages",
        help="Visit linked ingredient pages for deeper concern/reference facts.",
    ),
    user_data_dir: Path | None = typer.Option(
        None,
        "--user-data-dir",
        help="Persistent Chromium profile directory. Defaults to storage/ewg-browser-profile.",
    ),
    headed: bool = typer.Option(
        False,
        "--headed",
        help="Open a visible browser so you can clear site/browser checks manually.",
    ),
    challenge_wait_seconds: int = typer.Option(
        45,
        "--challenge-wait-seconds",
        min=0,
        help=(
            "Seconds to wait for a Cloudflare challenge to clear before giving up. "
            "Applies in both headless and --headed mode; the JS interstitial usually "
            "auto-clears in well under this once the browser fingerprint passes."
        ),
    ),
    user_agent: str | None = typer.Option(
        None,
        "--user-agent",
        help="Override the browser user agent. Defaults to a current desktop Chrome UA.",
    ),
    proxy: str | None = typer.Option(
        None,
        "--proxy",
        help=(
            "Route the browser through a proxy, e.g. http://user:pass@host:port. "
            "A clean residential IP is the most reliable way past Cloudflare once the "
            "default IP's reputation is flagged."
        ),
    ),
    delay_seconds: float = typer.Option(2.0, "--delay-seconds", min=0.5),
    browser_workers: int = typer.Option(
        1,
        "--browser-workers",
        min=1,
        max=8,
        help="Parallel browser pages for page collection. Database imports remain serial.",
    ),
    review_threshold: float = typer.Option(0.82, "--review-threshold", min=0.0, max=1.0),
    output_path: Path | None = typer.Option(
        None,
        "--output-path",
        help="Optional JSONL file to append parsed product/ingredient payloads before import.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Scrape and parse without writing to the database."),
) -> None:
    settings = get_settings()
    profile_dir = user_data_dir or settings.storage_dir / "ewg-browser-profile"
    selected_urls = list(url or [])
    if all_categories:
        selected_urls.insert(0, "https://www.ewg.org/skindeep/")
        if max_pages == 10:
            max_pages = 250
    if not selected_urls:
        raise typer.BadParameter("Provide at least one --url or use --all-categories.")
    with _session() as db:
        try:
            counts = scrape_ewg_skin_deep(
                db,
                urls=selected_urls,
                user_data_dir=profile_dir,
                max_products=max_products,
                max_pages=max_pages,
                max_ingredient_pages=max_ingredient_pages,
                scrape_ingredient_pages=scrape_ingredient_pages,
                headless=not headed,
                delay_seconds=delay_seconds,
                browser_workers=browser_workers,
                review_threshold=review_threshold,
                dry_run=dry_run,
                output_path=output_path,
                include_category_links=all_categories,
                challenge_wait_seconds=challenge_wait_seconds,
                user_agent=user_agent or DEFAULT_USER_AGENT,
                proxy_url=proxy,
            )
        except EwgScrapeBlocked as exc:
            db.rollback()
            raise typer.BadParameter(str(exc)) from exc
        if dry_run:
            db.rollback()
        else:
            db.commit()
    console.print_json(
        data=counts
        | {
            "all_categories": all_categories,
            "browser_workers": browser_workers,
            "dry_run": dry_run,
            "profile_dir": str(profile_dir),
        }
    )


@app.command("enrich-ingredients")
def enrich_ingredients_command(
    pubchem_live: bool = typer.Option(False, "--pubchem-live", help="Enable live PubChem lookups."),
    limit: int = typer.Option(25, "--limit", min=1),
) -> None:
    with _session() as db:
        count = enrich_ingredients(db, pubchem_live=pubchem_live, limit=limit)
        db.commit()
    console.print(f"Enriched {count} ingredient/risk record(s).")


@app.command("apply-product-corrections")
def apply_product_corrections_command() -> None:
    with _session() as db:
        count = apply_source_backed_product_corrections(db)
        db.commit()
    console.print(f"Applied {count} source-backed product correction(s).")


@app.command("index-images")
def index_images_command(
    limit: int = typer.Option(100, "--limit", min=1, help="Images to attempt in one batch."),
    all_pending: bool = typer.Option(
        False,
        "--all",
        help="Keep indexing pending images until complete, paused, or --max-images is reached.",
    ),
    batch_size: int = typer.Option(50, "--batch-size", min=1, help="Batch size for --all."),
    max_images: int | None = typer.Option(
        None,
        "--max-images",
        min=1,
        help="Optional cap for a resumable --all run.",
    ),
    retry_failed: bool = typer.Option(
        False,
        "--retry-failed",
        help="Retry download-failed/ml-unavailable images during --all runs.",
    ),
    download_workers: int = typer.Option(
        1,
        "--download-workers",
        min=1,
        max=12,
        help="Parallel image download workers. Embedding and DB writes remain serial.",
    ),
    status: bool = typer.Option(False, "--status", help="Print image indexing progress/status."),
    pause: bool = typer.Option(False, "--pause", help="Request a running --all job to pause."),
    resume: bool = typer.Option(False, "--resume", help="Clear the pause flag before running."),
) -> None:
    if sum(bool(flag) for flag in (status, pause, resume)) > 1:
        raise typer.BadParameter("Use only one of --status, --pause, or --resume at a time.")

    if pause:
        set_image_index_paused(True)
        console.print("Image indexing pause requested. A running job will stop after the current image.")
        return

    if resume:
        set_image_index_paused(False)
        console.print("Image indexing pause flag cleared.")
        return

    with _session() as db:
        if status:
            console.print_json(data=image_index_status(db))
            return

        settings = get_settings()
        if all_pending:
            if not settings.enable_optional_ml:
                raise typer.BadParameter(
                    "Refusing --all because BPV_ENABLE_OPTIONAL_ML is not true. "
                    "Run with ML extras enabled to avoid marking all images ml-disabled."
                )
            result = run_resumable_image_index(
                db,
                batch_size=batch_size,
                max_images=max_images,
                retry_failed=retry_failed,
                download_workers=download_workers,
            )
            console.print_json(data=result.__dict__)
            return

        count = index_images(db, limit=limit, download_workers=download_workers)
        db.commit()
    console.print(f"Indexed or marked {count} image(s).")


@app.command("refresh-risk-signals")
def refresh_risk_signals_command(
    live: bool = typer.Option(False, "--live", help="Enable live openFDA lookups."),
    limit: int = typer.Option(10, "--limit", min=1),
) -> None:
    with _session() as db:
        count = refresh_risk_signals(db, limit=limit, live=live)
        db.commit()
    console.print(f"Refreshed {count} adverse-event signal row(s).")


def main() -> None:
    app()


def _run_single_command(command_name: str) -> None:
    app(args=[command_name, *sys.argv[1:]], prog_name=Path(sys.argv[0]).name)


def import_open_beauty_facts_entry() -> None:
    _run_single_command("import-open-beauty-facts")


def backfill_open_beauty_facts_images_entry() -> None:
    _run_single_command("backfill-open-beauty-facts-images")


def enrich_ingredients_entry() -> None:
    _run_single_command("enrich-ingredients")


def apply_product_corrections_entry() -> None:
    _run_single_command("apply-product-corrections")


def import_ewg_skin_deep_entry() -> None:
    _run_single_command("import-ewg-skin-deep")


def scrape_ewg_skin_deep_entry() -> None:
    _run_single_command("scrape-ewg-skin-deep")


def index_images_entry() -> None:
    _run_single_command("index-images")


def refresh_risk_signals_entry() -> None:
    _run_single_command("refresh-risk-signals")
