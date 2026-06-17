from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Ingredient, Product, RiskRule, ScanJob, Source, SourceRecord
from app.db.session import get_db
from app.schemas import ImportStatusOut

router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("/status", response_model=ImportStatusOut)
def import_status(db: Session = Depends(get_db)) -> ImportStatusOut:
    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model)) or 0

    return ImportStatusOut(
        products=count(Product),
        ingredients=count(Ingredient),
        sources=count(Source),
        source_records=count(SourceRecord),
        risk_rules=count(RiskRule),
        scan_jobs=count(ScanJob),
    )
