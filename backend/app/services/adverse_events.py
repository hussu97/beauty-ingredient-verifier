from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AdverseEventSignal, Product
from app.services.codes import make_code
from app.services.source_records import upsert_source_record


def refresh_risk_signals(db: Session, limit: int = 10, live: bool = False) -> int:
    products = db.scalars(select(Product).limit(limit)).all()
    count = 0
    for product in products:
        if live:
            try:
                response = httpx.get(
                    "https://api.fda.gov/cosmetic/event.json",
                    params={"search": f'products.name:"{product.name}"', "limit": 1},
                    timeout=8,
                )
                payload = response.json() if response.status_code == 200 else {"results": []}
            except (httpx.HTTPError, ValueError):
                payload = {"results": []}
        else:
            payload = {"results": [], "note": "Live openFDA lookup disabled for local MVP"}
        record = upsert_source_record(
            db,
            source_code="src_openfda_cosmetic_events",
            external_id=f"product-signal:{product.product_code}",
            record_type="adverse-event-signal",
            payload=payload,
            source_url="https://open.fda.gov/apis/cosmetic/event/",
        )
        signal_code = make_code("sig", f"{product.product_code}:openfda")
        signal = db.get(AdverseEventSignal, signal_code)
        if signal is None:
            signal = AdverseEventSignal(
                signal_code=signal_code,
                product_code=product.product_code,
                ingredient_code=None,
                source_record_code=record.source_record_code,
                reaction_name="openFDA signal lookup",
                severity="unknown",
                report_count=len(payload.get("results", [])),
                signal_score=0.0,
                notes="Adverse-event reports are signals only and do not establish causation.",
            )
            db.add(signal)
        else:
            signal.report_count = len(payload.get("results", []))
            signal.source_record_code = record.source_record_code
        count += 1
    return count
