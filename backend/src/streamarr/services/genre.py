"""Genre service for managing genres."""

import hashlib
import json
import logging
import uuid
from collections import defaultdict
from datetime import date, datetime

logger = logging.getLogger(__name__)

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.genre import Genre
from streamarr.schemas.genre import GenreCreate, GenreRead, GenreUpdate

# ``get_genres_with_items`` powers the homepage browse strip and is
# expensive (window function + ~2k rows per call). Cache it in Redis with
# a short TTL — the underlying data only changes when imports run, and
# stale-by-up-to-120s is acceptable for a "browse by genre" view.
_GENRE_CACHE_TTL_SECONDS = 120
_GENRE_CACHE_PREFIX = "streamarr:genre_browse:"


def _json_default(obj):
    if isinstance(obj, (uuid.UUID,)):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Cannot serialize {type(obj)!r}")


def _genre_cache_key(
    *,
    media_type: str | None,
    max_items_per_genre: int,
    disabled_media_types: set[str] | None,
    allowed_media_types: list | None,
    max_age: int | None,
) -> str:
    allowed_values = [
        item.value if hasattr(item, "value") else str(item)
        for item in allowed_media_types or []
    ]
    payload = json.dumps(
        {
            "mt": media_type,
            "max": max_items_per_genre,
            "dis": sorted(disabled_media_types) if disabled_media_types else [],
            "allow": sorted(allowed_values),
            "age": max_age,
        },
        sort_keys=True,
    )
    digest = hashlib.sha1(payload.encode()).hexdigest()[:16]
    return f"{_GENRE_CACHE_PREFIX}{digest}"


