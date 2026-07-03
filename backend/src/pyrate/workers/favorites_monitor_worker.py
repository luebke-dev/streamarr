"""Favorites monitoring + backwards-search orchestrator (Subsystem 2).

Three impls (registered as @broker.task wrappers in worker.py):

  * ``backfill_favorite_monitored`` — on favorite, monitor the whole
    subtree of the favorited root and fan out search + auto-download for
    every missing leaf (the "backwards search").
  * ``unmonitor_favorite`` — on unfavorite, release the monitoring lock
    for the subtree (never deletes files).
  * ``tick_favorites_reconcile`` — 6h sweep: pick up newly-appeared
    children of favorited roots and re-acquire lost monitored leaves.

Impls are exposed (not decorated) so tests can drive them without taskiq.
Mirrors the lock/session/event shape of smart_collection_worker.py.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis_async
from sqlalchemy import literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.config import settings
from pyrate.database import sessionmanager
from pyrate.models.downloads import Download, DownloadStatus
from pyrate.models.media import (
    MediaFile,
    MediaItem,
    MediaRelease,
    MediaReleaseLink,
)
from pyrate.services.settings import SettingsService
from pyrate.services.task_events import record_worker_task_event

logger = logging.getLogger(__name__)

_RECONCILE_LOCK_KEY = "favorites_monitor:reconcile:lock"
_RECONCILE_LOCK_TTL = 50
_BACKFILL_LOCK_TTL = 300  # a big series fan-out takes a while
_BATCH = 25
_BATCH_SLEEP = 2.0
_MAX_DEPTH = 4  # show -> season -> episode (+root); artist -> album -> song


async def _redis() -> redis_async.Redis | None:
    try:
        return redis_async.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("favorites-monitor redis unavailable: %s", exc)
        return None


async def _acquire(rds: redis_async.Redis | None, key: str, ttl: int) -> bool:
    if rds is None:
        return True  # degrade open — better to run than to silently skip
    try:
        return bool(await rds.set(key, "1", ex=ttl, nx=True))
    except Exception:
        return True


async def _release(rds: redis_async.Redis | None, key: str) -> None:
    if rds is None:
        return
    try:
        await rds.delete(key)
        await rds.close()
    except Exception:
        pass


async def _collect_subtree(
    db: AsyncSession, root_guid: str
) -> list[tuple]:
    """Return [(guid, parent_guid)] for the root + all descendants
    (depth-bounded). Recursive CTE so it works on Postgres and the
    SQLite test DB alike."""
    try:
        root_uuid: uuid.UUID | str = uuid.UUID(str(root_guid))
    except (ValueError, TypeError):
        root_uuid = root_guid
    anchor = (
        select(
            MediaItem.guid,
            MediaItem.parent_guid,
            literal_column("1").label("depth"),
        )
        .where(MediaItem.guid == root_uuid)
        .cte(name="subtree", recursive=True)
    )
    child = select(
        MediaItem.guid,
        MediaItem.parent_guid,
        (anchor.c.depth + 1).label("depth"),
    ).join(anchor, MediaItem.parent_guid == anchor.c.guid).where(
        anchor.c.depth < _MAX_DEPTH
    )
    cte = anchor.union_all(child)
    rows = (await db.execute(select(cte.c.guid, cte.c.parent_guid))).all()
    return [(r[0], r[1]) for r in rows]


def _leaf_guids(rows: list[tuple]) -> list:
    """A node is a leaf if it is not the parent of any collected node."""
    parents = {r[1] for r in rows if r[1] is not None}
    return [r[0] for r in rows if r[0] not in parents]


async def _missing_leaves(db: AsyncSession, leaf_guids: list) -> list:
    """Leaves with no MediaFile AND no active download (bulk)."""
    if not leaf_guids:
        return []
    have_file = set(
        (
            await db.execute(
                select(MediaFile.media_item_guid).where(
                    MediaFile.media_item_guid.in_(leaf_guids)
                )
            )
        ).scalars().all()
    )
    active = set(
        (
            await db.execute(
                select(MediaRelease.media_item_guid)
                .join(
                    MediaReleaseLink,
                    MediaReleaseLink.media_release_guid == MediaRelease.guid,
                )
                .join(
                    Download,
                    Download.media_release_link_guid == MediaReleaseLink.guid,
                )
                .where(MediaRelease.media_item_guid.in_(leaf_guids))
                .where(
                    Download.status.notin_(DownloadStatus.ACTIVE_EXCLUSIONS)
                )
            )
        ).scalars().all()
    )
    return [g for g in leaf_guids if g not in have_file and g not in active]


async def _fan_out(leaf_guids: list, user_guid: str | None) -> int:
    """Enqueue force-search + backfill-download for each missing leaf,
    rate-limited so a 10-season show doesn't flood the indexers."""
    from pyrate.worker import auto_download_media_item, search_media_item_releases

    n = 0
    for i in range(0, len(leaf_guids), _BATCH):
        batch = leaf_guids[i : i + _BATCH]
        for guid in batch:
            await search_media_item_releases.kiq(
                str(guid), user_guid, force=True
            )
            await auto_download_media_item.kiq(
                str(guid), None, user_guid, backfill=True
            )
            n += 1
        if i + _BATCH < len(leaf_guids):
            await asyncio.sleep(_BATCH_SLEEP)
    return n


