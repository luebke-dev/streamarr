"""
Indexer Service

This service handles all indexer-related operations (Newznab indexers for torrents/usenet)
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamarr.models.indexer import Indexer, IndexerCategory
from streamarr.schemas.indexer import (
    IndexerCategoryCreate,
    IndexerCreate,
    IndexerRead,
    IndexerUpdate,
)


class IndexerService:
    """Service for managing content indexers"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _to_read(db_indexer: Indexer) -> IndexerRead:
        """Materialise an Indexer row as an ``IndexerRead`` without exposing the secret."""
        return IndexerRead(
            guid=db_indexer.guid,
            created_at=db_indexer.created_at,
            updated_at=db_indexer.updated_at,
            host=db_indexer.host,
            ssl=db_indexer.ssl,
            verify_ssl=db_indexer.verify_ssl,
            type=db_indexer.type,
            label=db_indexer.label,
            enabled=db_indexer.enabled,
            supports_rss=db_indexer.supports_rss,
            rss_enabled=db_indexer.rss_enabled,
            priority=db_indexer.priority,
            last_rss_sync_at=db_indexer.last_rss_sync_at,
            categories=list(db_indexer.categories),
            api_key_configured=bool(db_indexer.api_key),
        )

    async def get_all(self) -> list[IndexerRead]:
        """Get all configured indexers with their categories"""
        result = await self.db.execute(
            select(Indexer).options(selectinload(Indexer.categories))
        )
        return [self._to_read(row) for row in result.scalars().all()]

    async def get_model_by_id(self, indexer_id: str | uuid.UUID) -> Indexer | None:
        """Return the raw SA ``Indexer`` (including api_key) for internal use."""
        if isinstance(indexer_id, str):
            try:
                indexer_id = uuid.UUID(indexer_id)
            except (ValueError, AttributeError):
                return None
        result = await self.db.execute(
            select(Indexer)
            .where(Indexer.guid == indexer_id)
            .options(selectinload(Indexer.categories))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, indexer_id: str | uuid.UUID) -> IndexerRead | None:
        """Get an indexer by its GUID (redacted secret)."""
        db_indexer = await self.get_model_by_id(indexer_id)
        return self._to_read(db_indexer) if db_indexer else None

    async def create(self, indexer: IndexerCreate) -> IndexerRead:
        """Create a new indexer with optional categories"""
        categories_data = indexer.categories
        indexer_data = indexer.model_dump(exclude={"categories"})
        db_indexer = Indexer(**indexer_data)
        self.db.add(db_indexer)
        await self.db.flush()  # get db_indexer.guid

        for cat in categories_data:
            db_cat = IndexerCategory(**cat.model_dump(), indexer_guid=db_indexer.guid)
            self.db.add(db_cat)

        await self.db.commit()
        await self.db.refresh(db_indexer)
        # Reload with categories
        result = await self.db.execute(
            select(Indexer)
            .where(Indexer.guid == db_indexer.guid)
            .options(selectinload(Indexer.categories))
        )
        return self._to_read(result.scalar_one())

    async def update(
        self, db_indexer: Indexer, indexer_in: IndexerUpdate
    ) -> IndexerRead:
        """Update an existing indexer and replace its categories"""
        categories_data = indexer_in.categories
        indexer_data = indexer_in.model_dump(
            exclude={"categories", "api_key"}, exclude_unset=True
        )
        for key, value in indexer_data.items():
            setattr(db_indexer, key, value)

        # Only replace the api_key when the caller sent a non-empty value.
        # An unchanged admin form posts "" (or omits the field entirely),
        # in which case the existing secret is preserved.
        if indexer_in.api_key:
            db_indexer.api_key = indexer_in.api_key

        # Replace categories
        for existing_cat in list(db_indexer.categories):
            await self.db.delete(existing_cat)
        await self.db.flush()

        for cat in categories_data:
            db_cat = IndexerCategory(**cat.model_dump(), indexer_guid=db_indexer.guid)
            self.db.add(db_cat)

        await self.db.commit()
        result = await self.db.execute(
            select(Indexer)
            .where(Indexer.guid == db_indexer.guid)
            .options(selectinload(Indexer.categories))
        )
        return self._to_read(result.scalar_one())

    async def delete(self, indexer: Indexer) -> None:
        """Delete an indexer"""
        await self.db.delete(indexer)
        await self.db.commit()

    async def set_categories(
        self, indexer: Indexer, categories: list[IndexerCategoryCreate]
    ) -> list[IndexerCategory]:
        """Replace all categories for an indexer"""
        for existing_cat in list(indexer.categories):
            await self.db.delete(existing_cat)
        await self.db.flush()

        new_cats = []
        for cat in categories:
            db_cat = IndexerCategory(**cat.model_dump(), indexer_guid=indexer.guid)
            self.db.add(db_cat)
            new_cats.append(db_cat)

        await self.db.commit()
        return new_cats
