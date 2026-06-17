from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any


def stable_hash(value: Any, length: int = 14) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def make_code(prefix: str, seed: Any | None = None) -> str:
    if seed is None:
        token = uuid.uuid4().hex[:14]
    else:
        token = stable_hash(seed)
    return f"{prefix}_{token}"


def content_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
