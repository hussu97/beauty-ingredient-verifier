from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    CanonicalTerm,
    Ingredient,
    IngredientSourceLink,
    Product,
    ProductSourceLink,
    RiskRule,
    ScanJob,
    Source,
    SourceRecord,
    SourceRecordFact,
)
from app.db.session import get_db
from app.schemas import ImportStatusOut

router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("/status", response_model=ImportStatusOut)
def import_status(db: Session = Depends(get_db)) -> ImportStatusOut:
    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model)) or 0

    conflict_products = (
        select(ProductSourceLink.product_code)
        .where(ProductSourceLink.active.is_(True))
        .group_by(ProductSourceLink.product_code)
        .having(func.count(func.distinct(ProductSourceLink.source_code)) > 1)
        .subquery()
    )
    return ImportStatusOut(
        products=count(Product),
        ingredients=count(Ingredient),
        sources=count(Source),
        source_records=count(SourceRecord),
        risk_rules=count(RiskRule),
        scan_jobs=count(ScanJob),
        product_source_links=count(ProductSourceLink),
        ingredient_source_links=count(IngredientSourceLink),
        canonical_terms=count(CanonicalTerm),
        source_record_facts=count(SourceRecordFact),
        ewg_source_records=db.scalar(
            select(func.count())
            .select_from(SourceRecord)
            .where(SourceRecord.source_code == "src_ewg_skin_deep")
        )
        or 0,
        source_conflict_products=db.scalar(select(func.count()).select_from(conflict_products)) or 0,
    )
