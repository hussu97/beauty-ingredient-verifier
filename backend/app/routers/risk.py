from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import RiskEvaluateIn, RiskEvaluationOut
from app.services.risk import evaluate_product_risk

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/evaluate", response_model=RiskEvaluationOut)
def evaluate(payload: RiskEvaluateIn, db: Session = Depends(get_db)) -> dict:
    try:
        result = evaluate_product_risk(
            db,
            payload.product_code,
            payload.profile.model_dump(),
        )
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
