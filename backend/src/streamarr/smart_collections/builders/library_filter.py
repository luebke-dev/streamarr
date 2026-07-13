"""Library-filter builder: build collections from streamarr's local catalogue.

Used for decade/genre/runtime collections where there is no external
list to fetch — just "all movies released in the 1980s" or "all action
shows with a rating ≥ 7". The builder runs filters as SQL and emits one
``ExternalRef`` per matching item with ``provider="local"`` so the
resolver can short-circuit.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import asc, desc, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.metadata.list_sources import ExternalRef, ListSourceMediaType
from streamarr.models.media import MediaItem
from streamarr.smart_collections.builders.base import (
    BuildResult,
    SmartCollectionBuilder,
)


LIBRARY_FILTER_TYPE = "library_filter"


_MEDIA_TYPE_TOKENS = {
    ListSourceMediaType.MOVIE: "MOVIES",
    ListSourceMediaType.SHOW: "SHOWS",
}


_SORT_COLUMNS = {
    "release_date": MediaItem.release_date,
    "title": MediaItem.title,
    "created_at": MediaItem.created_at,
}


class LibraryFilterBuilder(SmartCollectionBuilder):
    """Build refs from MediaItem rows already in streamarr.

    Config keys (all optional unless noted):
      * ``year_min`` / ``year_max`` (int)
      * ``decade`` (int, e.g. 1980 → 1980-1989; overrides year_min/year_max)
      * ``min_age`` / ``max_age`` (int) — parental rating bands
      * ``availability`` (str: "available", "downloadable", "unknown")
      * ``sort`` (str: "release_date" | "title" | "created_at") — default
        "release_date"
      * ``sort_dir`` ("asc" | "desc") — default "desc"

    Genre filters are deliberately applied later by the filter stage so
    the same DSL works for both list-source and library builders.
    """

    type = LIBRARY_FILTER_TYPE

    async def fetch(
        self,
        config: dict[str, Any],
        *,
        media_type: ListSourceMediaType,
        limit: int | None,
        db: AsyncSession,
    ) -> BuildResult:
        token = _MEDIA_TYPE_TOKENS[media_type]
        stmt = select(MediaItem.guid, MediaItem.title, MediaItem.release_date).where(
            MediaItem.media_type == token
        )

        year_min = config.get("year_min")
        year_max = config.get("year_max")
        if decade := config.get("decade"):
            year_min = int(decade)
            year_max = int(decade) + 9

        if year_min is not None:
            stmt = stmt.where(
                extract("year", MediaItem.release_date) >= int(year_min)
            )
        if year_max is not None:
            stmt = stmt.where(
                extract("year", MediaItem.release_date) <= int(year_max)
            )
        if (min_age := config.get("min_age")) is not None:
            stmt = stmt.where(MediaItem.min_age >= int(min_age))
        if (max_age := config.get("max_age")) is not None:
            stmt = stmt.where(MediaItem.min_age <= int(max_age))
        if availability := config.get("availability"):
            stmt = stmt.where(MediaItem.availability_status == availability)

        sort_col = _SORT_COLUMNS.get(config.get("sort") or "release_date")
        if sort_col is None:
            sort_col = MediaItem.release_date
        direction = desc if (config.get("sort_dir") or "desc") == "desc" else asc
        # NULLs last is the friendly default for descending date sorts.
        stmt = stmt.order_by(direction(sort_col).nullslast())

        if limit:
            stmt = stmt.limit(int(limit))

        rows = (await db.execute(stmt)).all()
        refs = [
            ExternalRef(
                provider="local",
                external_id=str(guid),
                media_type=media_type,
                title=title,
                year=release_date.year if release_date else None,
            )
            for guid, title, release_date in rows
        ]
        return BuildResult(
            refs=refs,
            debug={
                "year_min": year_min,
                "year_max": year_max,
                "media_type": token,
                "matched_count": len(refs),
            },
        )
