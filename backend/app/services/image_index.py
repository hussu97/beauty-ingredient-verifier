from __future__ import annotations

import logging
import json
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ImageEmbedding, ProductImage
from app.services.codes import make_code
from app.services.ml import ImageVector, embed_image
from app.services.vector_store import upsert_sqlite_vec_embedding

PENDING_IMAGE_STATUSES = ("pending", "indexing")
RETRYABLE_IMAGE_STATUSES = ("failed", "download-failed", "ml-unavailable")
TERMINAL_IMAGE_STATUSES = ("indexed", "download-failed", "ml-unavailable", "ml-disabled")
PROGRESS_FILENAME = "image-index-progress.json"
PAUSE_FILENAME = "image-index.pause"


@dataclass(frozen=True)
class ImageIndexBatchResult:
    attempted: int = 0
    indexed: int = 0
    download_failed: int = 0
    ml_unavailable: int = 0
    ml_disabled: int = 0
    paused: bool = False
    last_image_code: str | None = None
    attempted_image_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImageIndexRunResult:
    state: str
    run_id: str
    attempted: int
    indexed: int
    failed: int
    batches: int
    last_image_code: str | None
    counts: dict[str, int]


@dataclass(frozen=True)
class ImageDownloadTarget:
    image_code: str
    url: str | None
    local_path: str | None


@dataclass(frozen=True)
class ImageDownloadResult:
    image_code: str
    path: Path | None
    url: str | None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso_now() -> str:
    return _utcnow().isoformat()


def _progress_path() -> Path:
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings.storage_dir / PROGRESS_FILENAME


def _pause_path() -> Path:
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings.storage_dir / PAUSE_FILENAME


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def image_index_pause_requested() -> bool:
    return _pause_path().exists()


def set_image_index_paused(paused: bool) -> None:
    pause_path = _pause_path()
    if paused:
        pause_path.write_text(f"pause requested at {_iso_now()}\n", encoding="utf-8")
    elif pause_path.exists():
        pause_path.unlink()


def image_index_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(ProductImage.embedding_status, func.count()).group_by(ProductImage.embedding_status)
    ).all()
    counts = {str(status): int(count) for status, count in rows}
    total = sum(counts.values())
    counts["total"] = total
    counts["pending_for_index"] = sum(counts.get(status, 0) for status in PENDING_IMAGE_STATUSES)
    counts["retryable_failed"] = sum(counts.get(status, 0) for status in RETRYABLE_IMAGE_STATUSES)
    counts["terminal"] = sum(counts.get(status, 0) for status in TERMINAL_IMAGE_STATUSES)
    counts["embeddings"] = int(db.scalar(select(func.count()).select_from(ImageEmbedding)) or 0)
    return counts


def image_index_status(db: Session) -> dict:
    progress_path = _progress_path()
    progress = None
    if progress_path.exists():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            progress = {"state": "unreadable", "path": str(progress_path)}
    return {
        "paused": image_index_pause_requested(),
        "counts": image_index_counts(db),
        "progress": progress,
        "progress_path": str(progress_path),
        "pause_path": str(_pause_path()),
    }


def _eligible_statuses(*, retry_failed: bool) -> tuple[str, ...]:
    if retry_failed:
        return (*PENDING_IMAGE_STATUSES, *RETRYABLE_IMAGE_STATUSES)
    return PENDING_IMAGE_STATUSES


def reset_stale_indexing_images(db: Session) -> int:
    result = db.execute(
        update(ProductImage)
        .where(ProductImage.embedding_status == "indexing")
        .values(embedding_status="pending")
    )
    return int(result.rowcount or 0)


def _extension_from_response(url: str, content_type: str | None) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    return guessed if guessed in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"


def _short_barcode_unsplit_fallback_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc != "images.openbeautyfacts.org":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    try:
        products_index = parts.index("products")
    except ValueError:
        return None
    image_parts = parts[products_index + 1 :]
    if len(image_parts) < 3:
        return None
    filename = image_parts[-1]
    barcode_parts = image_parts[:-1]
    if not all(part.isdigit() for part in barcode_parts):
        return None
    barcode = "".join(barcode_parts)
    if len(barcode) > 8:
        return None
    next_parts = [*parts[: products_index + 1], barcode, filename]
    return urlunparse(parsed._replace(path="/" + "/".join(next_parts)))


