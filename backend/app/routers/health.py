from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db
from app.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> HealthOut:
    db.execute(text("select 1"))
    return HealthOut(app=settings.app_name, env=settings.env, database="ok", status="ready")
