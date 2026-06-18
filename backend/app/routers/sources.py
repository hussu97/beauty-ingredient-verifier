from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    CanonicalTerm,
    IngredientTermLink,
    Product,
    ProductSourceLink,
    ProductTermLink,
    Source,
)
from app.db.session import get_db
from app.schemas import SourceConflictProductOut, SourceOut, SourceTermSummaryOut
from app.services.source_fusion import product_source_conflicts

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[Source]:
    return list(db.scalars(select(Source).order_by(Source.name)).all())


@router.get("/terms", response_model=list[SourceTermSummaryOut])
def list_source_terms(limit: int = 120, db: Session = Depends(get_db)) -> list[SourceTermSummaryOut]:
    product_counts = dict(
        db.execute(
            select(ProductTermLink.term_code, func.count(ProductTermLink.product_code))
            .group_by(ProductTermLink.term_code)
        ).all()
    )
    ingredient_counts = dict(
        db.execute(
            select(IngredientTermLink.term_code, func.count(IngredientTermLink.ingredient_code))
            .group_by(IngredientTermLink.term_code)
        ).all()
    )
    terms = db.scalars(
        select(CanonicalTerm)
        .order_by(CanonicalTerm.term_type, CanonicalTerm.label)
        .limit(limit)
    ).all()
    return [
        SourceTermSummaryOut(
            term_code=term.term_code,
            term_type=term.term_type,
            slug=term.slug,
            label=term.label,
            product_count=product_counts.get(term.term_code, 0),
            ingredient_count=ingredient_counts.get(term.term_code, 0),
        )
        for term in terms
    ]


@router.get("/conflicts", response_model=list[SourceConflictProductOut])
def list_source_conflicts(limit: int = 50, db: Session = Depends(get_db)) -> list[SourceConflictProductOut]:
    products = db.scalars(
        select(Product)
        .join(ProductSourceLink)
        .options(
            selectinload(Product.brand),
            selectinload(Product.source_links).selectinload(ProductSourceLink.source),
            selectinload(Product.source_links).selectinload(ProductSourceLink.source_record),
        )
        .group_by(Product.product_code)
        .order_by(Product.updated_at.desc())
        .limit(limit * 4)
    ).unique().all()
    rows: list[SourceConflictProductOut] = []
    for product in products:
        conflicts = product_source_conflicts(product)
        if conflicts:
            rows.append(
                SourceConflictProductOut(
                    product_code=product.product_code,
                    product_name=product.name,
                    source_conflicts=conflicts,
                )
            )
        if len(rows) >= limit:
            break
    return rows