def _download_image_target(target: ImageDownloadTarget) -> ImageDownloadResult:
    settings = get_settings()
    if not target.url:
        return ImageDownloadResult(image_code=target.image_code, path=None, url=None)

    cache_dir = settings.storage_dir / "product-images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(
            timeout=settings.image_download_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.open_beauty_facts_user_agent},
        ) as client:
            download_url = target.url
            response = client.get(download_url)
            if response.status_code == 404:
                fallback_url = _short_barcode_unsplit_fallback_url(download_url)
                if fallback_url is not None:
                    fallback_response = client.get(fallback_url)
                    if fallback_response.is_success:
                        response = fallback_response
                        download_url = fallback_url
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if content_type and "image" not in content_type.lower():
                raise ValueError(f"Unexpected image content type: {content_type}")
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_IMAGE_DOWNLOAD_BYTES:
                raise ValueError(f"Image exceeds {MAX_IMAGE_DOWNLOAD_BYTES} bytes")
            content = response.content
            if len(content) > MAX_IMAGE_DOWNLOAD_BYTES:
                raise ValueError(f"Image exceeds {MAX_IMAGE_DOWNLOAD_BYTES} bytes")
        extension = _extension_from_response(download_url, response.headers.get("content-type"))
        path = cache_dir / f"{target.image_code}{extension}"
        path.write_bytes(content)
        return ImageDownloadResult(image_code=target.image_code, path=path, url=download_url)
    except Exception:
        logger.exception("Image download failed for %s", target.url)
        return ImageDownloadResult(image_code=target.image_code, path=None, url=target.url)


def _resolve_image_target(target: ImageDownloadTarget) -> ImageDownloadResult:
    if target.local_path:
        path = Path(target.local_path)
        if path.exists():
            return ImageDownloadResult(image_code=target.image_code, path=path, url=target.url)
    return _download_image_target(target)


def _resolve_image_targets(
    targets: list[ImageDownloadTarget],
    *,
    download_workers: int,
) -> dict[str, ImageDownloadResult]:
    worker_count = max(1, int(download_workers))
    if worker_count == 1 or len(targets) <= 1:
        return {target.image_code: _resolve_image_target(target) for target in targets}

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = executor.map(_resolve_image_target, targets)
        return {result.image_code: result for result in results}


def _upsert_embedding(db: Session, image: ProductImage, image_vector: ImageVector) -> None:
    embedding_code = make_code("emb", f"{image_vector.model_name}:{image.image_code}")
    embedding = db.get(ImageEmbedding, embedding_code)
    if embedding is None:
        embedding = ImageEmbedding(
            embedding_code=embedding_code,
            image_code=image.image_code,
            product_code=image.product_code,
            model_name=image_vector.model_name,
            dimensions=image_vector.dimensions,
            vector=image_vector.vector,
        )
        db.add(embedding)
    else:
        embedding.model_name = image_vector.model_name
        embedding.dimensions = image_vector.dimensions
        embedding.vector = image_vector.vector

    settings = get_settings()
    if settings.enable_sqlite_vec:
        upsert_sqlite_vec_embedding(
            db,
            embedding_code=embedding_code,
            image_code=image.image_code,
            product_code=image.product_code,
            model_name=image_vector.model_name,
            vector=image_vector.vector,
        )


