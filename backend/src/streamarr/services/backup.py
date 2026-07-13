"""Backup service — the DB access behind the config-migration backup endpoints.

The backup/restore endpoints iterate generically over SQLAlchemy tables, so
these methods take a ``Table``/clause and wrap the raw ``execute`` calls that
used to live inline in ``api/v1/backups.py``. The imperative restore logic
(diffing, redaction, error accumulation) stays in the handler; only the
database round-trips live here.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import MediaFile, MediaItem
from streamarr.models.setting import Setting


class BackupService:
    """Database reads/writes for settings, table dump, restore and manifest."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_settings(self) -> dict[str, Any]:
        """All persisted settings as a ``{key: value}`` mapping."""
        result = await self.db.execute(select(Setting))
        return {row.key: row.value for row in result.scalars().all()}

    async def dump_table(self, table, limit: int) -> list:
        """Up to ``limit`` rows of ``table`` as mappings (for export)."""
        result = await self.db.execute(select(table).limit(limit))
        return result.mappings().all()

    async def fetch_table_rows(self, table) -> list:
        """All rows of ``table`` as mappings (for restore diffing)."""
        result = await self.db.execute(select(table))
        return result.mappings().all()

    async def row_exists(self, table, pk_clause) -> bool:
        """Whether a row matching ``pk_clause`` exists in ``table``."""
        result = await self.db.execute(select(table).where(pk_clause).limit(1))
        return result.first() is not None

    async def delete_where(self, table, pk_clause) -> None:
        """Delete rows of ``table`` matching ``pk_clause``."""
        await self.db.execute(table.delete().where(pk_clause))

    async def update_where(self, table, pk_clause, values: dict[str, Any]) -> None:
        """Update rows of ``table`` matching ``pk_clause`` with ``values``."""
        await self.db.execute(table.update().where(pk_clause).values(**values))

    async def insert_row(self, table, values: dict[str, Any]) -> None:
        """Insert one row into ``table``."""
        await self.db.execute(table.insert().values(**values))

    async def get_media_manifest(self) -> list:
        """(MediaFile, MediaItem) rows joined + ordered for the file manifest."""
        result = await self.db.execute(
            select(MediaFile, MediaItem)
            .join(MediaItem, MediaItem.guid == MediaFile.media_item_guid)
            .order_by(MediaItem.title, MediaFile.file_path)
        )
        return result.all()
