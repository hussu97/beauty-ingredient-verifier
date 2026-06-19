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
from app.services.importers.ewg_wayback import backfill_wayback_images, import_ewg_from_wayback
from app.services.product_corrections import apply_source_backed_product_corrections
from app.services.data_sync import run_prod_migrations, sync_local_to_prod

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


@app.command("import-ewg-wayback")
def import_ewg_wayback_command(
    max_products: int = typer.Option(100, "--max-products", min=0),
    max_ingredients: int = typer.Option(0, "--max-ingredients", min=0),
    scrape_ingredients: bool = typer.Option(
        False,
        "--scrape-ingredients/--no-scrape-ingredients",
        help="Also import standalone EWG ingredient pages from the archive.",
    ),
    from_date: str | None = typer.Option(
        None,
        "--from-date",
        help="Optional CDX 'from' filter (e.g. 2023) to prefer recent captures.",
    ),
    request_delay: float = typer.Option(0.5, "--request-delay", min=0.0),
    fetch_workers: int = typer.Option(
        1,
        "--fetch-workers",
        min=1,
        max=32,
        help="Parallel archive.org fetch threads. Fetch+parse run concurrently; "
        "DB imports stay serial. Try 8. Lower it if fetch_failures spike (429s).",
    ),
    review_threshold: float = typer.Option(0.82, "--review-threshold", min=0.0, max=1.0),
    output_path: Path | None = typer.Option(
        None,
        "--output-path",
        help="Optional JSONL file to append parsed payloads before import.",
    ),
    progress_every: int = typer.Option(
        100,
        "--progress-every",
        min=0,
        help="Print a progress line every N processed pages (0 to disable).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse without writing to the database."),
) -> None:
    """Import EWG Skin Deep from the Wayback Machine (no Cloudflare, no browser).

    EWG Skin Deep is entirely a cosmetics/beauty database, so this imports beauty
    products directly from archive.org's mirror of every product page. Use
    --max-products 0 (and --max-ingredients 0 with --scrape-ingredients) for the
    full catalogue; the run is resumable and fetches the exact CDX capture
    timestamp for each discovered page.
    """
    from datetime import datetime

    def _progress(counts: dict[str, int]) -> None:
        if not progress_every:
            return
        total = (
            counts["products"]
            + counts["ingredients"]
            + counts["skipped"]
            + counts["fetch_failures"]
        )
        if total and total % progress_every == 0:
            stamp = datetime.now().strftime("%H:%M:%S")
            console.print(
                f"[{stamp}] products={counts['products']} ingredients={counts['ingredients']} "
                f"skipped_existing={counts['skipped_existing']} skipped={counts['skipped']} "
                f"fetch_failures={counts['fetch_failures']} "
                f"generic={counts.get('fetch_generic', 0)} http={counts.get('fetch_http_errors', 0)}"
            )

    with _session() as db:
        counts = import_ewg_from_wayback(
            db,
            max_products=max_products,
            max_ingredients=max_ingredients,
            scrape_ingredients=scrape_ingredients,
            review_threshold=review_threshold,
            dry_run=dry_run,
            output_path=output_path,
            request_delay=request_delay,
            from_date=from_date,
            fetch_workers=fetch_workers,
            progress=_progress,
        )
        if dry_run:
            db.rollback()
        else:
            db.commit()
    console.print_json(data=counts | {"dry_run": dry_run})


@app.command("backfill-ewg-wayback-images")
def backfill_ewg_wayback_images_command(
    max_items: int = typer.Option(0, "--max-items", min=0, help="Cap items; 0 = all missing."),
    fetch_workers: int = typer.Option(8, "--fetch-workers", min=1, max=32),
    request_delay: float = typer.Option(0.2, "--request-delay", min=0.0),
    progress_every: int = typer.Option(100, "--progress-every", min=0),
) -> None:
    """Add product images to EWG products imported before image support existed.

    Re-fetches each archived page, extracts the product photo, and creates a
    pending ProductImage row for CLIP indexing. Idempotent and resumable.
    """
    from datetime import datetime

    def _progress(counts: dict[str, int]) -> None:
        if progress_every and counts["checked"] % progress_every == 0:
            stamp = datetime.now().strftime("%H:%M:%S")
            console.print(
                f"[{stamp}] checked={counts['checked']} images_added={counts['images_added']} "
                f"no_image={counts['no_image']} fetch_failures={counts['fetch_failures']}"
            )

    with _session() as db:
        counts = backfill_wayback_images(
            db,
            max_items=max_items,
            fetch_workers=fetch_workers,
            request_delay=request_delay,
            progress=_progress,
        )
        db.commit()
    console.print_json(data=counts)


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


