"""RSS sync scheduled tick (Subsystem 3).

Mirrors smart_collection_worker.py: a Redis-locked tick that runs
RssSyncService.run_once() and records a task event. The master switch
``automation.rss_sync_enabled`` is checked inside the service.
"""

from __future__ import annotations

import logging
import uuid

import redis.asyncio as redis_async

from pyrate.config import settings
from pyrate.database import sessionmanager
from pyrate.services.rss_sync import RssSyncService
from pyrate.services.task_events import record_worker_task_event

logger = logging.getLogger(__name__)

_LOCK_KEY = "rss_sync:tick:lock"
_LOCK_TTL = 50
_LOCK_RELEASE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


async def _acquire() -> tuple[redis_async.Redis, str] | tuple[None, None]:
    try:
        rds = redis_async.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
        token = uuid.uuid4().hex
        if not await rds.set(_LOCK_KEY, token, ex=_LOCK_TTL, nx=True):
            await rds.close()
            return None, None
        return rds, token
    except Exception as exc:
        logger.warning("rss-sync tick lock unavailable: %s", exc)
        return None, None


async def rss_sync_impl() -> dict:
    rds, token = await _acquire()
    if rds is None:
        logger.debug("rss-sync tick skipped (lock held)")
        return {"skipped": "locked"}
    try:
        async with sessionmanager.session() as db:
            result = await RssSyncService(db).run_once()
        payload = result.as_dict()
        if not payload.get("skipped_disabled"):
            await record_worker_task_event(
                task_id="rss_sync",
                category="automation",
                status="completed",
                message=(
                    f"RSS: polled {payload['indexers_polled']} indexer(s), "
                    f"{payload['feed_items']} item(s), "
                    f"{payload['matched_roots']} matched root(s), "
                    f"{payload['triggered']} triggered"
                ),
            )
        return payload
    except Exception as exc:
        logger.error("rss_sync failed: %s", exc)
        await record_worker_task_event(
            task_id="rss_sync",
            category="automation",
            status="failed",
            message="RSS sync failed",
            error=str(exc),
        )
        raise
    finally:
        try:
            await rds.eval(_LOCK_RELEASE, 1, _LOCK_KEY, token)
            await rds.close()
        except Exception:
            pass
