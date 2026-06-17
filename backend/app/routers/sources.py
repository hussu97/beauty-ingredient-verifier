from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Source
from app.db.session import get_db
from app.schemas import SourceOut

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[Source]:
    return list(db.scalars(select(Source).order_by(Source.name)).all())
