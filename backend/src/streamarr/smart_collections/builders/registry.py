"""Builder registry & factory.

``builder_type`` on a ``SmartCollectionRule`` maps to one of:
  * ``"library_filter"`` — local-only builder
  * a ``ListSource`` slug ("tmdb", "trakt", "imdb", "letterboxd",
    "mdblist", "mal", "anilist")
"""

from __future__ import annotations

from typing import Any

from streamarr.metadata.list_sources import (
    ListSourceError,
    build_source,
    list_source_slugs,
)
from streamarr.smart_collections.builders.base import SmartCollectionBuilder
from streamarr.smart_collections.builders.library_filter import (
    LIBRARY_FILTER_TYPE,
    LibraryFilterBuilder,
)
from streamarr.smart_collections.builders.list_source import ListSourceBuilder


def builder_types() -> list[str]:
    """Every accepted ``builder_type`` value."""
    return [LIBRARY_FILTER_TYPE, *list_source_slugs()]


def build_builder(
    builder_type: str, api_keys: dict[str, Any] | None = None
) -> SmartCollectionBuilder:
    """Construct a builder for ``builder_type``.

    Raises ``ListSourceError`` for unknown builder types or when a
    required API key is missing.
    """
    if builder_type == LIBRARY_FILTER_TYPE:
        return LibraryFilterBuilder()
    source = build_source(builder_type, api_keys or {})
    return ListSourceBuilder(source)


__all__ = ["build_builder", "builder_types", "ListSourceError"]