def index_image_batch(
    db: Session,
    limit: int = 100,
    *,
    retry_failed: bool = True,
    download_workers: int = 1,
    exclude_image_codes: set[str] | None = None,
) -> ImageIndexBatchResult:
    settings = get_settings()
    statuses = _eligible_statuses(retry_failed=retry_failed)
    stmt = (
        select(ProductImage)
        .where(ProductImage.embedding_status.in_(statuses))
        .order_by(ProductImage.created_at, ProductImage.image_code)
        .limit(limit)
    )
    if exclude_image_codes:
        stmt = stmt.where(ProductImage.image_code.not_in(exclude_image_codes))
    images = db.scalars(stmt).all()
    attempted = 0
    indexed = 0
    download_failed = 0
    ml_unavailable = 0
    ml_disabled = 0
    last_image_code = None
    active_images: list[ProductImage] = []
    download_targets: list[ImageDownloadTarget] = []
    attempted_image_codes: list[str] = []
    for image in images:
        if image_index_pause_requested():
            return ImageIndexBatchResult(
                attempted=attempted,
                indexed=indexed,
                download_failed=download_failed,
                ml_unavailable=ml_unavailable,
                ml_disabled=ml_disabled,
                paused=True,
                last_image_code=last_image_code,
            )

        image.embedding_status = "indexing"
        active_images.append(image)
        download_targets.append(
            ImageDownloadTarget(
                image_code=image.image_code,
                url=image.url,
                local_path=image.local_path,
            )
        )
    if not active_images:
        return ImageIndexBatchResult()

    db.flush()
    download_results = _resolve_image_targets(download_targets, download_workers=download_workers)

    for image in active_images:
        if image_index_pause_requested():
            return ImageIndexBatchResult(
                attempted=attempted,
                indexed=indexed,
                download_failed=download_failed,
                ml_unavailable=ml_unavailable,
                ml_disabled=ml_disabled,
                paused=True,
                last_image_code=last_image_code,
            )
        db.flush()
        download_result = download_results.get(image.image_code)
        path = download_result.path if download_result else None
        attempted += 1
        attempted_image_codes.append(image.image_code)
        last_image_code = image.image_code
        if path is None:
            image.embedding_status = "download-failed"
            download_failed += 1
            continue
        image.local_path = str(path)
        if download_result and download_result.url and download_result.url != image.url:
            image.url = download_result.url

        image_vector = embed_image(
            path,
            enabled=settings.enable_optional_ml,
            model_name=settings.image_embedding_model,
        )
        if image_vector is None:
            image.embedding_status = "ml-unavailable" if settings.enable_optional_ml else "ml-disabled"
            if settings.enable_optional_ml:
                ml_unavailable += 1
            else:
                ml_disabled += 1
            continue

        _upsert_embedding(db, image, image_vector)
        image.embedding_status = "indexed"
        indexed += 1
    return ImageIndexBatchResult(
        attempted=attempted,
        indexed=indexed,
        download_failed=download_failed,
        ml_unavailable=ml_unavailable,
        ml_disabled=ml_disabled,
        last_image_code=last_image_code,
        attempted_image_codes=tuple(attempted_image_codes),
    )


def index_images(db: Session, limit: int = 100, *, download_workers: int = 1) -> int:
    return index_image_batch(
        db,
        limit=limit,
        retry_failed=True,
        download_workers=download_workers,
    ).attempted


def run_resumable_image_index(
    db: Session,
    *,
    batch_size: int = 50,
    max_images: int | None = None,
    retry_failed: bool = False,
    download_workers: int = 1,
) -> ImageIndexRunResult:
    run_id = f"idx_{_utcnow().strftime('%Y%m%d_%H%M%S')}"
    started_at = _iso_now()
    reset_stale_indexing_images(db)
    db.commit()

    attempted = 0
    indexed = 0
    failed = 0
    batches = 0
    last_image_code = None
    attempted_image_codes: set[str] = set()
    state = "running"

    def write_progress(next_state: str) -> None:
        payload = {
            "batch_size": batch_size,
            "batches": batches,
            "counts": image_index_counts(db),
            "download_workers": download_workers,
            "failed_this_run": failed,
            "indexed_this_run": indexed,
            "last_image_code": last_image_code,
            "max_images": max_images,
            "pause_requested": image_index_pause_requested(),
            "processed_this_run": attempted,
            "retry_failed": retry_failed,
            "run_id": run_id,
            "started_at": started_at,
            "state": next_state,
            "updated_at": _iso_now(),
        }
        _write_json_atomic(_progress_path(), payload)

    write_progress(state)
    while True:
        if image_index_pause_requested():
            state = "paused"
            write_progress(state)
            break
        if max_images is not None and attempted >= max_images:
            state = "max-images-reached"
            write_progress(state)
            break

        remaining = batch_size if max_images is None else min(batch_size, max_images - attempted)
        if remaining <= 0:
            state = "max-images-reached"
            write_progress(state)
            break

        result = index_image_batch(
            db,
            limit=remaining,
            retry_failed=retry_failed,
            download_workers=download_workers,
            exclude_image_codes=attempted_image_codes if retry_failed else None,
        )
        db.commit()
        if result.attempted == 0:
            state = "complete"
            write_progress(state)
            break

        batches += 1
        attempted += result.attempted
        indexed += result.indexed
        failed += result.download_failed + result.ml_unavailable + result.ml_disabled
        attempted_image_codes.update(result.attempted_image_codes)
        last_image_code = result.last_image_code or last_image_code
        state = "paused" if result.paused else "running"
        write_progress(state)
        if result.paused:
            break

    counts = image_index_counts(db)
    return ImageIndexRunResult(
        state=state,
        run_id=run_id,
        attempted=attempted,
        indexed=indexed,
        failed=failed,
        batches=batches,
        last_image_code=last_image_code,
        counts=counts,
    )
logger = logging.getLogger(__name__)
MAX_IMAGE_DOWNLOAD_BYTES = 15 * 1024 * 1024
