"""Builder that delegates to a ``ListSource`` adapter."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.metadata.list_sources import ListSource, ListSourceMediaType
from pyrate.smart_collections.builders.base import (
    BuildResult,
    SmartCollectionBuilder,
)


class ListSourceBuilder(SmartCollectionBuilder):
    """Wrap any ``ListSource`` as a builder.

    The wrapped source's ``slug`` is used as ``self.type``, so the
    registry can resolve ``builder_type`` ↔ ``ListSource`` 1:1.
    """

    def __init__(self, source: ListSource) -> None:
        self.source = source
        self.type = source.slug

    async def fetch(
        self,
        config: dict[str, Any],
        *,
        media_type: ListSourceMediaType,
        limit: int | None,
        db: AsyncSession,  # noqa: ARG002 — unused, satisfies protocol
    ) -> BuildResult:
        refs = await self.source.fetch(
            config, media_type=media_type, limit=limit
        )
        return BuildResult(refs=refs, debug={"source": self.source.slug})

    async def close(self) -> None:
        await self.source.close()
