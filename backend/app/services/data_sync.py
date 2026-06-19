from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, Table, create_engine, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db.models import Base, SyncRun
from app.services.codes import make_code, stable_hash

SyncMode = Literal["dry-run", "apply", "validate-only"]
SyncStrategy = Literal["auto", "full", "delta"]

RUNTIME_TABLE_NAMES = frozenset(
    {
        "scan_jobs",
        "scan_candidates",
        "risk_evaluations",
    }
)

SYNC_TABLE_ORDER = (
    "sources",
    "source_records",
    "brands",
    "categories",
    "products",
    "ingredients",
    "source_record_facts",
    "product_categories",
    "product_images",
    "ingredient_synonyms",
    "product_ingredients",
    "product_source_links",
    "ingredient_source_links",
    "canonical_terms",
    "term_aliases",
    "product_term_links",
    "ingredient_term_links",
    "risk_rules",
    "adverse_event_signals",
    "image_embeddings",
)

POSTGRES_VECTOR_DIMENSIONS = 512


@dataclass(frozen=True)
class TableSyncResult:
    table: str
    source_rows: int
    selected_source_rows: int
    target_rows_before: int
    target_rows_after: int
    upserted_rows: int = 0
    matched: bool = False
    strategy: str = "full"
    watermark_column: str | None = None
    watermark_value: str | None = None
    full_bootstrap: bool = False


@dataclass(frozen=True)
class CatalogSyncResult:
    sync_run_code: str | None
    mode: SyncMode
    status: str
    source_database: str
    source_fingerprint: str
    tables: list[str]
    row_counts: dict[str, dict[str, Any]]
    started_at: str
    finished_at: str
    failure_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_sync_tables(selection: str | list[str] | tuple[str, ...] | None = "all") -> list[str]:
    if selection is None or selection == "all":
        return list(SYNC_TABLE_ORDER)

    if isinstance(selection, str):
        requested = {item.strip() for item in selection.split(",") if item.strip()}
    else:
        requested = {item.strip() for item in selection if item.strip()}

    if not requested or requested == {"all"}:
        return list(SYNC_TABLE_ORDER)

    runtime = sorted(requested & RUNTIME_TABLE_NAMES)
    if runtime:
        raise ValueError(f"Runtime tables cannot be synced to production: {', '.join(runtime)}")

    known = set(SYNC_TABLE_ORDER)
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError(f"Unknown sync table(s): {', '.join(unknown)}")

    return [table_name for table_name in SYNC_TABLE_ORDER if table_name in requested]


def safe_database_url(database_url: str) -> str:
    return make_url(database_url).render_as_string(hide_password=True)


def source_database_identity(database_url: str) -> tuple[str, str]:
    url = make_url(database_url)
    safe_url = url.render_as_string(hide_password=True)
    identity: dict[str, Any] = {"url": safe_url}

    if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
        path = Path(url.database)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        identity["path"] = str(path)

    return safe_url, stable_hash(identity, length=24)


