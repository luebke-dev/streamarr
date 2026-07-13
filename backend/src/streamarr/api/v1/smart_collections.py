"""Admin API for smart-collection rules.

All endpoints are gated by ``CurrentSuperuser``. Mutating endpoints
respect the ``is_system`` flag: system-seeded rules can be toggled
on/off and re-run, but their builder/filter config is read-only — the
admin would otherwise be able to break the bundled defaults beyond
recognition.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from streamarr.api.dependencies import CurrentSuperuser, DatabaseSession
from streamarr.metadata.list_sources import ListSourceError, source_class
from streamarr.models.smart_collection import (
    SmartCollectionRule,
    SmartCollectionRun,
)
from streamarr.schemas.smart_collection import (
    BuilderInfo,
    SmartCollectionCreate,
    SmartCollectionRead,
    SmartCollectionRunRead,
    SmartCollectionUpdate,
)
from streamarr.smart_collections import builder_types
from streamarr.smart_collections.cron import next_run_after

router = APIRouter()


# ---------------------------------------------------------------------------
# Builders catalogue (powers the admin UI's builder picker / form)
# ---------------------------------------------------------------------------


@router.get("/builders", response_model=list[BuilderInfo])
async def list_builders(current_user: CurrentSuperuser):  # noqa: ARG001
    """Describe every available builder type and its config schema."""
    out: list[BuilderInfo] = []
    for type_ in builder_types():
        if type_ == "library_filter":
            out.append(
                BuilderInfo(
                    type="library_filter",
                    supported_media_types=["MOVIE", "SHOW"],
                    requires_api_key=False,
                    config_schema={
                        "year_min": {"type": "integer"},
                        "year_max": {"type": "integer"},
                        "decade": {"type": "integer"},
                        "min_age": {"type": "integer"},
                        "max_age": {"type": "integer"},
                        "availability": {
                            "type": "select",
                            "options": [
                                "available",
                                "downloadable",
                                "unknown",
                            ],
                        },
                        "sort": {
                            "type": "select",
                            "options": ["release_date", "title", "created_at"],
                        },
                        "sort_dir": {
                            "type": "select",
                            "options": ["asc", "desc"],
                        },
                    },
                )
            )
            continue
        try:
            cls = source_class(type_)
        except ListSourceError:
            continue
        out.append(
            BuilderInfo(
                type=type_,
                supported_media_types=sorted(
                    mt.value.upper() for mt in cls.supported_media_types
                ),
                requires_api_key=cls.requires_api_key,
                config_schema=cls.config_schema,
            )
        )
    return out


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[SmartCollectionRead])
async def list_rules(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    enabled: bool | None = Query(default=None),
    is_system: bool | None = Query(default=None),
):
    stmt = select(SmartCollectionRule).order_by(
        SmartCollectionRule.is_system.desc(),
        SmartCollectionRule.name.asc(),
    )
    if enabled is not None:
        stmt = stmt.where(SmartCollectionRule.enabled.is_(enabled))
    if is_system is not None:
        stmt = stmt.where(SmartCollectionRule.is_system.is_(is_system))
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


@router.get("/{rule_guid}", response_model=SmartCollectionRead)
async def get_rule(
    rule_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    rule = await db.get(SmartCollectionRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Smart-collection rule not found")
    return rule


@router.post(
    "",
    response_model=SmartCollectionRead,
    status_code=201,
)
async def create_rule(
    payload: SmartCollectionCreate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    if payload.builder_type not in builder_types():
        raise HTTPException(
            422, detail=f"Unknown builder_type {payload.builder_type!r}"
        )
    rule = SmartCollectionRule(
        name=payload.name,
        description=payload.description,
        media_type=payload.media_type,
        builder_type=payload.builder_type,
        builder_config=payload.builder_config,
        filters=payload.filters,
        sync_mode=payload.sync_mode,
        item_limit=payload.item_limit,
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
    else:
        rule.next_run_at = None
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/{rule_guid}", response_model=SmartCollectionRead)
async def update_rule(
    rule_guid: uuid.UUID,
    payload: SmartCollectionUpdate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    rule = await db.get(SmartCollectionRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Smart-collection rule not found")

    changes = payload.model_dump(exclude_unset=True)
    # System rules: only enabled toggle and schedule_cron are mutable —
    # builder/filter changes would break the bundled defaults.
    if rule.is_system:
        allowed = {"enabled", "schedule_cron"}
        invalid = set(changes) - allowed
        if invalid:
            raise HTTPException(
                422,
                detail=(
                    f"System rule {rule.guid} is read-only for fields: "
                    f"{sorted(invalid)}"
                ),
            )
    if "builder_type" in changes and changes["builder_type"] not in builder_types():
        raise HTTPException(
            422, detail=f"Unknown builder_type {changes['builder_type']!r}"
        )
    if "schedule_cron" in changes:
        cron_value = changes["schedule_cron"]
        if cron_value:
            try:
                next_run_at = next_run_after(cron_value)
            except ValueError as exc:
                raise HTTPException(
                    422, detail=f"Invalid schedule_cron {cron_value!r}: {exc}"
                )
        else:
            next_run_at = None
    for key, value in changes.items():
        setattr(rule, key, value)
    if "schedule_cron" in changes:
        rule.next_run_at = next_run_at
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
    rule = await db.get(SmartCollectionRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Smart-collection rule not found")
    if rule.is_system:
        raise HTTPException(
            422, detail="System rules cannot be deleted; disable instead"
        )
    await db.delete(rule)
    await db.commit()


# ---------------------------------------------------------------------------
# Run-now / history
# ---------------------------------------------------------------------------


@router.post("/{rule_guid}/run", status_code=202)
async def run_rule_now(
    rule_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
) -> dict:
    """Enqueue a synchronous run via taskiq. Returns 202 + queued envelope."""
    rule = await db.get(SmartCollectionRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Smart-collection rule not found")

    # Importing inside the function keeps the API import-graph free of
    # taskiq broker dependencies at module load.
    from streamarr.worker import run_smart_collection_rule

    await run_smart_collection_rule.kiq(str(rule.guid))
    return {"rule_guid": str(rule.guid), "enqueued": True}


@router.get(
    "/{rule_guid}/runs",
    response_model=list[SmartCollectionRunRead],
)
async def list_runs(
    rule_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    limit: int = Query(default=20, ge=1, le=200),
):
    rule = await db.get(SmartCollectionRule, rule_guid)
    if rule is None:
        raise HTTPException(404, detail="Smart-collection rule not found")
    rows = await db.execute(
        select(SmartCollectionRun)
        .where(SmartCollectionRun.rule_guid == rule_guid)
        .order_by(desc(SmartCollectionRun.started_at))
        .limit(limit)
    )
    return list(rows.scalars().all())
