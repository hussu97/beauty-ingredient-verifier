from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.normalization import normalize_text

PROFILE_OPTIONS_PATHS = (
    Path(__file__).resolve().parents[3] / "shared" / "profile-options.json",
    Path(__file__).resolve().parents[2] / "shared" / "profile-options.json",
)


def _profile_options_path() -> Path:
    for path in PROFILE_OPTIONS_PATHS:
        if path.exists():
            return path
    searched = ", ".join(str(path) for path in PROFILE_OPTIONS_PATHS)
    raise FileNotFoundError(f"profile options file not found; searched: {searched}")


@lru_cache(maxsize=1)
def load_profile_options() -> dict[str, Any]:
    return json.loads(_profile_options_path().read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def profile_alias_index() -> dict[str, dict[str, str]]:
    options = load_profile_options()
    index: dict[str, dict[str, str]] = {}
    for field, config in options.get("fields", {}).items():
        field_index: dict[str, str] = {}
        for option in config.get("options", []):
            canonical = normalize_text(option["value"])
            field_index[canonical] = canonical
            for alias in option.get("aliases", []):
                field_index[normalize_text(alias)] = canonical
        index[field] = field_index
    return index


def canonical_profile_value(field: str, value: str) -> str:
    normalized = normalize_text(value)
    return profile_alias_index().get(field, {}).get(normalized, normalized)


def canonical_profile_values(field: str, values: list[str] | None) -> set[str]:
    return {canonical_profile_value(field, value) for value in values or [] if normalize_text(value)}


def selectable_profile_values(field: str) -> set[str]:
    config = load_profile_options().get("fields", {}).get(field, {})
    return {normalize_text(option["value"]) for option in config.get("options", [])}


def all_selectable_profile_values() -> dict[str, set[str]]:
    return {
        field: selectable_profile_values(field)
        for field in load_profile_options().get("fields", {})
    }
