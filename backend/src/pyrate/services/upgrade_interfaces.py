"""Thin adapter over Subsystem 1 (quality) + Subsystem 2 (monitoring).

S3 (RSS sync / upgrade scan / upgrade execution) only talks to S1/S2
through this module. Every call is wrapped so that if S1/S2 are missing
or change shape, S3 degrades to a safe no-op (no upgrade, not monitored)
rather than crashing the scheduler. This keeps the subsystems decoupled.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.media import MediaFile, MediaItem, MediaRelease

logger = logging.getLogger(__name__)


def available() -> dict[str, bool]:
    """Which subsystems are importable (logged once per task run)."""
    s1 = s2 = False
    try:
        import pyrate.services.quality_profile  # noqa: F401

        s1 = True
    except Exception:
        pass
    try:
        import pyrate.services.monitoring  # noqa: F401

        s2 = True
    except Exception:
        pass
    return {"quality": s1, "monitoring": s2}


# --------------------------------------------------------------------- #
# Subsystem 1 — quality / cutoff / linkage
# --------------------------------------------------------------------- #

async def cutoff_met(db: AsyncSession, media_item: MediaItem) -> bool:
    """True ⇒ no upgrade should be attempted. Safe default: True (skip)."""
    try:
        from pyrate.services.quality_profile import QualityProfileService

        return await QualityProfileService(db).cutoff_met(media_item)
    except Exception as e:
        logger.debug("cutoff_met fallback (True): %s", e)
        return True


async def is_upgrade_wanted(
    db: AsyncSession,
    media_item: MediaItem,
    candidate_release: MediaRelease,
    *,
    current_file: MediaFile | None = None,
) -> bool:
    """True ⇒ candidate is a profile-allowed improvement. Default: False."""
    try:
        from pyrate.services.quality_profile import QualityProfileService

        return await QualityProfileService(db).is_upgrade_wanted(
            media_item, candidate_release, current_file=current_file
        )
    except Exception as e:
        logger.debug("is_upgrade_wanted fallback (False): %s", e)
        return False


async def link_media_file_to_release(
    db: AsyncSession,
    media_file: MediaFile,
    release: MediaRelease,
    media_type: Any,
) -> None:
    """Persist file↔release linkage + parsed quality. Best-effort."""
    try:
        from pyrate.services.quality_profile import QualityProfileService

        await QualityProfileService(db).link_media_file_to_release(
            media_file, release, media_type
        )
    except Exception as e:
        logger.debug("link_media_file_to_release skipped: %s", e)


# --------------------------------------------------------------------- #
# Subsystem 2 — monitoring
# --------------------------------------------------------------------- #

async def is_item_favorite_monitored(
    db: AsyncSession, media_item: MediaItem | Any
) -> bool:
    """True ⇒ item is a monitored favorite. Safe default: False."""
    try:
        from pyrate.services.monitoring import MonitoringService

        status = await MonitoringService(db).is_item_favorite_monitored(
            media_item
        )
        return status is not None
    except Exception as e:
        logger.debug("is_item_favorite_monitored fallback (False): %s", e)
        return False


async def iter_monitored_leaves(
    db: AsyncSession,
    *,
    limit: int | None = None,
    order_by_oldest_searched: bool = True,
) -> list[MediaItem]:
    """Monitored leaf items (bounded). Safe default: []."""
    try:
        from pyrate.services.monitoring import MonitoringService

        out: list[MediaItem] = []
        async for mi in MonitoringService(db).iter_monitored_leaves(
            order_by_oldest_searched=order_by_oldest_searched, limit=limit
        ):
            out.append(mi)
        return out
    except Exception as e:
        logger.debug("iter_monitored_leaves fallback ([]): %s", e)
        return []


async def iter_missing_monitored_leaves(
    db: AsyncSession, *, limit: int | None = None
) -> AsyncIterator[MediaItem]:
    """Monitored leaves lacking a file/active download. Safe default: empty."""
    try:
        from pyrate.services.monitoring import MonitoringService

        async for mi in MonitoringService(db).iter_missing_monitored_leaves(
            limit=limit
        ):
            yield mi
    except Exception as e:
        logger.debug("iter_missing_monitored_leaves fallback (empty): %s", e)
        return
