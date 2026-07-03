"""Taskiq worker tasks for the smart-collection engine.

Two registered tasks:

  * ``tick_smart_collections`` — fires once per minute, enqueues a run
    for every rule whose ``next_run_at`` is due. Uses a Redis lock so
    overlapping ticks (multiple worker pods) don't double-dispatch.
  * ``run_smart_collection_rule`` — executes one rule end-to-end via
    :class:`SmartCollectionService`.

Run-history accounting is split in two: ``SmartCollectionRun`` rows
carry the engine-specific metrics, and :func:`record_worker_task_event`
writes an entry to the global activity log so the admin "tasks" page
sees them next to imports and recommendation rebuilds.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis_async
from sqlalchemy import select

from pyrate.config import settings
from pyrate.database import sessionmanager
from pyrate.models.smart_collection import (
    SmartCollectionRule,
    SmartCollectionRunStatus,
)
from pyrate.services.settings import SettingsService
from pyrate.services.task_events import record_worker_task_event
from pyrate.smart_collections import SmartCollectionService

logger = logging.getLogger(__name__)


_TICK_LOCK_KEY = "smart_collections:tick:lock"
_TICK_LOCK_TTL = 50  # seconds — slightly less than the 1-minute cadence
_TICK_LOCK_RELEASE = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


async def _api_keys(db) -> dict[str, Any]:
    """Read smart-collection API keys from the Settings table."""
    service = SettingsService(db)
    keys = await service.get("smart_collections.api_keys", {})
    return dict(keys) if isinstance(keys, dict) else {}


async def _acquire_tick_lock() -> tuple[redis_async.Redis, str] | tuple[None, None]:
    """Hold a short Redis lock so overlapping ticks no-op cleanly."""
    try:
        rds = redis_async.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
        token = uuid.uuid4().hex
        acquired = await rds.set(_TICK_LOCK_KEY, token, ex=_TICK_LOCK_TTL, nx=True)
        if not acquired:
            await rds.close()
            return None, None
        return rds, token
    except Exception as exc:
        logger.warning("smart-collection tick lock unavailable: %s", exc)
        return None, None


async def tick_smart_collections_impl() -> int:
    """Find due rules and enqueue runs. Returns the number enqueued."""
    # Avoid registering the task here; we expose the impl so it can be
    # called both from the @broker.task wrapper and from tests.
    rds, token = await _acquire_tick_lock()
    if rds is None:
        logger.debug("smart-collection tick skipped (lock held)")
        return 0

    enqueued = 0
    try:
        now = datetime.now(UTC)
        async with sessionmanager.session() as db:
            enabled_check = await SettingsService(db).get(
                "smart_collections.enabled", True
            )
            if not enabled_check:
                logger.debug("smart-collection tick disabled via settings")
                return 0

            stmt = (
                select(SmartCollectionRule.guid)
                .where(SmartCollectionRule.enabled.is_(True))
                .where(
                    (SmartCollectionRule.next_run_at.is_(None))
                    | (SmartCollectionRule.next_run_at <= now)
                )
            )
            rows = (await db.execute(stmt)).all()
            due_guids = [row[0] for row in rows]

        # Importing the broker-decorated task here keeps the impl easy
        # to test without booting taskiq.
        from pyrate.worker import run_smart_collection_rule  # noqa: WPS433

        for rule_guid in due_guids:
            await run_smart_collection_rule.kiq(str(rule_guid))
            enqueued += 1
        if enqueued:
            logger.info("smart-collection tick enqueued %d run(s)", enqueued)
    finally:
        try:
            await rds.eval(_TICK_LOCK_RELEASE, 1, _TICK_LOCK_KEY, token)
            await rds.close()
        except Exception:
            pass

    return enqueued


async def run_smart_collection_rule_impl(rule_guid: str) -> dict:
    """Execute one rule end-to-end and emit task-event records."""
    try:
        guid = uuid.UUID(rule_guid)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid rule_guid {rule_guid!r}") from exc

    run_id = await record_worker_task_event(
        task_id="run_smart_collection_rule",
        category="smart_collections",
        status="queued",
        message=f"Queued smart-collection run for {guid}",
    )

    async with sessionmanager.session() as db:
        api_keys = await _api_keys(db)
        service = SmartCollectionService(db, api_keys=api_keys)
        result = await service.run(guid)

    status_text = (
        "completed"
        if result.status == SmartCollectionRunStatus.SUCCESS
        else "failed"
    )
    await record_worker_task_event(
        task_id="run_smart_collection_rule",
        category="smart_collections",
        status=status_text,
        run_id=run_id,
        message=(
            f"Smart-collection {guid} {result.status.value.lower()} — "
            f"+{result.items_added}/-{result.items_removed} items, "
            f"{result.items_unresolved} unresolved, {result.duration_ms} ms"
        ),
        error=result.error,
    )
    return {
        "rule_guid": str(guid),
        "run_guid": str(result.run_guid),
        "status": result.status.value,
        "items_added": result.items_added,
        "items_removed": result.items_removed,
        "items_unresolved": result.items_unresolved,
        "duration_ms": result.duration_ms,
        "error": result.error,
    }


async def bulk_run_smart_collections() -> int:
    """Admin-triggered "run every enabled rule now" helper.

    Useful right after a Defaults import so the user sees populated
    lists without waiting for the natural cron tick. Returns the number
    of rules enqueued.
    """
    from pyrate.worker import run_smart_collection_rule  # noqa: WPS433

    async with sessionmanager.session() as db:
        rows = await db.execute(
            select(SmartCollectionRule.guid).where(
                SmartCollectionRule.enabled.is_(True)
            )
        )
        guids = [row[0] for row in rows.all()]

    for guid in guids:
        await run_smart_collection_rule.kiq(str(guid))
    return len(guids)


async def _run_due_now() -> None:
    """Used by integration tests: run the tick synchronously."""
    await tick_smart_collections_impl()
    await asyncio.sleep(0)  # let queued .kiq() calls flush