class GenreService:
    """Service for managing genres."""

    def __init__(self, db: AsyncSession):
        """Initialize the genre service.

        Args:
            db: Database session
        """
        self.db = db

    async def get_by_id(self, genre_id: int) -> GenreRead | None:
        """Get a genre by ID.

        Args:
            genre_id: The genre ID

        Returns:
            The genre if found, None otherwise
        """
        result = await self.db.execute(select(Genre).where(Genre.id == genre_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> GenreRead | None:
        """Get a genre by name.

        Args:
            name: The genre name

        Returns:
            The genre if found, None otherwise
        """
        result = await self.db.execute(select(Genre).where(Genre.name == name))
        return result.scalar_one_or_none()

    async def get_all(self) -> list[GenreRead]:
        """Get all genres ordered by name.

        Returns:
            List of all genres
        """
        result = await self.db.execute(select(Genre).order_by(Genre.name))
        return list(result.scalars().all())

    async def get_all_with_items_of_type(self, media_type) -> list[GenreRead]:
        """Get only genres that have at least one media item of the given type."""
        from streamarr.models.media import MediaItem, media_genre_table

        query = (
            select(Genre)
            .join(media_genre_table, media_genre_table.c.genre_id == Genre.id)
            .join(MediaItem, MediaItem.guid == media_genre_table.c.media_item_guid)
            .where(MediaItem.media_type == media_type, MediaItem.parent_guid.is_(None))
            .group_by(Genre.id)
            .order_by(Genre.name)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, genre: GenreCreate) -> GenreRead:
        """Create a new genre.

        Args:
            genre: The genre data

        Returns:
            The created genre
        """
        db_genre = Genre(**genre.model_dump())
        self.db.add(db_genre)
        await self.db.commit()
        await self.db.refresh(db_genre)
        logger.info("Created genre %d (%s)", db_genre.id, db_genre.name)
        return db_genre

    async def get_or_create(self, genre_id: int, name: str) -> GenreRead:
        """Get an existing genre or create it if it doesn't exist.

        Uses INSERT ... ON CONFLICT DO NOTHING to handle race conditions
        when multiple requests try to create the same genre simultaneously.

        Args:
            genre_id: The genre ID
            name: The genre name

        Returns:
            The existing or newly created genre
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        # Try to find existing genre
        existing_genre = await self.get_by_id(genre_id)
        if existing_genre:
            logger.debug("Genre %d (%s) already exists", genre_id, name)
            return existing_genre

        # Use INSERT ... ON CONFLICT DO NOTHING to handle race conditions
        stmt = (
            pg_insert(Genre)
            .values(id=genre_id, name=name)
            .on_conflict_do_nothing(index_elements=["name"])
        )
        await self.db.execute(stmt)
        await self.db.commit()

        # Fetch the genre (might have been created by another request with different ID)
        result = await self.db.execute(select(Genre).where(Genre.name == name))
        genre = result.scalar_one_or_none()
        logger.debug("get_or_create genre %d (%s)", genre_id, name)

        return genre

    async def update(self, db_genre: Genre, genre_in: GenreUpdate) -> GenreRead:
        """Update a genre.

        Args:
            db_genre: The existing genre model
            genre_in: The update data

        Returns:
            The updated genre
        """
        genre_data = genre_in.model_dump(exclude_unset=True)
        for key, value in genre_data.items():
            setattr(db_genre, key, value)
        self.db.add(db_genre)
        await self.db.commit()
        await self.db.refresh(db_genre)
        return db_genre

    async def delete(self, genre: Genre) -> None:
        """Delete a genre.

        Args:
            genre: The genre to delete
        """
        logger.info("Deleted genre %d (%s)", genre.id, genre.name)
        await self.db.delete(genre)
        await self.db.commit()

    async def get_genres_with_items(
        self,
        media_type: str | None = None,
        max_items_per_genre: int = 10,
        library_guid=None,
        disabled_media_types: set[str] | None = None,
        allowed_media_types: list | None = None,
        max_age: int | None = None,
    ) -> dict[int, dict]:
        """Get all genres with their top N media items in a single query.

        Uses a ROW_NUMBER() window function to fetch the top N items per genre
        without issuing a separate query for each genre (avoids N+1). Result
        is cached in Redis for a short TTL — the homepage browse view tolerates
        ~2 minutes of staleness in exchange for skipping the 19ms scan/join.

        Args:
            media_type: Filter by media type (e.g. "MOVIES")
            max_items_per_genre: Maximum number of items to return per genre
            library_guid: Unused, kept for API compatibility
            disabled_media_types: Set of media types to exclude (disabled libraries)
            allowed_media_types: User-visible media types to include
            max_age: User parental-control maximum age

        Returns:
            Dict mapping genre_id to {"id": ..., "name": ..., "items": [...]}
        """
        cache_key = _genre_cache_key(
            media_type=media_type,
            max_items_per_genre=max_items_per_genre,
            disabled_media_types=disabled_media_types,
            allowed_media_types=allowed_media_types,
            max_age=max_age,
        )
        try:
            from streamarr.services.rate_limiter import _get_redis
            r = await _get_redis()
            cached = await r.get(cache_key)
            if cached:
                payload = json.loads(cached)
                # JSON keys come back as strings; the API contract is
                # ``dict[int, dict]`` so coerce.
                return {int(k): v for k, v in payload.items()}
        except Exception as e:
            logger.debug("Genre cache read failed: %s", e)

        from streamarr.models.media import MediaItem, media_genre_table

        # Build a subquery with ROW_NUMBER() to rank items within each genre
        row_num = func.row_number().over(
            partition_by=media_genre_table.c.genre_id,
            order_by=MediaItem.created_at.desc(),
        ).label("rn")

        subq = (
            select(
                Genre.id.label("genre_id"),
                Genre.name.label("genre_name"),
                MediaItem.guid,
                MediaItem.title,
                MediaItem.original_title,
                MediaItem.poster_path,
                MediaItem.backdrop_path,
                MediaItem.release_date,
                MediaItem.media_type,
                MediaItem.availability_status,
                MediaItem.content_rating,
                MediaItem.min_age,
                row_num,
            )
            .join(media_genre_table, media_genre_table.c.genre_id == Genre.id)
            .join(MediaItem, MediaItem.guid == media_genre_table.c.media_item_guid)
            .where(MediaItem.parent_guid.is_(None))  # top-level only
        )

        if media_type:
            subq = subq.where(MediaItem.media_type == media_type)

        if allowed_media_types is not None:
            if not allowed_media_types:
                return {}
            subq = subq.where(MediaItem.media_type.in_(allowed_media_types))

        if disabled_media_types:
            subq = subq.where(MediaItem.media_type.notin_(disabled_media_types))

        if max_age is not None:
            from streamarr.utils.age_rating import age_filter_clause
            subq = subq.where(age_filter_clause(max_age))

        subq = subq.subquery()

        # Filter to top N per genre
        query = (
            select(subq)
            .where(subq.c.rn <= max_items_per_genre)
            .order_by(subq.c.genre_name, subq.c.rn)
        )

        result = await self.db.execute(query)
        rows = result.all()

        # Group rows by genre
        genres: dict[int, dict] = {}
        for row in rows:
            genre_id = row.genre_id
            if genre_id not in genres:
                genres[genre_id] = {
                    "id": genre_id,
                    "name": row.genre_name,
                    "items": [],
                }
            genres[genre_id]["items"].append({
                "guid": row.guid,
                "title": row.title,
                "original_title": row.original_title,
                "poster_path": row.poster_path,
                "backdrop_path": row.backdrop_path,
                "release_date": row.release_date,
                "media_type": row.media_type,
                "availability_status": row.availability_status,
                "content_rating": row.content_rating,
                "min_age": row.min_age,
                "genres": [],
                "platforms": [],
            })

        try:
            from streamarr.services.rate_limiter import _get_redis
            r = await _get_redis()
            await r.set(
                cache_key,
                json.dumps(genres, default=_json_default),
                ex=_GENRE_CACHE_TTL_SECONDS,
            )
        except Exception as e:
            logger.debug("Genre cache write failed: %s", e)

        return genres

    async def get_items_for_genre_ids(
        self,
        genre_ids: list[int],
        media_type: str | None = None,
        max_items: int = 10,
        disabled_media_types: set[str] | None = None,
        allowed_media_types: list | None = None,
        max_age: int | None = None,
    ) -> dict[int, list[dict]]:
        """Get media items for a batch of genre IDs in a single query.

        Args:
            genre_ids: List of genre IDs to fetch items for
            media_type: Filter by media type
            max_items: Maximum items per genre
            disabled_media_types: Set of media types to exclude
            allowed_media_types: User-visible media types to include
            max_age: User parental-control maximum age

        Returns:
            Dict mapping genre_id to list of item dicts
        """
        from streamarr.models.media import MediaItem, media_genre_table

        if not genre_ids:
            return {}

        row_num = func.row_number().over(
            partition_by=media_genre_table.c.genre_id,
            order_by=MediaItem.created_at.desc(),
        ).label("rn")

        subq = (
            select(
                media_genre_table.c.genre_id.label("genre_id"),
                MediaItem.guid,
                MediaItem.title,
                MediaItem.original_title,
                MediaItem.poster_path,
                MediaItem.backdrop_path,
                MediaItem.release_date,
                MediaItem.media_type,
                MediaItem.availability_status,
                MediaItem.content_rating,
                MediaItem.min_age,
                row_num,
            )
            .join(MediaItem, MediaItem.guid == media_genre_table.c.media_item_guid)
            .where(
                media_genre_table.c.genre_id.in_(genre_ids),
                MediaItem.parent_guid.is_(None),
            )
        )

        if media_type:
            subq = subq.where(MediaItem.media_type == media_type)

        if allowed_media_types is not None:
            if not allowed_media_types:
                return {}
            subq = subq.where(MediaItem.media_type.in_(allowed_media_types))

        if disabled_media_types:
            subq = subq.where(MediaItem.media_type.notin_(disabled_media_types))

        if max_age is not None:
            from streamarr.utils.age_rating import age_filter_clause
            subq = subq.where(age_filter_clause(max_age))

        subq = subq.subquery()

        query = select(subq).where(subq.c.rn <= max_items)

        result = await self.db.execute(query)
        rows = result.all()

        grouped: dict[int, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row.genre_id].append({
                "guid": row.guid,
                "title": row.title,
                "original_title": row.original_title,
                "poster_path": row.poster_path,
                "backdrop_path": row.backdrop_path,
                "release_date": row.release_date,
                "media_type": row.media_type,
                "availability_status": row.availability_status,
                "content_rating": row.content_rating,
                "min_age": row.min_age,
                "genres": [],
                "platforms": [],
            })

        return dict(grouped)