def run_prod_migrations(database_url: str) -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    previous_url = os.environ.get("BPV_DATABASE_URL")
    os.environ["BPV_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        command.upgrade(config, "head")
    finally:
        if previous_url is None:
            os.environ.pop("BPV_DATABASE_URL", None)
        else:
            os.environ["BPV_DATABASE_URL"] = previous_url
        get_settings.cache_clear()


def _table(table_name: str) -> Table:
    return Base.metadata.tables[table_name]


def _count_rows(connection: Connection, table: Table) -> int:
    return int(connection.scalar(select(func.count()).select_from(table)) or 0)


def _count_selected_rows(
    connection: Connection,
    table: Table,
    *,
    watermark_column: sa.Column[Any] | None = None,
    watermark_value: datetime | None = None,
) -> int:
    statement = select(func.count()).select_from(table)
    if watermark_column is not None and watermark_value is not None:
        statement = statement.where(watermark_column >= watermark_value)
    return int(connection.scalar(statement) or 0)


def _ordered_select(
    table: Table,
    *,
    watermark_column: sa.Column[Any] | None = None,
    watermark_value: datetime | None = None,
) -> sa.Select[Any]:
    primary_key_columns = list(table.primary_key.columns)
    statement = select(table)
    if watermark_column is not None and watermark_value is not None:
        statement = statement.where(watermark_column >= watermark_value)
    if primary_key_columns:
        statement = statement.order_by(*primary_key_columns)
    return statement


def _row_batches(
    connection: Connection,
    table: Table,
    batch_size: int,
    *,
    watermark_column: sa.Column[Any] | None = None,
    watermark_value: datetime | None = None,
):
    result = connection.execution_options(stream_results=True).execute(
        _ordered_select(table, watermark_column=watermark_column, watermark_value=watermark_value)
    )
    while True:
        rows = result.fetchmany(batch_size)
        if not rows:
            break
        yield [dict(row._mapping) for row in rows]


def _watermark_column(table: Table) -> sa.Column[Any] | None:
    for column_name in ("updated_at", "created_at", "fetched_at", "source_updated_at"):
        if column_name in table.c:
            return table.c[column_name]
    return None


def _latest_successful_sync_watermark(
    connection: Connection,
    *,
    source_database: str,
    source_fingerprint: str,
    table_name: str,
) -> datetime | None:
    sync_runs = SyncRun.__table__
    try:
        rows = connection.execute(
            select(sync_runs.c.finished_at, sync_runs.c.tables)
            .where(
                sync_runs.c.mode == "apply",
                sync_runs.c.status == "succeeded",
                sa.or_(
                    sync_runs.c.source_fingerprint == source_fingerprint,
                    sync_runs.c.source_database == source_database,
                ),
                sync_runs.c.finished_at.is_not(None),
            )
            .order_by(sync_runs.c.finished_at.desc())
        )
    except sa.exc.DBAPIError:
        return None
    for finished_at, tables in rows:
        if table_name in (tables or []):
            return finished_at
    return None


def _insert_for_target(connection: Connection, table: Table):
    if connection.dialect.name == "postgresql":
        return postgres_insert(table)
    if connection.dialect.name == "sqlite":
        return sqlite_insert(table)
    raise ValueError(
        f"Unsupported sync target dialect {connection.dialect.name!r}; use PostgreSQL "
        "for production or SQLite in tests."
    )


def _upsert_batch(connection: Connection, table: Table, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    if connection.dialect.name == "postgresql":
        return _upsert_batch_postgres_temp(connection, table, rows)

    primary_key_names = [column.name for column in table.primary_key.columns]
    if not primary_key_names:
        raise ValueError(f"Cannot sync {table.name}; table has no primary key")

    insert_statement = _insert_for_target(connection, table).values(rows)
    update_columns = [column.name for column in table.columns if column.name not in primary_key_names]
    if update_columns:
        excluded = insert_statement.excluded
        insert_statement = insert_statement.on_conflict_do_update(
            index_elements=primary_key_names,
            set_={name: getattr(excluded, name) for name in update_columns},
        )
    else:
        insert_statement = insert_statement.on_conflict_do_nothing(
            index_elements=primary_key_names,
        )

    connection.execute(insert_statement)
    return len(rows)


def _quote_identifier(connection: Connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote(identifier)


def _copy_value(value: Any, column: sa.Column[Any]) -> Any:
    if value is None:
        return None
    if isinstance(column.type, sa.JSON):
        return json.dumps(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _copy_rows_to_temp_postgres(
    connection: Connection,
    *,
    temp_name: str,
    table: Table,
    rows: list[dict[str, Any]],
) -> bool:
    driver_connection = getattr(connection.connection, "driver_connection", None)
    if driver_connection is None or not hasattr(driver_connection, "cursor"):
        return False

    columns = list(table.columns)
    quoted_columns = ", ".join(_quote_identifier(connection, column.name) for column in columns)
    copy_sql = f"COPY {_quote_identifier(connection, temp_name)} ({quoted_columns}) FROM STDIN"
    nested = connection.begin_nested()
    try:
        with driver_connection.cursor() as cursor:
            with cursor.copy(copy_sql) as copy:
                for row in rows:
                    copy.write_row(
                        tuple(_copy_value(row.get(column.name), column) for column in columns)
                    )
        nested.commit()
        return True
    except Exception:
        nested.rollback()
        return False


def _insert_rows_to_temp(
    connection: Connection,
    *,
    temp_name: str,
    table: Table,
    rows: list[dict[str, Any]],
) -> None:
    temp_metadata = sa.MetaData()
    temp_table = sa.Table(
        temp_name,
        temp_metadata,
        *(sa.Column(column.name, column.type) for column in table.columns),
    )
    connection.execute(temp_table.insert(), rows)


def _upsert_batch_postgres_temp(
    connection: Connection,
    table: Table,
    rows: list[dict[str, Any]],
) -> int:
    primary_key_names = [column.name for column in table.primary_key.columns]
    if not primary_key_names:
        raise ValueError(f"Cannot sync {table.name}; table has no primary key")

    temp_hash = stable_hash({"first": rows[0], "last": rows[-1]}, length=8)
    temp_name = f"_bpv_sync_{table.name}_{temp_hash}"
    quoted_temp = _quote_identifier(connection, temp_name)
    quoted_table = _quote_identifier(connection, table.name)
    connection.execute(
        sa.text(
            f"CREATE TEMP TABLE {quoted_temp} (LIKE {quoted_table} INCLUDING DEFAULTS) ON COMMIT DROP"
        )
    )

    copied = _copy_rows_to_temp_postgres(connection, temp_name=temp_name, table=table, rows=rows)
    if not copied:
        _insert_rows_to_temp(connection, temp_name=temp_name, table=table, rows=rows)

    column_names = [column.name for column in table.columns]
    quoted_columns = ", ".join(_quote_identifier(connection, name) for name in column_names)
    select_columns = ", ".join(_quote_identifier(connection, name) for name in column_names)
    conflict_columns = ", ".join(_quote_identifier(connection, name) for name in primary_key_names)
    update_columns = [name for name in column_names if name not in primary_key_names]

    if update_columns:
        update_sql = ", ".join(
            f"{_quote_identifier(connection, name)} = EXCLUDED.{_quote_identifier(connection, name)}"
            for name in update_columns
        )
        conflict_sql = f"DO UPDATE SET {update_sql}"
    else:
        conflict_sql = "DO NOTHING"

    try:
        connection.execute(
            sa.text(
                f"""
                INSERT INTO {quoted_table} ({quoted_columns})
                SELECT {select_columns}
                FROM {quoted_temp}
                ON CONFLICT ({conflict_columns}) {conflict_sql}
                """
            )
        )
    finally:
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {quoted_temp}"))
    return len(rows)


def _insert_sync_run(
    engine: Engine,
    *,
    sync_run_code: str,
    mode: SyncMode,
    source_database: str,
    source_fingerprint: str,
    tables: list[str],
    started_at: datetime,
) -> None:
    sync_runs = SyncRun.__table__
    with engine.begin() as connection:
        connection.execute(
            sa.insert(sync_runs).values(
                sync_run_code=sync_run_code,
                mode=mode,
                status="running",
                source_database=source_database,
                source_fingerprint=source_fingerprint,
                tables=tables,
                row_counts={},
                failure_message=None,
                started_at=started_at,
                finished_at=None,
            )
        )


def _finish_sync_run(
    engine: Engine,
    *,
    sync_run_code: str,
    status: str,
    row_counts: dict[str, dict[str, Any]],
    failure_message: str | None,
    finished_at: datetime,
) -> None:
    sync_runs = SyncRun.__table__
    with engine.begin() as connection:
        connection.execute(
            sa.update(sync_runs)
            .where(sync_runs.c.sync_run_code == sync_run_code)
            .values(
                status=status,
                row_counts=row_counts,
                failure_message=failure_message,
                finished_at=finished_at,
            )
        )


def _vector_literal(vector: list[float]) -> str:
    return json.dumps([float(item) for item in vector])


def refresh_postgres_vector_index(engine: Engine, *, batch_size: int = 500) -> int:
    if engine.dialect.name != "postgresql":
        return 0

    image_embeddings = _table("image_embeddings")
    total = 0
    select_statement = (
        select(
            image_embeddings.c.embedding_code,
            image_embeddings.c.image_code,
            image_embeddings.c.product_code,
            image_embeddings.c.model_name,
            image_embeddings.c.dimensions,
            image_embeddings.c.vector,
        )
        .where(image_embeddings.c.dimensions == POSTGRES_VECTOR_DIMENSIONS)
        .order_by(image_embeddings.c.embedding_code)
    )
    upsert_statement = sa.text(
        """
        INSERT INTO image_embedding_vectors (
            embedding_code,
            image_code,
            product_code,
            model_name,
            dimensions,
            embedding,
            updated_at
        )
        VALUES (
            :embedding_code,
            :image_code,
            :product_code,
            :model_name,
            :dimensions,
            CAST(:embedding AS vector),
            now()
        )
        ON CONFLICT (embedding_code) DO UPDATE SET
            image_code = EXCLUDED.image_code,
            product_code = EXCLUDED.product_code,
            model_name = EXCLUDED.model_name,
            dimensions = EXCLUDED.dimensions,
            embedding = EXCLUDED.embedding,
            updated_at = now()
        """
    )

    with engine.connect() as source_connection:
        result = source_connection.execution_options(stream_results=True).execute(select_statement)
        while True:
            rows = result.fetchmany(batch_size)
            if not rows:
                break
            payload = []
            for row in rows:
                mapping = row._mapping
                vector = mapping["vector"] or []
                if len(vector) != POSTGRES_VECTOR_DIMENSIONS:
                    continue
                payload.append(
                    {
                        "embedding_code": mapping["embedding_code"],
                        "image_code": mapping["image_code"],
                        "product_code": mapping["product_code"],
                        "model_name": mapping["model_name"],
                        "dimensions": mapping["dimensions"],
                        "embedding": _vector_literal(vector),
                    }
                )
            if not payload:
                continue
            with engine.begin() as target_connection:
                target_connection.execute(upsert_statement, payload)
            total += len(payload)

    return total


def sync_local_to_prod(
    *,
    local_db_url: str,
    prod_db_url: str,
    tables: str | list[str] | tuple[str, ...] | None = "all",
    mode: SyncMode = "dry-run",
    strategy: SyncStrategy = "auto",
    batch_size: int = 500,
    record_run: bool = True,
) -> CatalogSyncResult:
    if mode not in {"dry-run", "apply", "validate-only"}:
        raise ValueError(f"Unknown sync mode: {mode}")
    if strategy not in {"auto", "full", "delta"}:
        raise ValueError(f"Unknown sync strategy: {strategy}")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    table_names = parse_sync_tables(tables)
    source_database, source_fingerprint = source_database_identity(local_db_url)
    started_at = datetime.now(UTC)
    sync_run_code = (
        make_code(
            "syn",
            {
                "source": source_fingerprint,
                "started_at": started_at.isoformat(),
                "tables": table_names,
            },
        )
        if mode == "apply" and record_run
        else None
    )

    source_engine = create_engine(local_db_url, future=True)
    target_engine = create_engine(prod_db_url, future=True)
    row_counts: dict[str, dict[str, Any]] = {}
    failure_message: str | None = None
    status = "running" if mode == "apply" else mode

    if sync_run_code is not None:
        _insert_sync_run(
            target_engine,
            sync_run_code=sync_run_code,
            mode=mode,
            source_database=source_database,
            source_fingerprint=source_fingerprint,
            tables=table_names,
            started_at=started_at,
        )

    try:
        with source_engine.connect() as source_connection:
            for table_name in table_names:
                table = _table(table_name)
                source_rows = _count_rows(source_connection, table)
                with target_engine.connect() as target_connection:
                    target_rows_before = _count_rows(target_connection, table)
                    previous_watermark = _latest_successful_sync_watermark(
                        target_connection,
                        source_database=source_database,
                        source_fingerprint=source_fingerprint,
                        table_name=table_name,
                    )

                watermark_column = _watermark_column(table)
                selected_strategy = "full"
                watermark_value = None
                full_bootstrap = False
                if strategy in {"auto", "delta"} and watermark_column is not None:
                    if previous_watermark is not None and target_rows_before > 0:
                        selected_strategy = "delta"
                        watermark_value = previous_watermark
                    else:
                        full_bootstrap = True
                elif strategy == "delta":
                    full_bootstrap = True

                selected_rows = _count_selected_rows(
                    source_connection,
                    table,
                    watermark_column=watermark_column if selected_strategy == "delta" else None,
                    watermark_value=watermark_value,
                )

                upserted_rows = 0
                if mode == "apply":
                    with target_engine.begin() as target_connection:
                        for batch in _row_batches(
                            source_connection,
                            table,
                            batch_size,
                            watermark_column=watermark_column
                            if selected_strategy == "delta"
                            else None,
                            watermark_value=watermark_value,
                        ):
                            upserted_rows += _upsert_batch(target_connection, table, batch)

                with target_engine.connect() as target_connection:
                    target_rows_after = _count_rows(target_connection, table)

                row_counts[table_name] = asdict(
                    TableSyncResult(
                        table=table_name,
                        source_rows=source_rows,
                        selected_source_rows=selected_rows,
                        target_rows_before=target_rows_before,
                        target_rows_after=target_rows_after,
                        upserted_rows=upserted_rows,
                        matched=source_rows == target_rows_after,
                        strategy=selected_strategy,
                        watermark_column=watermark_column.name if selected_strategy == "delta" else None,
                        watermark_value=watermark_value.isoformat() if watermark_value else None,
                        full_bootstrap=full_bootstrap,
                    )
                )

        if mode == "apply" and "image_embeddings" in table_names:
            vector_rows = refresh_postgres_vector_index(target_engine, batch_size=batch_size)
            row_counts["image_embedding_vectors"] = {
                "source_rows": vector_rows,
                "target_rows_before": 0,
                "target_rows_after": vector_rows,
                "upserted_rows": vector_rows,
                "matched": True,
            }

        mismatched = [
            table_name
            for table_name, counts in row_counts.items()
            if table_name != "image_embedding_vectors" and not counts["matched"]
        ]
        if mismatched and mode != "dry-run":
            status = "validation_failed"
            failure_message = f"Row-count mismatch after sync: {', '.join(mismatched)}"
        elif mode == "apply":
            status = "succeeded"
        elif mode == "validate-only":
            status = "succeeded"
    except Exception as exc:
        status = "failed"
        failure_message = str(exc)
        if sync_run_code is not None:
            _finish_sync_run(
                target_engine,
                sync_run_code=sync_run_code,
                status=status,
                row_counts=row_counts,
                failure_message=failure_message,
                finished_at=datetime.now(UTC),
            )
        raise
    finally:
        finished_at = datetime.now(UTC)

    if sync_run_code is not None:
        _finish_sync_run(
            target_engine,
            sync_run_code=sync_run_code,
            status=status,
            row_counts=row_counts,
            failure_message=failure_message,
            finished_at=finished_at,
        )

    return CatalogSyncResult(
        sync_run_code=sync_run_code,
        mode=mode,
        status=status,
        source_database=source_database,
        source_fingerprint=source_fingerprint,
        tables=table_names,
        row_counts=row_counts,
        failure_message=failure_message,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
    )
