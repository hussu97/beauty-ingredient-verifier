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


@app.command("enrich-ingredients")
def enrich_ingredients_command(
    pubchem_live: bool = typer.Option(False, "--pubchem-live", help="Enable live PubChem lookups."),
    limit: int = typer.Option(25, "--limit", min=1),
) -> None:
    with _session() as db:
        count = enrich_ingredients(db, pubchem_live=pubchem_live, limit=limit)
        db.commit()
    console.print(f"Enriched {count} ingredient/risk record(s).")


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


def index_images_entry() -> None:
    _run_single_command("index-images")


def refresh_risk_signals_entry() -> None:
    _run_single_command("refresh-risk-signals")
