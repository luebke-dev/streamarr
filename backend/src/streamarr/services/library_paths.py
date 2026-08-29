"""Canonical parsing of per-library roots and processing options."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_library_settings(raw_settings: object) -> dict[str, Any]:
    if not raw_settings:
        return {}
    if isinstance(raw_settings, dict):
        return dict(raw_settings)
    if isinstance(raw_settings, str):
        try:
            parsed = json.loads(raw_settings)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def library_root_paths(library: object) -> list[str]:
    """Return normalized, de-duplicated physical roots for a library."""
    settings = parse_library_settings(getattr(library, "settings", None))
    candidates = [str(getattr(library, "path", ""))]
    media_folders = settings.get("media_folders")
    if isinstance(media_folders, list):
        candidates.extend(str(path) for path in media_folders if path)

    roots: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = str(Path(candidate).expanduser().resolve(strict=False))
        if normalized in seen:
            continue
        seen.add(normalized)
        roots.append(normalized)
    return roots


def library_processing_options(library: object) -> dict[str, Any]:
    settings = parse_library_settings(getattr(library, "settings", None))
    options = settings.get("options")
    return dict(options) if isinstance(options, dict) else {}
