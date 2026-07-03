"""Upgrade-scan scheduled tick (Subsystem 3).

Redis-locked tick mirroring smart_collection_worker.py. Batch size is
``automation.upgrade_scan_batch_size``; the master switch
``automation.upgrades_enabled`` is checked inside the service.
"""

from __future__ import annotations

import logging
import uuid

import redis.asyncio as redis_async

from pyrate.config import settings
from pyrate.database import sessionmanager
from pyrate.services.settings import SettingsService
from pyrate.services.task_events import record_worker_task_event
from pyrate.services.upgrade_scan import UpgradeScanService

logger = logging.getLogger(__name__)

_LOCK_KEY = "upgrade_scan:tick:lock"
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
        logger.warning("upgrade-scan tick lock unavailable: %s", exc)
        return None, None


async def tick_upgrade_scan_impl() -> dict:
    rds, token = await _acquire()
    if rds is None:
        logger.debug("upgrade-scan tick skipped (lock held)")
        return {"skipped": "locked"}
    try:
        async with sessionmanager.session() as db:
            batch = int(
                await SettingsService(db).get(
                    "automation.upgrade_scan_batch_size", 25
                )
                or 25
            )
            result = await UpgradeScanService(db).scan_batch(batch)
        payload = result.as_dict()
        if not payload.get("skipped_disabled"):
            await record_worker_task_event(
                task_id="upgrade_scan",
                category="automation",
                status="completed",
                message=(
                    f"Upgrade scan: {payload['candidates']} candidate(s), "
                    f"{payload['enqueued']} enqueued, "
                    f"{payload['skipped_cutoff_met']} at cutoff, "
                    f"{payload['skipped_active_dl']} downloading"
                ),
            )
        return payload
    except Exception as exc:
        logger.error("upgrade_scan failed: %s", exc)
        await record_worker_task_event(
            task_id="upgrade_scan",
            category="automation",
            status="failed",
            message="Upgrade scan failed",
            error=str(exc),
        )
        raise
    finally:
        try:
            await rds.eval(_LOCK_RELEASE, 1, _LOCK_KEY, token)
            await rds.close()
        except Exception:
            pass
