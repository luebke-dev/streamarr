"""Platform service for managing streaming/distribution platforms."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.platform import Platform

logger = logging.getLogger(__name__)


class PlatformService:
    """Service for platform operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Platform]:
        """List all platforms, ordered by name."""
        result = await self.db.execute(select(Platform).order_by(Platform.name))
        platforms = list(result.scalars().all())
        logger.debug("Listed %d platforms", len(platforms))
        return platforms
