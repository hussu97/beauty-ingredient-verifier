from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Source, SourceRecord, utcnow
from app.services.codes import content_hash, make_code


def upsert_source(
    db: Session,
    *,
    source_code: str,
    name: str,
    kind: str,
    homepage_url: str | None,
    license_name: str | None = None,
    terms_url: str | None = None,
    reliability: str = "source-backed",
) -> Source:
    source = db.get(Source, source_code)
    if source is None:
        source = Source(source_code=source_code, name=name, kind=kind)
        db.add(source)
    source.name = name
    source.kind = kind
    source.homepage_url = homepage_url
    source.license_name = license_name
    source.terms_url = terms_url
    source.reliability = reliability
    source.updated_at = utcnow()
    db.flush()
    return source


def upsert_source_record(
    db: Session,
    *,
    source_code: str,
    external_id: str,
    record_type: str,
    payload: dict[str, Any],
    source_url: str | None = None,
) -> SourceRecord:
    existing = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source_code == source_code,
            SourceRecord.record_type == record_type,
            SourceRecord.external_id == external_id,
        )
    )
    record_hash = content_hash(payload)
    if existing is None:
        existing = SourceRecord(
            source_record_code=make_code("sr", f"{source_code}:{record_type}:{external_id}"),
            source_code=source_code,
            external_id=external_id,
            record_type=record_type,
            payload=payload,
            content_hash=record_hash,
            source_url=source_url,
            fetched_at=utcnow(),
        )
        db.add(existing)
        db.flush()
    else:
        existing.payload = payload
        existing.content_hash = record_hash
        existing.record_type = record_type
        existing.source_url = source_url
        existing.fetched_at = utcnow()
        db.flush()
    return existing
