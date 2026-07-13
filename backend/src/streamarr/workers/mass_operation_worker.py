"""Taskiq workers driving the mass-operation engine."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis_async
from sqlalchemy import select

from streamarr.config import settings
from streamarr.database import sessionmanager
from streamarr.models.mass_operation import (
    MassOperationRule,
    MassOperationRunStatus,
)
from streamarr.services.mass_operation import MassOperationService
from streamarr.services.task_events import record_worker_task_event

logger = logging.getLogger(__name__)

_LOCK_KEY = "mass_operations:tick:lock"
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
        logger.warning("mass-operation tick lock unavailable: %s", exc)
        return None, None


async def tick_mass_operations_impl() -> int:
    """Enqueue mass-operation rules whose ``next_run_at`` is due."""
    rds, token = await _acquire()
    if rds is None:
        logger.debug("mass-operation tick skipped (lock held)")
        return 0

    try:
        now = datetime.now(UTC)
        async with sessionmanager.session() as db:
            stmt = (
                select(MassOperationRule.guid)
                .where(MassOperationRule.enabled.is_(True))
                .where(MassOperationRule.schedule_cron.isnot(None))
                .where(
                    (MassOperationRule.next_run_at.is_(None))
                    | (MassOperationRule.next_run_at <= now)
                )
            )
            rows = (await db.execute(stmt)).all()
            due_guids = [row[0] for row in rows]

        if not due_guids:
            return 0

        from streamarr.worker import run_mass_operation_rule  # noqa: WPS433

        for rule_guid in due_guids:
            await run_mass_operation_rule.kiq(str(rule_guid), False)
        logger.info("mass-operation tick enqueued %d run(s)", len(due_guids))
        return len(due_guids)
    finally:
        try:
            await rds.eval(_LOCK_RELEASE, 1, _LOCK_KEY, token)
            await rds.close()
        except Exception:
            pass


async def run_mass_operation_rule_impl(
    rule_guid: str,
    dry_run: bool = False,
) -> dict:
    """Execute a single mass-operation rule and emit task-event records."""
    try:
        guid = uuid.UUID(rule_guid)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid rule_guid {rule_guid!r}") from exc

    run_id = await record_worker_task_event(
        task_id="run_mass_operation_rule",
        category="mass_operations",
        status="queued",
        message=(
            f"Queued mass-operation run for {guid}"
            + (" (dry-run)" if dry_run else "")
        ),
    )

    async with sessionmanager.session() as db:
        service = MassOperationService(db)
        result = await service.run(guid, dry_run=bool(dry_run))

    status_text = (
        "completed"
        if result.status == MassOperationRunStatus.SUCCESS
        else "failed"
    )
    await record_worker_task_event(
        task_id="run_mass_operation_rule",
        category="mass_operations",
        status=status_text,
        run_id=run_id,
        message=(
            f"Mass-operation {guid} {result.status.value.lower()} — "
            f"matched={result.items_matched} updated={result.items_updated} "
            f"skipped={result.items_skipped} duration_ms={result.duration_ms}"
            + (" (dry-run)" if dry_run else "")
        ),
        error=result.error,
    )
    return {
        "rule_guid": str(guid),
        "run_guid": str(result.run_guid),
        "status": result.status.value,
        "dry_run": result.dry_run,
        "items_matched": result.items_matched,
        "items_updated": result.items_updated,
        "items_skipped": result.items_skipped,
        "duration_ms": result.duration_ms,
        "error": result.error,
        "changed_sample": result.changed_sample,
    }
