"""Render-context helpers.

A "render context" is a flat dict that condition expressions and
text-element placeholders both read from. Building it once per item
means subsequent template evaluation never has to walk the ORM graph.
"""

from __future__ import annotations

from typing import Any

from pyrate.models.media import MediaItem


def resolution_label(height: int | None) -> str | None:
    """Map a pixel height to a coarse label ("4K", "1080p", …)."""
    if not height:
        return None
    if height >= 2160:
        return "4K"
    if height >= 1440:
        return "1440p"
    if height >= 1080:
        return "1080p"
    if height >= 720:
        return "720p"
    if height >= 480:
        return "480p"
    return "SD"


def _media_type_value(item: MediaItem) -> str:
    raw = getattr(item, "media_type", None)
    return getattr(raw, "value", str(raw)) if raw is not None else ""


def _availability_value(item: MediaItem) -> str:
    raw = getattr(item, "availability_status", None)
    return getattr(raw, "value", str(raw)) if raw is not None else ""


def _max_height(item: MediaItem) -> int:
    files = getattr(item, "files", None) or []
    heights = [getattr(f, "height", None) or 0 for f in files]
    return max(heights, default=0)


def _max_width(item: MediaItem) -> int:
    files = getattr(item, "files", None) or []
    widths = [getattr(f, "width", None) or 0 for f in files]
    return max(widths, default=0)


def _file_attribute_any(item: MediaItem, attr: str) -> set[str]:
    files = getattr(item, "files", None) or []
    out: set[str] = set()
    for f in files:
        value = getattr(f, attr, None)
        if isinstance(value, str) and value:
            out.add(value.lower())
    return out


def build_render_context(item: MediaItem) -> dict[str, Any]:
    """Build the per-item context the renderer & condition DSL read.

    Keys are dotted strings — match what conditions store in their JSON.
    Values are primitives or simple containers so the DSL stays trivial.
    """
    max_h = _max_height(item)
    max_w = _max_width(item)
    return {
        # Identity / classification
        "media_type": _media_type_value(item),
        "min_age": getattr(item, "min_age", None),
        "availability": _availability_value(item),
        # Release info
        "year": (
            item.release_date.year
            if getattr(item, "release_date", None) is not None
            else None
        ),
        "title": getattr(item, "title", "") or "",
        # Genres (lowercased for case-insensitive matches)
        "genres": [g.name.lower() for g in (getattr(item, "genres", None) or [])],
        # Resolution & codecs read from MediaFile rows
        "resolution.height": max_h,
        "resolution.width": max_w,
        "resolution.label": resolution_label(max_h) or "",
        "codecs.video": list(_file_attribute_any(item, "codec")),
        "codecs.audio": list(_file_attribute_any(item, "audio_codec")),
        "has_files": bool(getattr(item, "files", None) or []),
    }
