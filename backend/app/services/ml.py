from __future__ import annotations

import math
import re
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)


BARCODE_RE = re.compile(r"(\d{8,14})")


@dataclass(frozen=True)
class ImageVector:
    model_name: str
    vector: list[float]

    @property
    def dimensions(self) -> int:
        return len(self.vector)


def barcode_from_filename(path: Path) -> str | None:
    match = BARCODE_RE.search(path.name)
    return match.group(1) if match else None


def extract_barcode(image_path: Path, *, enabled: bool) -> str | None:
    if not enabled:
        return barcode_from_filename(image_path)

    try:
        import cv2
        import zxingcpp
    except ImportError:
        logger.debug("Barcode ML dependencies are not installed; using filename fallback")
        return barcode_from_filename(image_path)

    try:
        image = cv2.imread(str(image_path))
        results = zxingcpp.read_barcodes(image if image is not None else str(image_path))
        for result in results or []:
            value = str(getattr(result, "text", "")).strip()
            if value:
                return value
    except Exception:
        logger.exception("Barcode extraction failed for %s; using filename fallback", image_path)
        return barcode_from_filename(image_path)
    return barcode_from_filename(image_path)


def fallback_ocr_text(image_path: Path) -> str:
    return image_path.stem.replace("-", " ").replace("_", " ").strip()


@lru_cache(maxsize=4)
def _paddle_ocr(language: str) -> Any:
    from paddleocr import PaddleOCR

    try:
        return PaddleOCR(use_angle_cls=True, lang=language, show_log=False)
    except TypeError:
        return PaddleOCR(lang=language)


def _collect_ocr_text(value: Any) -> list[str]:
    texts: list[str] = []
    if value is None:
        return texts
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, dict):
        for key in ("rec_texts", "texts", "text"):
            direct = value.get(key)
            if isinstance(direct, str):
                texts.extend(_collect_ocr_text(direct))
            elif isinstance(direct, Iterable):
                for item in direct:
                    texts.extend(_collect_ocr_text(item))
        for nested in value.values():
            texts.extend(_collect_ocr_text(nested))
        return texts
    if isinstance(value, tuple | list):
        for item in value:
            texts.extend(_collect_ocr_text(item))
    return texts


def extract_ocr_text(image_path: Path, *, enabled: bool, language: str) -> str:
    fallback = fallback_ocr_text(image_path)
    if not enabled:
        return fallback

    try:
        ocr = _paddle_ocr(language)
    except Exception:
        logger.exception("PaddleOCR initialization failed for language %s; using filename fallback", language)
        return fallback

    try:
        if hasattr(ocr, "ocr"):
            try:
                result = ocr.ocr(str(image_path), cls=True)
            except TypeError:
                result = ocr.ocr(str(image_path))
        else:
            result = ocr.predict(str(image_path))
    except Exception:
        logger.exception("OCR extraction failed for %s; using filename fallback", image_path)
        return fallback

    texts = []
    seen = set()
    for text in _collect_ocr_text(result):
        cleaned = re.sub(r"\s+", " ", text).strip()
        if cleaned and cleaned not in seen:
            texts.append(cleaned)
            seen.add(cleaned)
    return "\n".join(texts) or fallback


@lru_cache(maxsize=2)
def _sentence_transformer(model_name: str) -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def _as_float_list(value: Any) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    if hasattr(value, "tolist"):
        value = value.tolist()
    if value and isinstance(value, list) and isinstance(value[0], list):
        value = value[0]
    return [float(item) for item in value]


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(item * item for item in vector))
    if norm == 0:
        return vector
    return [item / norm for item in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=False)) / (left_norm * right_norm)


def embed_image(image_path: Path, *, enabled: bool, model_name: str) -> ImageVector | None:
    if not enabled:
        return None

    try:
        model = _sentence_transformer(model_name)
    except Exception:
        logger.exception("Image embedding model %s failed to load", model_name)
        return None

    try:
        with Image.open(image_path) as image:
            rgb_image = image.convert("RGB")
            try:
                encoded = model.encode(
                    rgb_image,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
            except TypeError:
                encoded = model.encode(rgb_image)
        vector = normalize_vector(_as_float_list(encoded))
    except Exception:
        logger.exception("Image embedding failed for %s", image_path)
        return None

    return ImageVector(model_name=model_name, vector=vector)
