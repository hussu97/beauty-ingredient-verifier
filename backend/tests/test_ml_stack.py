from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ImageEmbedding, Product, ProductImage, ScanCandidate
from app.services.codes import make_code
from app.services.image_index import (
    ImageDownloadResult,
    _short_barcode_unsplit_fallback_url,
    image_index_status,
    index_images,
    run_resumable_image_index,
    set_image_index_paused,
)
from app.services.ml import ImageVector, barcode_from_filename
from app.services.scanner import process_scan


def test_barcode_from_filename_fallback():
    assert barcode_from_filename(Path("brand-3560070791460-front.jpg")) == "3560070791460"
    assert barcode_from_filename(Path("brand-front.jpg")) is None


def test_short_open_beauty_facts_image_url_fallback():
    assert _short_barcode_unsplit_fallback_url(
        "https://images.openbeautyfacts.org/images/products/000/328/31/front_fr.6.400.jpg"
    ) == "https://images.openbeautyfacts.org/images/products/00032831/front_fr.6.400.jpg"
    assert _short_barcode_unsplit_fallback_url(
        "https://images.openbeautyfacts.org/images/products/001/878/778/8059/front.3.400.jpg"
    ) is None


def test_index_images_uses_sentence_transformer_adapter(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_optional_ml", True)
    monkeypatch.setattr(settings, "enable_sqlite_vec", False)
    monkeypatch.setattr(settings, "storage_dir", tmp_path)

    for existing_image in db_session.scalars(select(ProductImage)).all():
        existing_image.embedding_status = "ignored-for-test"

    product = db_session.scalar(select(Product).limit(1))
    image_path = tmp_path / "product.jpg"
    Image.new("RGB", (8, 8), color=(220, 120, 120)).save(image_path)
    image = ProductImage(
        image_code=make_code("img", "test-index-image"),
        product_code=product.product_code,
        kind="front",
        local_path=str(image_path),
        embedding_status="pending",
    )
    db_session.add(image)
    db_session.flush()

    def fake_embed_image(path: Path, *, enabled: bool, model_name: str):
        assert path == image_path
        assert enabled is True
        return ImageVector(model_name=model_name, vector=[1.0, 0.0, 0.0])

    monkeypatch.setattr("app.services.image_index.embed_image", fake_embed_image)

    assert index_images(db_session, limit=10) >= 1
    db_session.flush()

    embedding = db_session.scalar(
        select(ImageEmbedding).where(ImageEmbedding.image_code == image.image_code)
    )
    assert embedding is not None
    assert embedding.vector == [1.0, 0.0, 0.0]
    assert image.embedding_status == "indexed"


def test_image_index_status_and_pause_controls(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_dir", tmp_path)

    set_image_index_paused(True)
    status = image_index_status(db_session)

    assert status["paused"] is True
    assert status["counts"]["total"] >= 1
    assert Path(status["pause_path"]).exists()

    set_image_index_paused(False)
    assert image_index_status(db_session)["paused"] is False


def test_resumable_image_index_honors_pause_before_work(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_dir", tmp_path)

    set_image_index_paused(True)
    result = run_resumable_image_index(db_session, batch_size=2)

    assert result.state == "paused"
    assert result.attempted == 0
    assert (tmp_path / "image-index-progress.json").exists()

    set_image_index_paused(False)


def test_resumable_image_index_retries_failed_images_once_per_run(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_optional_ml", True)
    monkeypatch.setattr(settings, "storage_dir", tmp_path)

    for existing_image in db_session.scalars(select(ProductImage)).all():
        existing_image.embedding_status = "ignored-for-test"

    product = db_session.scalar(select(Product).limit(1))
    image = ProductImage(
        image_code=make_code("img", "retry-failed-once"),
        product_code=product.product_code,
        kind="front",
        url="https://images.openbeautyfacts.org/missing.jpg",
        embedding_status="download-failed",
    )
    db_session.add(image)
    db_session.flush()

    attempts: list[str] = []

    def fake_resolve_image_target(target):
        attempts.append(target.image_code)
        return ImageDownloadResult(image_code=target.image_code, path=None, url=target.url)

    monkeypatch.setattr("app.services.image_index._resolve_image_target", fake_resolve_image_target)

    result = run_resumable_image_index(db_session, batch_size=1, retry_failed=True)

    assert result.state == "complete"
    assert result.attempted == 1
    assert result.failed == 1
    assert attempts == [image.image_code]
    assert image.embedding_status == "download-failed"


def test_scan_uses_image_embedding_candidates(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_optional_ml", True)
    monkeypatch.setattr(settings, "image_embedding_model", "test-clip")

    product = db_session.scalar(select(Product).limit(1))
    image_code = "img_test_scan_hit"
    db_session.add(
        ProductImage(
            image_code=image_code,
            product_code=product.product_code,
            kind="front",
        )
    )
    db_session.flush()
    db_session.add(
        ImageEmbedding(
            embedding_code=make_code("emb", "scan-image-hit"),
            image_code=image_code,
            product_code=product.product_code,
            model_name="test-clip",
            dimensions=3,
            vector=[1.0, 0.0, 0.0],
        )
    )
    db_session.flush()

    upload_path = tmp_path / "unknown-product.jpg"
    Image.new("RGB", (8, 8), color=(220, 120, 120)).save(upload_path)

    monkeypatch.setattr("app.services.scanner.extract_barcode", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.scanner.extract_ocr_text", lambda *args, **kwargs: "unmatched text")
    monkeypatch.setattr(
        "app.services.scanner.embed_image",
        lambda *args, **kwargs: ImageVector(model_name="test-clip", vector=[1.0, 0.0, 0.0]),
    )

    scan = process_scan(db_session, image_path=upload_path, upload_filename=upload_path.name)
    candidates = db_session.scalars(
        select(ScanCandidate)
        .where(ScanCandidate.scan_code == scan.scan_code)
        .order_by(ScanCandidate.rank)
    ).all()

    assert scan.status == "completed"
    assert scan.matched_product_code == product.product_code
    assert candidates
    assert "CLIP image similarity" in candidates[0].match_reasons
