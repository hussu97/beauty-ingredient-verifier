from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Ingredient
from app.db.session import get_db
from app.schemas import IngredientDetailOut, IngredientSummaryOut
from app.services.normalization import normalize_text

router = APIRouter(prefix="/ingredients", tags=["ingredients"])


@router.get("", response_model=list[IngredientSummaryOut])
def list_ingredients(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Ingredient]:
    stmt = select(Ingredient).order_by(Ingredient.canonical_name).offset(offset).limit(limit)
    if q:
        normalized = f"%{normalize_text(q)}%"
        stmt = stmt.where(Ingredient.normalized_name.like(normalized))
    return list(db.scalars(stmt).all())


@router.get("/{ingredient_code}", response_model=IngredientDetailOut)
def get_ingredient(ingredient_code: str, db: Session = Depends(get_db)) -> Ingredient:
    ingredient = db.scalar(
        select(Ingredient)
        .where(Ingredient.ingredient_code == ingredient_code)
        .options(selectinload(Ingredient.risk_rules))
    )
    if ingredient is None:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    return ingredient
