from __future__ import annotations

import re
import shutil
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ScanCandidate, ScanJob
from app.db.session import SessionLocal
from app.services.codes import make_code
from app.services.importers.open_beauty_facts import lookup_open_beauty_facts_barcode
from app.services.ml import embed_image, extract_barcode, extract_ocr_text
from app.services.search import merge_product_matches, search_products, search_products_by_image_embedding

logger = logging.getLogger(__name__)


def _extract_fields(ocr_text: str) -> tuple[str | None, str | None, str | None]:
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    product_name = lines[0] if lines else (ocr_text.strip() or None)
    brand = lines[1] if len(lines) > 1 else None
    ingredient_text = None
    for line in lines:
        if "ingredient" in line.lower():
            ingredient_text = line.split(":", 1)[-1].strip()
            break
    return brand, product_name, ingredient_text


def save_upload(fileobj, filename: str) -> Path:
    settings = get_settings()
    uploads_dir = settings.storage_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "upload.jpg")
    target = uploads_dir / f"{make_code('upload')}_{safe_name}"
    with target.open("wb") as handle:
        shutil.copyfileobj(fileobj, handle)
    return target


def create_scan_job(db: Session, *, image_path: Path, upload_filename: str) -> ScanJob:
    scan = ScanJob(
        scan_code=make_code("scan"),
        upload_filename=upload_filename,
        image_path=str(image_path),
        status="pending",
    )
    db.add(scan)
    db.flush()
    return scan


def _run_scan(db: Session, scan: ScanJob) -> ScanJob:
    settings = get_settings()
    image_path = Path(scan.image_path)
    scan.status = "processing"
    scan.error_message = None
    scan.candidates.clear()
    db.flush()
    try:
        barcode = extract_barcode(image_path, enabled=settings.enable_optional_ml)
        if barcode:
            local_matches = search_products(db, barcode=barcode, limit=1)
            if not local_matches:
                looked_up = lookup_open_beauty_facts_barcode(db, barcode)
                if looked_up is not None:
                    db.flush()
        ocr_text = extract_ocr_text(
            image_path,
            enabled=settings.enable_optional_ml,
            language=settings.ocr_language,
        )
        brand, product_name, ingredient_text = _extract_fields(ocr_text)
        query = " ".join(part for part in [brand, product_name] if part)
        text_matches = search_products(
            db,
            query=query or upload_filename,
            barcode=barcode,
            ingredient_text=ingredient_text,
            limit=5,
        )
        image_vector = embed_image(
            image_path,
            enabled=settings.enable_optional_ml,
            model_name=settings.image_embedding_model,
        )
        image_matches = (
            search_products_by_image_embedding(
                db,
                vector=image_vector.vector,
                model_name=image_vector.model_name,
                limit=5,
            )
            if image_vector is not None
            else []
        )
        matches = merge_product_matches(text_matches, image_matches, limit=5)
        for rank, match in enumerate(matches, start=1):
            db.add(
                ScanCandidate(
                    candidate_code=make_code("cand", f"{scan.scan_code}:{match.product.product_code}:{rank}"),
                    scan_code=scan.scan_code,
                    product_code=match.product.product_code,
                    candidate_name=match.product.name,
                    brand_name=match.product.brand.name if match.product.brand else None,
                    confidence_score=match.confidence,
                    match_reasons=match.reasons,
                    rank=rank,
                )
            )
        best = matches[0] if matches else None
        scan.status = "completed"
        scan.barcode = barcode
        scan.ocr_text = ocr_text
        scan.extracted_brand = brand
        scan.extracted_product_name = product_name
        scan.extracted_ingredient_text = ingredient_text
        scan.confidence_score = best.confidence if best else 0
        scan.matched_product_code = best.product.product_code if best and best.confidence >= 0.62 else None
    except Exception as exc:
        logger.exception("Scan processing failed for %s", scan.scan_code)
        scan.status = "failed"
        scan.error_message = str(exc)
    db.flush()
    return scan


def process_scan(db: Session, *, image_path: Path, upload_filename: str) -> ScanJob:
    scan = create_scan_job(db, image_path=image_path, upload_filename=upload_filename)
    return _run_scan(db, scan)


def process_scan_job(scan_code: str) -> None:
    with SessionLocal() as db:
        scan = db.get(ScanJob, scan_code)
        if scan is None:
            logger.warning("Scan job %s disappeared before processing", scan_code)
            return
        _run_scan(db, scan)
        db.commit()
