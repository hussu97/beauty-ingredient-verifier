from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.db.models import ScanJob
from app.db.session import get_db
from app.schemas import ScanJobOut
from app.services.scanner import create_scan_job, process_scan_job, save_upload

router = APIRouter(prefix="/scans", tags=["scan"])


@router.post("", response_model=ScanJobOut, status_code=status.HTTP_202_ACCEPTED)
def create_scan(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScanJob:
    max_bytes = settings.max_scan_upload_mb * 1024 * 1024
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > max_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds configured size limit")
    path = save_upload(file.file, file.filename or "upload.jpg")
    scan = create_scan_job(db, image_path=path, upload_filename=file.filename or path.name)
    db.commit()
    background_tasks.add_task(process_scan_job, scan.scan_code)
    return get_scan(scan.scan_code, db)


@router.get("/{scan_code}", response_model=ScanJobOut)
def get_scan(scan_code: str, db: Session = Depends(get_db)) -> ScanJob:
    scan = db.scalar(
        select(ScanJob)
        .where(ScanJob.scan_code == scan_code)
        .options(selectinload(ScanJob.candidates))
    )
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan
