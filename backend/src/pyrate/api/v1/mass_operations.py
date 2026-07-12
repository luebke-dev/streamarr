"""Admin API for mass-metadata operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from pyrate.api.dependencies import CurrentSuperuser, DatabaseSession
from pyrate.models.mass_operation import (
    MassOperationRule,
    MassOperationRun,
)
from pyrate.schemas.mass_operation import (
    MassOperationCreate,
    MassOperationDryRunResponse,
    MassOperationRead,
    MassOperationRunRead,
    MassOperationRunResponse,
    MassOperationUpdate,
)
from pyrate.services.mass_operation import (
    MassOperationError,
    MassOperationService,
)
from pyrate.smart_collections.cron import next_run_after

router = APIRouter()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[MassOperationRead])
async def list_rules(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    enabled: bool | None = Query(default=None),
):
    stmt = select(MassOperationRule).order_by(
        MassOperationRule.is_system.desc(),
        MassOperationRule.name.asc(),
    )
    if enabled is not None:
        stmt = stmt.where(MassOperationRule.enabled.is_(enabled))
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{rule_guid}", response_model=MassOperationRead)
async def get_rule(
    rule_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    rule = await db.get(MassOperationRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Mass-operation rule not found")
    return rule


@router.post("", response_model=MassOperationRead, status_code=201)
async def create_rule(
    payload: MassOperationCreate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    try:
        MassOperationService._validate_action(payload.action)  # noqa: SLF001
    except MassOperationError as exc:
        raise HTTPException(422, detail=str(exc))
    rule = MassOperationRule(
        name=payload.name,
        description=payload.description,
        target_filter=payload.target_filter,
        action=payload.action,
        schedule_cron=payload.schedule_cron,
        enabled=payload.enabled,
        is_system=False,
    )
    if payload.schedule_cron:
        try:
            rule.next_run_at = next_run_after(payload.schedule_cron)
        except ValueError as exc:
            raise HTTPException(
                422, detail=f"Invalid schedule_cron {payload.schedule_cron!r}: {exc}"
            )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/{rule_guid}", response_model=MassOperationRead)
async def update_rule(
    rule_guid: uuid.UUID,
    payload: MassOperationUpdate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    rule = await db.get(MassOperationRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Mass-operation rule not found")

    changes = payload.model_dump(exclude_unset=True)
    if rule.is_system and set(changes) - {"enabled", "schedule_cron"}:
        raise HTTPException(
            422,
            detail="System rules are read-only except for 'enabled' and 'schedule_cron'",
        )
    if "action" in changes:
        try:
            MassOperationService._validate_action(changes["action"])  # noqa: SLF001
        except MassOperationError as exc:
            raise HTTPException(422, detail=str(exc))
    for key, value in changes.items():
        setattr(rule, key, value)
    if "schedule_cron" in changes:
        if rule.schedule_cron:
            try:
                rule.next_run_at = next_run_after(rule.schedule_cron)
            except ValueError as exc:
                raise HTTPException(
                    422, detail=f"Invalid schedule_cron {rule.schedule_cron!r}: {exc}"
                )
        else:
            rule.next_run_at = None
    rule.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/{rule_guid}", status_code=204)
async def delete_rule(
    rule_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    rule = await db.get(MassOperationRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Mass-operation rule not found")
    if rule.is_system:
        raise HTTPException(
            422, detail="System rules cannot be deleted; disable instead"
        )
    await db.delete(rule)
    await db.commit()


# ---------------------------------------------------------------------------
# Run / dry-run / history
# ---------------------------------------------------------------------------


@router.post(
    "/{rule_guid}/dry-run",
    response_model=MassOperationDryRunResponse,
)
async def dry_run_rule(
    rule_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    """Synchronously run the rule in dry-run mode and return matches.

    Inline rather than async because admins typically want to see "what
    would change?" before clicking Apply — waiting on the queue would
    feel sluggish.
    """
    rule = await db.get(MassOperationRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Mass-operation rule not found")
    service = MassOperationService(db)
    result = await service.run(rule_guid, dry_run=True)
    if result.status.value == "FAILED":
        raise HTTPException(422, detail=result.error or "Dry-run failed")
    return MassOperationDryRunResponse(
        rule_guid=rule.guid,
        items_matched=result.items_matched,
        items_updated=result.items_updated,
        items_skipped=result.items_skipped,
        duration_ms=result.duration_ms,
        changed_sample=result.changed_sample,
    )


@router.post(
    "/{rule_guid}/run",
    response_model=MassOperationRunResponse,
    status_code=202,
)
async def run_rule_now(
    rule_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    """Enqueue an async (non-dry-run) execution."""
    rule = await db.get(MassOperationRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Mass-operation rule not found")

    from pyrate.worker import run_mass_operation_rule

    await run_mass_operation_rule.kiq(str(rule.guid), False)
    return MassOperationRunResponse(
        rule_guid=rule.guid, enqueued=True, dry_run=False
    )


@router.get("/{rule_guid}/runs", response_model=list[MassOperationRunRead])
async def list_runs(
    rule_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    limit: int = Query(default=20, ge=1, le=200),
):
    rule = await db.get(MassOperationRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Mass-operation rule not found")
    rows = await db.execute(
        select(MassOperationRun)
        .where(MassOperationRun.rule_guid == rule_guid)
        .order_by(desc(MassOperationRun.started_at))
        .limit(limit)
    )
    return list(rows.scalars().all())
