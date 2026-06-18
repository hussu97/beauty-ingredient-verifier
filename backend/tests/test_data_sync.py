from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import Base, Brand, Product, Source, SourceRecord, SyncRun
from app.db.session import apply_sqlite_pragmas
from app.services.data_sync import (
    RUNTIME_TABLE_NAMES,
    SYNC_TABLE_ORDER,
    parse_sync_tables,
    sync_local_to_prod,
)


def _sqlite_url(path) -> str:
    return f"sqlite:///{path}"


def _create_sqlite_db(path) -> None:
    engine = create_engine(_sqlite_url(path), future=True)
    apply_sqlite_pragmas(engine)
    Base.metadata.create_all(engine)
    engine.dispose()


def _seed_catalog(path, *, product_name: str) -> None:
    engine = create_engine(_sqlite_url(path), future=True)
    with Session(engine) as db:
        source = Source(
            source_code="src_test",
            name="Test Source",
            kind="fixture",
            homepage_url=None,
            license_name=None,
            terms_url=None,
            reliability="test",
        )
        record = SourceRecord(
            source_record_code="sr_test_product",
            source_code="src_test",
            external_id="fixture-1",
            record_type="product",
            source_url="https://example.test/product/1",
            content_hash="hash-1",
            payload={"name": product_name},
        )
        brand = Brand(
            brand_code="brd_test",
            name="Example Brand",
            normalized_name="example brand",
            source_record_code="sr_test_product",
        )
        product = Product(
            product_code="prd_test",
            barcode="1234567890123",
            name=product_name,
            normalized_name=product_name.lower(),
            brand_code="brd_test",
            source_record_code="sr_test_product",
            category_text="cleanser",
            ingredient_text="water",
            data_quality_warnings=[],
            confidence_score=0.9,
        )
        db.add_all([source, record, brand, product])
        db.commit()
    engine.dispose()


def test_sync_table_selection_blocks_runtime_tables() -> None:
    assert not (set(SYNC_TABLE_ORDER) & RUNTIME_TABLE_NAMES)

    with pytest.raises(ValueError, match="Runtime tables"):
        parse_sync_tables("sources,scan_jobs")

    assert parse_sync_tables("products,sources") == ["sources", "products"]


def test_sync_local_to_prod_upserts_and_records_run(tmp_path) -> None:
    source_path = tmp_path / "source.sqlite3"
    target_path = tmp_path / "target.sqlite3"
    _create_sqlite_db(source_path)
    _create_sqlite_db(target_path)
    _seed_catalog(source_path, product_name="Fresh Product")
    _seed_catalog(target_path, product_name="Stale Product")

    result = sync_local_to_prod(
        local_db_url=_sqlite_url(source_path),
        prod_db_url=_sqlite_url(target_path),
        tables="sources,source_records,brands,products",
        mode="apply",
        batch_size=2,
    )

    assert result.status == "succeeded"
    assert result.sync_run_code is not None
    assert result.row_counts["products"]["upserted_rows"] == 1

    engine = create_engine(_sqlite_url(target_path), future=True)
    with Session(engine) as db:
        product = db.get(Product, "prd_test")
        assert product is not None
        assert product.name == "Fresh Product"
        sync_run = db.scalars(select(SyncRun)).one()
        assert sync_run.status == "succeeded"
        assert sync_run.tables == ["sources", "source_records", "brands", "products"]
    engine.dispose()


def test_sync_local_to_prod_dry_run_does_not_write(tmp_path) -> None:
    source_path = tmp_path / "source.sqlite3"
    target_path = tmp_path / "target.sqlite3"
    _create_sqlite_db(source_path)
    _create_sqlite_db(target_path)
    _seed_catalog(source_path, product_name="Fresh Product")

    result = sync_local_to_prod(
        local_db_url=_sqlite_url(source_path),
        prod_db_url=_sqlite_url(target_path),
        tables="sources",
        mode="dry-run",
    )

    assert result.status == "dry-run"
    assert result.row_counts["sources"]["source_rows"] == 1
    assert result.row_counts["sources"]["target_rows_after"] == 0

    engine = create_engine(_sqlite_url(target_path), future=True)
    with Session(engine) as db:
        assert db.get(Source, "src_test") is None
        assert db.scalars(select(SyncRun)).all() == []
    engine.dispose()