@app.command("sync-local-to-prod")
def sync_local_to_prod_command(
    local_db: str | None = typer.Option(
        None,
        "--local-db",
        help=(
            "Canonical local SQLite SQLAlchemy URL. Defaults to BPV_SYNC_LOCAL_DATABASE_URL, "
            "then BPV_DATABASE_URL."
        ),
    ),
    prod_db: str | None = typer.Option(
        None,
        "--prod-db",
        help="Production PostgreSQL SQLAlchemy URL. Defaults to BPV_SYNC_PROD_DATABASE_URL.",
    ),
    tables: str | None = typer.Option(
        None,
        "--tables",
        help=(
            "Comma-separated sync table list or 'all'. Defaults to BPV_SYNC_TABLES. "
            "Runtime scan/evaluation tables are forbidden."
        ),
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Count rows without writing to production."),
    apply: bool = typer.Option(False, "--apply", help="Apply idempotent upserts to production."),
    validate_only: bool = typer.Option(False, "--validate-only", help="Compare local/prod counts without writing."),
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        help="Sync row selection strategy: auto, full, or delta. Defaults to BPV_SYNC_STRATEGY.",
    ),
    batch_size: int | None = typer.Option(None, "--batch-size", min=1),
    skip_migrations: bool = typer.Option(
        False,
        "--skip-migrations",
        help="Skip Alembic upgrade before --apply. Intended only for tests or already-migrated databases.",
    ),
) -> None:
    selected_modes = sum(bool(flag) for flag in (dry_run, apply, validate_only))
    if selected_modes > 1:
        raise typer.BadParameter("Use only one of --dry-run, --apply, or --validate-only.")
    mode = "apply" if apply else "validate-only" if validate_only else "dry-run"
    settings = get_settings()
    resolved_local_db = local_db or settings.sync_local_database_url or settings.database_url
    resolved_prod_db = prod_db or settings.sync_prod_database_url
    resolved_tables = tables or settings.sync_tables
    resolved_strategy = strategy or settings.sync_strategy
    resolved_batch_size = batch_size or settings.sync_batch_size

    if not resolved_prod_db:
        raise typer.BadParameter("Provide --prod-db or set BPV_SYNC_PROD_DATABASE_URL in .env.")
    if resolved_strategy not in {"auto", "full", "delta"}:
        raise typer.BadParameter("--strategy must be one of: auto, full, delta.")

    if mode == "apply" and not skip_migrations:
        console.print("Running Alembic migrations on production database...")
        run_prod_migrations(resolved_prod_db)

    result = sync_local_to_prod(
        local_db_url=resolved_local_db,
        prod_db_url=resolved_prod_db,
        tables=resolved_tables,
        mode=mode,
        strategy=resolved_strategy,
        batch_size=resolved_batch_size,
    )
    console.print_json(data=result.as_dict())

    if result.status in {"failed", "validation_failed"}:
        raise typer.Exit(code=1)


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


def import_ewg_wayback_entry() -> None:
    _run_single_command("import-ewg-wayback")


def backfill_ewg_wayback_images_entry() -> None:
    _run_single_command("backfill-ewg-wayback-images")


def index_images_entry() -> None:
    _run_single_command("index-images")


def refresh_risk_signals_entry() -> None:
    _run_single_command("refresh-risk-signals")


def sync_local_to_prod_entry() -> None:
    _run_single_command("sync-local-to-prod")
