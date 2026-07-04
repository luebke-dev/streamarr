"""Service for discoverable item filter values (genres, platforms, years, …).

The filter endpoint builds the request-shaped ``conditions`` (visible media
types + parental age gate) and this service runs the per-facet aggregate
queries against them, so the router carries no raw SQL.
"""

import json
import logging

from sqlalchemy import distinct, extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.genre import Genre
from pyrate.models.media import (
    MediaFile,
    MediaItem,
    media_genre_table,
    media_platform_table,
)
from pyrate.models.person import MediaCast, Person
from pyrate.models.platform import Platform

logger = logging.getLogger(__name__)


def _extract_studio_names(extra_data: str | dict | None) -> set[str]:
    """Studio/production-company names carried in a media item's extra_data."""
    if not extra_data:
        return set()
    if isinstance(extra_data, dict):
        data = extra_data
    else:
        try:
            data = json.loads(extra_data)
        except (TypeError, ValueError):
            return set()
    if not isinstance(data, dict):
        return set()

    raw_values = []
    for key in ("studio", "studios", "production_company", "production_companies"):
        value = data.get(key)
        if value:
            raw_values.append(value)

    names: set[str] = set()
    for value in raw_values:
        if isinstance(value, str):
            names.update(part.strip() for part in value.split(",") if part.strip())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    names.add(item.strip())
                elif isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name.strip():
                        names.add(name.strip())
    return names


class FilterService:
    """Runs the per-facet filter-value queries for a set of where-conditions."""

    def __init__(self, db: AsyncSession):
        """Initialize the filter service.

        Args:
            db: Database session
        """
        self.db = db

    async def genre_options(self, conditions: list) -> list[tuple[int, str]]:
        """(id, name) of genres present on any item matching ``conditions``."""
        rows = await self.db.execute(
            select(Genre.id, Genre.name)
            .join(media_genre_table, Genre.id == media_genre_table.c.genre_id)
            .join(MediaItem, MediaItem.guid == media_genre_table.c.media_item_guid)
            .where(*conditions)
            .group_by(Genre.id, Genre.name)
            .order_by(Genre.name)
        )
        return [(row.id, row.name) for row in rows.all()]

    async def platform_options(self, conditions: list) -> list[tuple[int, str]]:
        """(id, name) of platforms present on any matching item."""
        rows = await self.db.execute(
            select(Platform.id, Platform.name)
            .join(media_platform_table, Platform.id == media_platform_table.c.platform_id)
            .join(MediaItem, MediaItem.guid == media_platform_table.c.media_item_guid)
            .where(*conditions)
            .group_by(Platform.id, Platform.name)
            .order_by(Platform.name)
        )
        return [(row.id, row.name) for row in rows.all()]

    async def person_options(self, conditions: list) -> list[tuple[str, str]]:
        """(guid, name) of cast/crew on any matching item."""
        rows = await self.db.execute(
            select(Person.guid, Person.name)
            .join(MediaCast, MediaCast.person_guid == Person.guid)
            .join(MediaItem, MediaItem.guid == MediaCast.media_item_guid)
            .where(*conditions)
            .group_by(Person.guid, Person.name)
            .order_by(Person.name)
        )
        return [(str(row.guid), row.name) for row in rows.all()]

    async def years(self, conditions: list) -> list[int]:
        """Distinct release years across matching items, newest first."""
        rows = await self.db.execute(
            select(distinct(extract("year", MediaItem.release_date)))
            .where(*conditions, MediaItem.release_date.isnot(None))
            .order_by(extract("year", MediaItem.release_date).desc())
        )
        return [int(row[0]) for row in rows.all() if row[0] is not None]

    async def content_ratings(self, conditions: list) -> list[str]:
        """Distinct non-empty content ratings across matching items."""
        rows = await self.db.execute(
            select(distinct(MediaItem.content_rating))
            .where(
                *conditions,
                MediaItem.content_rating.isnot(None),
                MediaItem.content_rating != "",
            )
            .order_by(MediaItem.content_rating.asc())
        )
        return [row[0] for row in rows.all() if row[0]]

    async def containers(self, conditions: list) -> list[str]:
        """Distinct non-empty file container formats across matching items."""
        rows = await self.db.execute(
            select(distinct(MediaFile.format))
            .join(MediaItem, MediaItem.guid == MediaFile.media_item_guid)
            .where(*conditions, MediaFile.format.isnot(None), MediaFile.format != "")
            .order_by(MediaFile.format.asc())
        )
        return [row[0] for row in rows.all() if row[0]]

    async def studios(self, conditions: list) -> list[str]:
        """Studio/production names parsed from matching items' extra_data."""
        rows = await self.db.execute(
            select(MediaItem.extra_data).where(
                *conditions, MediaItem.extra_data.isnot(None)
            )
        )
        return sorted(
            {
                studio_name
                for row in rows.all()
                for studio_name in _extract_studio_names(row[0])
            },
            key=str.casefold,
        )
