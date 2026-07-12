"""Data access for the suggestion / autocomplete / instant-mix endpoints.

The endpoints build request-shaped visibility ``conditions`` (from the caller's
permissions/age) and hand them here; this service owns the actual queries so the
router carries endpoints, not raw ``select(...)`` statements.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, desc, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.genre import Genre
from pyrate.models.list import List, ListItem, ListType
from pyrate.models.media import MediaItem, media_genre_table
from pyrate.models.person import MediaCast, Person
from pyrate.models.viewing_history import ViewingHistory

# Eager-load the relationships every summary needs.
_ITEM_OPTIONS = (selectinload(MediaItem.genres), selectinload(MediaItem.platforms))


class SuggestionService:
    """Read queries backing the suggestion / autocomplete endpoints."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def seed_genre_ids(self, user_guid: uuid.UUID) -> list[int]:
        """Genre ids from the user's favorites and watch history."""
        favorite_genres = (
            select(media_genre_table.c.genre_id)
            .join(ListItem, ListItem.item_guid == media_genre_table.c.media_item_guid)
            .join(List, List.guid == ListItem.list_guid)
            .where(
                List.list_type == ListType.FAVORITES,
                List.owner_guid == user_guid,
            )
        )
        watched_genres = (
            select(media_genre_table.c.genre_id)
            .join(
                ViewingHistory,
                ViewingHistory.media_item_guid == media_genre_table.c.media_item_guid,
            )
            .where(ViewingHistory.user_guid == user_guid)
        )
        result = await self.db.execute(favorite_genres.union(watched_genres))
        return [genre_id for (genre_id,) in result.all()]

    async def seed_item_guids(self, user_guid: uuid.UUID) -> set[uuid.UUID]:
        """Item guids from the user's favorites and watch history."""
        favorite_items = (
            select(ListItem.item_guid)
            .join(List, List.guid == ListItem.list_guid)
            .where(
                List.list_type == ListType.FAVORITES,
                List.owner_guid == user_guid,
            )
        )
        watched_items = select(ViewingHistory.media_item_guid).where(
            ViewingHistory.user_guid == user_guid
        )
        result = await self.db.execute(favorite_items.union(watched_items))
        return {item_guid for (item_guid,) in result.all()}

    async def search_media(
        self, conditions: Sequence[Any], pattern: str, limit: int
    ) -> list[MediaItem]:
        """Visible media whose title/original title/description matches ``pattern``."""
        result = await self.db.execute(
            select(MediaItem)
            .options(*_ITEM_OPTIONS)
            .where(
                *conditions,
                or_(
                    MediaItem.title.ilike(pattern),
                    MediaItem.original_title.ilike(pattern),
                    MediaItem.description.ilike(pattern),
                ),
            )
            .order_by(MediaItem.title.asc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def search_genres(
        self, conditions: Sequence[Any], pattern: str, limit: int
    ) -> list[tuple[str, int]]:
        """(name, count) for genres matching ``pattern`` on visible items."""
        result = await self.db.execute(
            select(Genre.name, func.count(MediaItem.guid))
            .join(media_genre_table, media_genre_table.c.genre_id == Genre.id)
            .join(MediaItem, MediaItem.guid == media_genre_table.c.media_item_guid)
            .where(*conditions, Genre.name.ilike(pattern))
            .group_by(Genre.name)
            .order_by(Genre.name.asc())
            .limit(limit)
        )
        return list(result.all())

    async def search_people(
        self, conditions: Sequence[Any], pattern: str, limit: int
    ) -> list[tuple[str, uuid.UUID, int]]:
        """(name, guid, count) for people matching ``pattern`` on visible items."""
        result = await self.db.execute(
            select(Person.name, Person.guid, func.count(MediaItem.guid))
            .join(MediaCast, MediaCast.person_guid == Person.guid)
            .join(MediaItem, MediaItem.guid == MediaCast.media_item_guid)
            .where(*conditions, Person.name.ilike(pattern))
            .group_by(Person.guid, Person.name)
            .order_by(Person.name.asc())
            .limit(limit)
        )
        return list(result.all())

    async def facet_years(
        self, conditions: Sequence[Any], limit: int = 200
    ) -> list[int]:
        """Distinct release years among visible items (for the year facet).

        Bounded by the number of *distinct* years (tens, not the whole
        library), computed in SQL rather than by materialising rows.
        """
        year_expr = extract("year", MediaItem.release_date)
        result = await self.db.execute(
            select(year_expr)
            .where(*conditions, MediaItem.release_date.is_not(None))
            .distinct()
            .limit(limit)
        )
        years: list[int] = []
        for (value,) in result.all():
            if value is None:
                continue
            try:
                years.append(int(value))
            except (TypeError, ValueError):
                continue
        return years

    async def scan_studio_facets(
        self, conditions: Sequence[Any], limit: int = 500
    ) -> list[Any]:
        """A bounded slice of visible items' ``extra_data`` blobs (studio facet).

        Selects only the ``extra_data`` column instead of hydrating full ORM
        rows, so the studio-suggestion scan stays cheap on the autocomplete
        hot path.
        """
        result = await self.db.execute(
            select(MediaItem.extra_data)
            .where(*conditions)
            .order_by(MediaItem.title.asc())
            .limit(limit)
        )
        return [row[0] for row in result.all()]

    async def recommended(
        self, conditions: Sequence[Any], seed_genre_ids: Sequence[int], limit: int
    ) -> list[MediaItem]:
        """Suggestions ordered newest-first, optionally filtered to seed genres."""
        query = (
            select(MediaItem)
            .options(*_ITEM_OPTIONS)
            .where(*conditions)
            .order_by(
                desc(MediaItem.release_date).nulls_last(), desc(MediaItem.created_at)
            )
            .limit(limit)
        )
        if seed_genre_ids:
            query = query.where(MediaItem.genres.any(Genre.id.in_(seed_genre_ids)))
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def latest(self, conditions: Sequence[Any], limit: int) -> list[MediaItem]:
        """Latest visible items (created-desc, then release-date-desc)."""
        result = await self.db.execute(
            select(MediaItem)
            .options(*_ITEM_OPTIONS)
            .where(*conditions)
            .order_by(
                desc(MediaItem.created_at), desc(MediaItem.release_date).nulls_last()
            )
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def get_item(self, item_guid: uuid.UUID) -> MediaItem | None:
        """A single media item with genres/platforms eager-loaded."""
        result = await self.db.execute(
            select(MediaItem).options(*_ITEM_OPTIONS).where(MediaItem.guid == item_guid)
        )
        return result.scalars().unique().one_or_none()

    async def related(
        self, conditions: Sequence[Any], limit: int
    ) -> list[MediaItem]:
        """Items related to an instant-mix seed (sequence-then-release ordering)."""
        result = await self.db.execute(
            select(MediaItem)
            .options(*_ITEM_OPTIONS)
            .where(and_(*conditions))
            .order_by(
                MediaItem.sequence_number.asc().nulls_last(),
                desc(MediaItem.release_date).nulls_last(),
            )
            .limit(limit)
        )
        return list(result.scalars().unique().all())
