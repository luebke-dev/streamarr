"""Activity log API endpoints."""

import math
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query

from pyrate.api.dependencies import CurrentSuperuser, DatabaseSession
from pyrate.schemas.activity_log import (
    ActivityLogCreate,
    ActivityLogRead,
    PaginatedActivityLogResponse,
)
from pyrate.services.activity_log import ActivityLogService

router = APIRouter()


@router.get("", response_model=PaginatedActivityLogResponse)
async def list_activity_logs(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    event_type: str | None = Query(None),
    severity: str | None = Query(None),
    message: str | None = Query(None),
    entity_type: str | None = Query(None),
    entity_guid: UUID | None = Query(None),
    actor_guid: UUID | None = Query(None),
    has_actor: bool | None = Query(None),
    min_date: datetime | None = Query(None),
    max_date: datetime | None = Query(None),
    sort_by: Literal["created_at", "severity", "event_type"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
):
    """List activity log entries (admin only)."""
    skip = (page - 1) * per_page
    entries, total = await ActivityLogService(db).list(
        skip=skip,
        limit=per_page,
        event_type=event_type,
        severity=severity,
        message=message,
        entity_type=entity_type,
        entity_guid=entity_guid,
        actor_guid=actor_guid,
        has_actor=has_actor,
        min_date=min_date,
        max_date=max_date,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedActivityLogResponse(
        items=[ActivityLogRead.model_validate(entry) for entry in entries],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=math.ceil(total / per_page) if total > 0 else 1,
    )


@router.post("", response_model=ActivityLogRead, status_code=201)
async def create_activity_log(
    db: DatabaseSession,
    activity: ActivityLogCreate,
    current_user: CurrentSuperuser,
):
    """Create an activity log entry (admin only)."""
    entry = await ActivityLogService(db).create(activity, actor_guid=current_user.guid)
    return ActivityLogRead.model_validate(entry)
