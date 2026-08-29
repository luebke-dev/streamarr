"""Periodic full media-library reconciliation orchestration."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis_async
from sqlalchemy import select

from streamarr.config import settings
from streamarr.database import sessionmanager
from streamarr.models.activity_log import ActivityLog
from streamarr.schemas.activity_log import ActivityLogCreate
from streamarr.services.activity_log import ActivityLogService
from streamarr.services.library import LibraryService
from streamarr.services.library_post_scan import PostScanEnqueuers, dispatch_post_scan
from streamarr.services.redis_event import get_redis_event_service
from streamarr.services.settings import SettingsService

logger = logging.getLogger(__name__)
_LOCK_KEY = "library_scan:full:lock"
_PROBE_LIBRARY_TYPES = {"MOVIES", "SHOWS", "MUSIC", "AUDIOBOOKS"}
ProbeEnqueuer = Callable[[str], Awaitable[object]]


async def _scan_is_due(db, library_guid, interval_hours: int) -> bool:
    last_scan = await db.scalar(
        select(ActivityLog.created_at)
        .where(
            ActivityLog.event_type == "library.scan",
            ActivityLog.entity_type == "library",
            ActivityLog.entity_guid == library_guid,
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(1)
    )
    if last_scan is None:
        return True
    if last_scan.tzinfo is None:
        last_scan = last_scan.replace(tzinfo=UTC)
    return last_scan <= datetime.now(UTC) - timedelta(hours=interval_hours)


async def _record_scan(db, library, *, status: str, counts: dict, error=None) -> None:
    payload = {
        "library_guid": str(library.guid),
        "library_type": library.type,
        "path": library.path,
        "status": status,
        **counts,
    }
    if error:
        payload["error"] = str(error)
    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="library.scan"
            if status == "completed"
            else "library.scan_failed",
            severity="info" if status == "completed" else "error",
            message=(
                f"Scanned library {library.name}; discovered "
                f"{counts.get('discovered', 0)} files"
                if status == "completed"
                else f"Library scan failed for {library.name}"
            ),
            entity_type="library",
            entity_guid=library.guid,
            extra_data=json.dumps(payload, sort_keys=True),
        )
    )
    try:
        await get_redis_event_service().publish(
            channel="libraries",
            event=f"library_scan_{status}",
            data=payload,
        )
    except Exception:
        logger.debug("Could not publish library scan event", exc_info=True)


async def scan_libraries_impl(
    *,
    force: bool,
    enqueue_probe: ProbeEnqueuer | None = None,
    enqueue_metadata=None,
    enqueue_subtitles=None,
    enqueue_search_index=None,
) -> dict[str, int | str]:
    """Scan enabled libraries once, using existing settings/events/task queue."""
    redis = redis_async.from_url(settings.redis_url, decode_responses=True)
    token = uuid.uuid4().hex
    acquired = False
    totals = {
        "libraries": 0,
        "discovered": 0,
        "added": 0,
        "updated": 0,
        "removed": 0,
        "files_skipped": 0,
        "libraries_skipped": 0,
        "failed": 0,
        "probes_queued": 0,
    }
    try:
        acquired = bool(await redis.set(_LOCK_KEY, token, nx=True, ex=6 * 60 * 60))
        if not acquired:
            return {"status": "already_running", **totals}

        async with sessionmanager.session() as db:
            interval = int(
                await SettingsService(db).get(
                    "automation.library_scan_interval_hours", 12
                )
            )
            service = LibraryService(db)
            for library in await service.list_libraries(enabled_only=True):
                if not force and not await _scan_is_due(db, library.guid, interval):
                    totals["libraries_skipped"] += 1
                    continue
                try:
                    _discovered, result = await service.scan_library_with_result(
                        library.guid
                    )
                    counts = {
                        "discovered": result.discovered,
                        "added": result.added,
                        "updated": result.updated,
                        "removed": result.removed,
                        "skipped": result.skipped,
                    }
                    totals["libraries"] += 1
                    totals["discovered"] += counts["discovered"]
                    totals["added"] += counts["added"]
                    totals["updated"] += counts["updated"]
                    totals["removed"] += counts["removed"]
                    totals["files_skipped"] += counts["skipped"]
                    await _record_scan(db, library, status="completed", counts=counts)

                    queued = await dispatch_post_scan(
                        library,
                        result,
                        PostScanEnqueuers(
                            probe=enqueue_probe,
                            metadata=enqueue_metadata,
                            subtitles=enqueue_subtitles,
                            search_index=enqueue_search_index,
                        ),
                    )
                    totals["probes_queued"] += queued["probes"]
                except Exception as exc:
                    await db.rollback()
                    totals["failed"] += 1
                    logger.exception("Scan failed for library %s", library.guid)
                    await _record_scan(
                        db,
                        library,
                        status="failed",
                        counts={"discovered": 0},
                        error=exc,
                    )
        return {"status": "completed", **totals}
    finally:
        if acquired:
            try:
                await redis.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    _LOCK_KEY,
                    token,
                )
            finally:
                await redis.aclose()
        else:
            await redis.aclose()


async def scan_all_libraries_impl(
    enqueue_probe: ProbeEnqueuer | None = None,
    **enqueue_kwargs,
) -> dict[str, int | str]:
    """Compatibility entry point for an explicit full scan."""
    return await scan_libraries_impl(
        force=True, enqueue_probe=enqueue_probe, **enqueue_kwargs
    )