async def _autodownload_enabled(db: AsyncSession) -> bool:
    """Master switch. Monitoring/retention always applies, but the actual
    search + download fan-out only runs once an operator opts in (safe
    rollout: default OFF)."""
    try:
        return bool(
            await SettingsService(db).get(
                "automation.favorites_autodownload_enabled", False
            )
        )
    except Exception:
        return False


async def _set_monitored(
    db: AsyncSession, guids: list, *, monitored: bool
) -> int:
    """Bulk set/clear monitored for guids, never clobbering manual monitors."""
    if not guids:
        return 0
    if monitored:
        values = {
            "monitored": True,
            "monitored_source": "favorite",
            "monitored_reconciled_at": datetime.now(UTC),
        }
    else:
        values = {
            "monitored": False,
            "monitored_source": None,
            "monitored_reconciled_at": None,
        }
    stmt = (
        update(MediaItem)
        .where(MediaItem.guid.in_(guids))
        .where(MediaItem.monitored_source.is_distinct_from("manual"))
        .values(**values)
    )
    res = await db.execute(stmt)
    await db.commit()
    return res.rowcount or 0


async def backfill_favorite_monitored_impl(
    root_guid: str, user_guid: str | None = None
) -> dict:
    rds = await _redis()
    lock_key = f"favorites_monitor:backfill:{root_guid}"
    if not await _acquire(rds, lock_key, _BACKFILL_LOCK_TTL):
        if rds is not None:
            await rds.close()
        return {"skipped": "locked", "root": root_guid}

    try:
        async with sessionmanager.session() as db:
            root = await db.get(MediaItem, root_guid)
            if root is None:
                return {"skipped": "root_gone", "root": root_guid}

            rows = await _collect_subtree(db, root_guid)
            all_guids = [r[0] for r in rows]
            monitored_n = await _set_monitored(db, all_guids, monitored=True)

            leaves = _leaf_guids(rows)
            missing = await _missing_leaves(db, leaves)
            fan_out_enabled = await _autodownload_enabled(db)

        searched = (
            await _fan_out(missing, user_guid) if fan_out_enabled else 0
        )
        await record_worker_task_event(
            task_id=f"backfill:{root_guid}",
            category="favorites_monitor",
            status="completed",
            message=(
                f"Monitored {monitored_n} item(s); "
                + (
                    f"searched {searched} missing leaf/leaves"
                    if fan_out_enabled
                    else f"{len(missing)} missing (auto-download disabled)"
                )
                + f" ({len(leaves)} leaves, root {root_guid})"
            ),
        )
        return {
            "root": root_guid,
            "monitored": monitored_n,
            "leaves": len(leaves),
            "searched": searched,
        }
    except Exception as exc:
        logger.error("backfill_favorite_monitored failed for %s: %s", root_guid, exc)
        await record_worker_task_event(
            task_id=f"backfill:{root_guid}",
            category="favorites_monitor",
            status="failed",
            message=f"Backfill failed for {root_guid}",
            error=str(exc),
        )
        raise
    finally:
        await _release(rds, lock_key)


async def unmonitor_favorite_impl(root_guid: str) -> dict:
    try:
        async with sessionmanager.session() as db:
            root = await db.get(MediaItem, root_guid)
            if root is None:
                return {"skipped": "root_gone", "root": root_guid}
            rows = await _collect_subtree(db, root_guid)
            guids = [r[0] for r in rows]
            cleared = await _set_monitored(db, guids, monitored=False)
        logger.info("Unmonitored %d item(s) under root %s", cleared, root_guid)
        return {"root": root_guid, "unmonitored": cleared}
    except Exception as exc:
        logger.error("unmonitor_favorite failed for %s: %s", root_guid, exc)
        raise


async def tick_favorites_reconcile_impl() -> int:
    """6h sweep: monitor newly-appeared children of favorited roots and
    re-acquire monitored leaves that lost their file."""
    rds = await _redis()
    if not await _acquire(rds, _RECONCILE_LOCK_KEY, _RECONCILE_LOCK_TTL):
        if rds is not None:
            await rds.close()
        logger.debug("favorites reconcile skipped (lock held)")
        return 0

    enqueued = 0
    try:
        from pyrate.services.monitoring import MonitoringService

        async with sessionmanager.session() as db:
            if not await SettingsService(db).get(
                "favorites.monitor_enabled", True
            ):
                logger.debug("favorites reconcile disabled via settings")
                return 0

            svc = MonitoringService(db)

            # 1) New children of favorited roots become monitored.
            root_guids: list = []
            async for root in svc.iter_monitored_roots():
                root_guids.append(str(root.guid))
            for rg in root_guids:
                rows = await _collect_subtree(db, rg)
                await _set_monitored(
                    db, [r[0] for r in rows], monitored=True
                )

            # 2) Re-acquire monitored leaves missing a file (only when
            #    auto-download is enabled — monitoring always reconciles).
            missing: list = []
            fan_out_enabled = await _autodownload_enabled(db)
            if fan_out_enabled:
                async for mi in svc.iter_missing_monitored_leaves(limit=500):
                    missing.append(str(mi.guid))

        enqueued = await _fan_out(missing, None) if missing else 0
        if enqueued or root_guids:
            await record_worker_task_event(
                task_id="favorites_reconcile",
                category="favorites_monitor",
                status="completed",
                message=(
                    f"Reconciled {len(root_guids)} root(s); "
                    + (
                        f"re-acquiring {enqueued} missing leaf/leaves"
                        if fan_out_enabled
                        else "auto-download disabled"
                    )
                ),
            )
    finally:
        await _release(rds, _RECONCILE_LOCK_KEY)

    return enqueued
