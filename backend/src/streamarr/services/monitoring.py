"""Monitoring reads (Subsystem 2).

A media item is *monitored* when it (or a favorited ancestor) should be
auto-acquired and kept. The flag lives on ``MediaItem.monitored`` /
``monitored_source`` (written by the favorites backfill / reconcile worker).
This module is pure DB reads (no taskiq import) so Subsystems 1 & 3 can
import it without circulars.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from streamarr.models.downloads import Download, DownloadStatus
from streamarr.models.media import MediaFile, MediaItem, MediaRelease, MediaReleaseLink


@dataclass(frozen=True)
class MonitoredStatus:
    guid: uuid.UUID
    monitored: bool
    source: str | None
    reconciled_at: datetime | None


class MonitoringService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def is_item_favorite_monitored(
        self, item: MediaItem | uuid.UUID | str
    ) -> MonitoredStatus | None:
        """Return the monitored status, or ``None`` if not monitored.

        Accepts a loaded ``MediaItem`` (no extra query) or a guid.
        """
        if isinstance(item, MediaItem):
            mi = item
        else:
            guid = item if isinstance(item, uuid.UUID) else uuid.UUID(str(item))
            mi = await self.db.get(MediaItem, guid)
        if mi is None or not getattr(mi, "monitored", False):
            return None
        return MonitoredStatus(
            guid=mi.guid,
            monitored=True,
            source=getattr(mi, "monitored_source", None),
            reconciled_at=getattr(mi, "monitored_reconciled_at", None),
        )

    @staticmethod
    def _is_leaf_clause():
        """A leaf = no MediaItem has this row as its parent."""
        child = aliased(MediaItem)
        return ~exists().where(child.parent_guid == MediaItem.guid)

    async def iter_monitored_leaves(
        self,
        media_type: Any = None,
        *,
        batch_size: int = 500,
        order_by_oldest_searched: bool = False,
        limit: int | None = None,
    ) -> AsyncIterator[MediaItem]:
        """Yield monitored *leaf* items (episodes/movies/songs/...).

        Keyset-paginated by guid (or a bounded single page when
        ``order_by_oldest_searched`` is set, used by the upgrade scan for
        fairness)."""
        base = select(MediaItem).where(
            MediaItem.monitored.is_(True), self._is_leaf_clause()
        )
        if media_type is not None:
            base = base.where(MediaItem.media_type == media_type)

        if order_by_oldest_searched:
            q = base.order_by(
                MediaItem.last_searched_at.is_(None).desc(),
                MediaItem.last_searched_at.asc(),
            )
            if limit is not None:
                q = q.limit(limit)
            res = await self.db.execute(q)
            for mi in res.scalars().all():
                yield mi
            return

        last: uuid.UUID | None = None
        yielded = 0
        while True:
            q = base.order_by(MediaItem.guid).limit(batch_size)
            if last is not None:
                q = q.where(MediaItem.guid > last)
            rows = (await self.db.execute(q)).scalars().all()
            if not rows:
                return
            for mi in rows:
                yield mi
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            last = rows[-1].guid
            if len(rows) < batch_size:
                return

    async def iter_monitored_roots(self) -> AsyncIterator[MediaItem]:
        """Favorite-monitored top-level items (for the reconcile sweep)."""
        q = (
            select(MediaItem)
            .where(
                MediaItem.monitored.is_(True),
                MediaItem.monitored_source == "favorite",
                MediaItem.parent_guid.is_(None),
            )
            .order_by(
                MediaItem.monitored_reconciled_at.is_(None).desc(),
                MediaItem.monitored_reconciled_at.asc(),
            )
        )
        res = await self.db.execute(q)
        for mi in res.scalars().all():
            yield mi

    async def iter_missing_monitored_leaves(
        self, *, limit: int | None = None
    ) -> AsyncIterator[MediaItem]:
        """Monitored leaves with NO file AND no active download — the
        re-acquisition queue (lost / never-downloaded items)."""
        active_dl = (
            select(MediaRelease.media_item_guid)
            .join(
                MediaReleaseLink,
                MediaReleaseLink.media_release_guid == MediaRelease.guid,
            )
            .join(
                Download,
                Download.media_release_link_guid == MediaReleaseLink.guid,
            )
            .where(Download.status.notin_(DownloadStatus.ACTIVE_EXCLUSIONS))
        )
        q = (
            select(MediaItem)
            .where(
                MediaItem.monitored.is_(True),
                self._is_leaf_clause(),
                ~exists().where(
                    MediaFile.media_item_guid == MediaItem.guid
                ),
                MediaItem.guid.notin_(active_dl),
            )
            .order_by(
                MediaItem.last_searched_at.is_(None).desc(),
                MediaItem.last_searched_at.asc(),
            )
        )
        if limit is not None:
            q = q.limit(limit)
        res = await self.db.execute(q)
        for mi in res.scalars().all():
            yield mi
