"""Incremental + delta Elasticsearch sync.

Keeps the search index aligned with Postgres without a manual full reindex:

* ``reindex_media_item`` — re-index one item after a create/update. Enqueued
  best-effort from ``MediaService`` so a missing broker never fails a DB write.
* ``remove_media_item_from_index`` — drop one item from the index after a
  delete (the media type is carried along because the row is already gone).
* ``reindex_recent_media`` — a periodic safety net that re-indexes everything
  touched in the last window, catching any enqueue that was lost.

Impl functions are kept separate from the ``@broker.task`` wrappers so the
test suite can drive them without booting the broker layer.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from streamarr.database import sessionmanager
from streamarr.models.media import MediaItem, MediaType
from streamarr.services.elasticsearch import elasticsearch_service
from streamarr.workers.runtime import broker

logger = logging.getLogger(__name__)

# Media types that actually have an Elasticsearch index.
_INDEXED_MEDIA_TYPES = (MediaType.MOVIES, MediaType.SHOWS, MediaType.BOOKS)

# Overlap window for the delta safety net. A little larger than the schedule
# interval so nothing slips through between runs.
_DELTA_WINDOW_MINUTES = 20


async def _ensure_client() -> bool:
    """Return True when an ES client is available, initialising it lazily."""
    if elasticsearch_service.client is None:
        try:
            await elasticsearch_service.initialize()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Elasticsearch init failed during sync: %s", exc)
    return elasticsearch_service.client is not None


async def reindex_media_item_impl(media_item_guid: str) -> None:
    """Re-index a single media item after a create/update."""
    if not await _ensure_client():
        return
    async with sessionmanager.session() as db:
        result = await db.execute(
            select(MediaItem)
            .where(MediaItem.guid == uuid.UUID(media_item_guid))
            .options(
                selectinload(MediaItem.genres),
                selectinload(MediaItem.external_ids),
            )
        )
        item = result.scalars().first()
        if item is None:
            # Deleted between enqueue and execution; the delete task owns removal.
            logger.debug("Skip reindex for missing media item %s", media_item_guid)
            return
        await elasticsearch_service.index_media_item(item)


async def remove_media_item_from_index_impl(
    media_item_guid: str, media_type: str
) -> None:
    """Remove a single media item from the index after a delete."""
    if not await _ensure_client():
        return
    await elasticsearch_service.delete_media_item(
        uuid.UUID(media_item_guid), media_type
    )


async def reindex_recent_media_impl(
    window_minutes: int = _DELTA_WINDOW_MINUTES,
) -> dict:
    """Re-index every indexable top-level item updated within the window."""
    if not await _ensure_client():
        return {"skipped": "es_unavailable"}
    cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
    reindexed = 0
    async with sessionmanager.session() as db:
        result = await db.execute(
            select(MediaItem)
            .where(
                MediaItem.media_type.in_(_INDEXED_MEDIA_TYPES),
                MediaItem.parent_guid.is_(None),
                MediaItem.updated_at >= cutoff,
            )
            .options(
                selectinload(MediaItem.genres),
                selectinload(MediaItem.external_ids),
            )
        )
        for item in result.scalars().all():
            if await elasticsearch_service.index_media_item(item):
                reindexed += 1
    if reindexed:
        logger.info("Delta reindex: %d item(s) synced to Elasticsearch", reindexed)
    return {"reindexed": reindexed}


@broker.task
async def reindex_media_item(media_item_guid: str) -> None:
    """Re-index one media item (enqueued after a create/update)."""
    await reindex_media_item_impl(media_item_guid)


@broker.task
async def remove_media_item_from_index(
    media_item_guid: str, media_type: str
) -> None:
    """Remove one media item from the index (enqueued after a delete)."""
    await remove_media_item_from_index_impl(media_item_guid, media_type)


@broker.task(schedule=[{"cron": "*/15 * * * *"}])  # Every 15 minutes
async def reindex_recent_media() -> dict:
    """Delta safety net: re-index recently changed items."""
    return await reindex_recent_media_impl()
