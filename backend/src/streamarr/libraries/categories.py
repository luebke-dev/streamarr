"""Canonical media-type -> parent-library-category mapping.

Single source of truth for how the fine-grained ``MediaType`` values
(SEASONS/EPISODES, ARTISTS/ALBUMS/SONGS, AUDIOBOOK_CHAPTERS, ...) roll up into
their top-level library category (MOVIES / SHOWS / MUSIC / BOOKS / GAMES /
PHOTOS). The per-subsystem variants (quality-profile plugin keys, permission
library names, ...) are derived from this map so adding a new subtype only
requires editing one place.
"""

from __future__ import annotations

from typing import Any

# media_type value -> parent library category (uppercase, plugin-key style).
MEDIA_TYPE_TO_CATEGORY: dict[str, str] = {
    "MOVIES": "MOVIES",
    "SHOWS": "SHOWS",
    "SEASONS": "SHOWS",
    "EPISODES": "SHOWS",
    "MUSIC": "MUSIC",
    "ARTISTS": "MUSIC",
    "ALBUMS": "MUSIC",
    "SONGS": "MUSIC",
    "BOOKS": "BOOKS",
    "AUDIOBOOKS": "BOOKS",
    "AUDIOBOOK_CHAPTERS": "BOOKS",
    "GAMES": "GAMES",
    "PHOTOS": "PHOTOS",
    "HOME_VIDEOS": "PHOTOS",
}

# Downloadable categories that have a library plugin + quality profile.
DOWNLOADABLE_CATEGORIES: tuple[str, ...] = (
    "MOVIES",
    "SHOWS",
    "MUSIC",
    "BOOKS",
    "GAMES",
)


def media_type_name(media_type: Any) -> str:
    """Normalize a MediaType enum or string to its uppercase value name."""
    return str(getattr(media_type, "value", media_type) or "").upper()


def category_for(media_type: Any) -> str | None:
    """Parent library category for a media type, or None if unknown."""
    return MEDIA_TYPE_TO_CATEGORY.get(media_type_name(media_type))
