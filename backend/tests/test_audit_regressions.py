from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.schema import UniqueConstraint

from app.db import session as db_session_module
from app.db.models import (
    IngredientSourceLink,
    Product,
    ProductIngredient,
    ProductSourceLink,
    ScanJob,
    SourceRecord,
)
from app.services.normalization import normalize_text
from app.services.scanner import process_scan
from app.services.search import search_products
from app.services.source_records import upsert_source, upsert_source_record


def _sqlite_foreign_keys_enabled(engine) -> bool:
    if engine.dialect.name != "sqlite":
        pytest.skip("SQLite pragma audit applies only to SQLite engines")
    with engine.connect() as connection:
        return connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def _unique_column_sets(model) -> set[frozenset[str]]:
    table = model.__table__
    uniques = {
        frozenset(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    uniques.update(
        frozenset(column.name for column in index.columns)
        for index in table.indexes
        if index.unique
    )
    return uniques


def test_runtime_sqlite_engine_enables_foreign_keys():
    assert _sqlite_foreign_keys_enabled(db_session_module.engine)


def test_test_sqlite_engine_enables_foreign_keys():
    TestingSessionLocal = db_session_module.make_test_sessionmaker()
    engine = TestingSessionLocal.kw["bind"]

    assert _sqlite_foreign_keys_enabled(engine)


@pytest.mark.parametrize(
    ("model", "expected_columns"),
    [
        (SourceRecord, ("source_code", "external_id", "record_type")),
        (ProductIngredient, ("product_code", "ingredient_code")),
        (ProductSourceLink, ("product_code", "source_record_code")),
        (IngredientSourceLink, ("ingredient_code", "source_record_code")),
    ],
)
def test_model_metadata_declares_audit_unique_indexes(model, expected_columns):
    assert frozenset(expected_columns) in _unique_column_sets(model)


def test_source_record_upsert_keeps_record_type_in_identity(db_session: Session):
    upsert_source(
        db_session,
        source_code="src_audit_record_type",
        name="Audit Record Type Source",
        kind="test-source",
        homepage_url=None,
    )

    product_record = upsert_source_record(
        db_session,
        source_code="src_audit_record_type",
        external_id="shared-record",
        record_type="product",
        payload={"record": "product"},
    )
    ingredient_record = upsert_source_record(
        db_session,
        source_code="src_audit_record_type",
        external_id="shared-record",
        record_type="ingredient",
        payload={"record": "ingredient"},
    )
    db_session.flush()

    records = db_session.scalars(
        select(SourceRecord)
        .where(SourceRecord.source_code == "src_audit_record_type")
        .order_by(SourceRecord.record_type)
    ).all()

    assert product_record.source_record_code != ingredient_record.source_record_code
    assert {record.record_type for record in records} == {"ingredient", "product"}
    assert len(records) == 2
    assert product_record.payload == {"record": "product"}
    assert ingredient_record.payload == {"record": "ingredient"}


def test_search_scores_products_beyond_first_500_rows(db_session: Session):
    filler_products = []
    for index in range(520):
        name = f"Audit Filler Lotion {index:03d}"
        filler_products.append(
            Product(
                product_code=f"prd_audit_filler_{index:04d}",
                barcode=None,
                name=name,
                normalized_name=normalize_text(name),
                data_quality_warnings=[],
                confidence_score=0.5,
            )
        )
    db_session.add_all(filler_products)
    db_session.flush()

    target = Product(
        product_code="prd_zzzz_late_match",
        barcode=None,
        name="Audit Rare Late Match Gel",
        normalized_name=normalize_text("Audit Rare Late Match Gel"),
        data_quality_warnings=[],
        confidence_score=0.95,
    )
    db_session.add(target)
    db_session.flush()

    matches = search_products(db_session, query="Rare Late Match Gel", limit=5)

    assert [match.product.product_code for match in matches]
    assert matches[0].product.product_code == target.product_code


def test_process_scan_persists_failed_status_when_pipeline_raises(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    upload_path = tmp_path / "broken-scan.jpg"
    upload_path.write_bytes(b"not an image")

    def raise_pipeline_error(*args, **kwargs):
        raise RuntimeError("barcode engine unavailable")

    monkeypatch.setattr("app.services.scanner.extract_barcode", raise_pipeline_error)

    scan = process_scan(db_session, image_path=upload_path, upload_filename=upload_path.name)
    db_session.flush()

    persisted = db_session.get(ScanJob, scan.scan_code)

    assert persisted is not None
    assert persisted.status == "failed"
    assert "barcode engine unavailable" in (persisted.error_message or "")
    assert persisted.matched_product_code is None
