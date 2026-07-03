"""Activity log service."""

import json
import logging
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.activity_log import ActivityLog
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.services.notification import NotificationDispatchService

logger = logging.getLogger(__name__)


class ActivityLogService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        activity: ActivityLogCreate,
        actor_guid: uuid.UUID | str | None = None,
        *,
        commit: bool = True,
    ) -> ActivityLog:
        """Create an activity log entry.

        Pass ``commit=False`` when the caller owns a larger unit of work. In
        that mode this method only flushes the row and skips notification
        dispatch; callers should emit external side effects after their
        transaction commits.
        """
        actor_uuid = uuid.UUID(str(actor_guid)) if actor_guid else None
        entry = ActivityLog(actor_guid=actor_uuid, **activity.model_dump())
        self.db.add(entry)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await self.db.refresh(entry)
        if commit:
            await self._dispatch_activity_event(entry)
        return entry

    async def _dispatch_activity_event(self, entry: ActivityLog) -> None:
        """Best-effort dispatch of activity events to configured notification providers."""
        payload = {
            "activity_guid": str(entry.guid),
            "event_type": entry.event_type,
            "severity": entry.severity,
            "message": entry.message,
            "entity_type": entry.entity_type,
            "entity_guid": str(entry.entity_guid) if entry.entity_guid else None,
            "actor_guid": str(entry.actor_guid) if entry.actor_guid else None,
        }
        if entry.extra_data:
            try:
                payload["extra_data"] = json.loads(entry.extra_data)
            except json.JSONDecodeError:
                payload["extra_data"] = entry.extra_data
        try:
            await NotificationDispatchService(self.db).dispatch_event(
                entry.event_type,
                payload,
            )
        except Exception as exc:
            logger.warning(
                "Activity notification dispatch failed for %s: %s",
                entry.event_type,
                exc,
            )

    async def list(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        event_type: str | None = None,
        severity: str | None = None,
        message: str | None = None,
        entity_type: str | None = None,
        entity_guid: uuid.UUID | None = None,
        actor_guid: uuid.UUID | None = None,
        has_actor: bool | None = None,
        min_date: datetime | None = None,
        max_date: datetime | None = None,
        sort_by: Literal["created_at", "severity", "event_type"] = "created_at",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> tuple[list[ActivityLog], int]:
        filters = []
        if event_type:
            filters.append(ActivityLog.event_type == event_type)
        if severity:
            filters.append(ActivityLog.severity == severity)
        if message:
            filters.append(ActivityLog.message.ilike(f"%{message}%"))
        if entity_type:
            filters.append(ActivityLog.entity_type == entity_type)
        if entity_guid:
            filters.append(ActivityLog.entity_guid == entity_guid)
        if actor_guid:
            filters.append(ActivityLog.actor_guid == actor_guid)
        if has_actor is True:
            filters.append(ActivityLog.actor_guid.is_not(None))
        elif has_actor is False:
            filters.append(ActivityLog.actor_guid.is_(None))
        if min_date:
            filters.append(ActivityLog.created_at >= min_date)
        if max_date:
            filters.append(ActivityLog.created_at <= max_date)

        sort_columns = {
            "created_at": ActivityLog.created_at,
            "severity": ActivityLog.severity,
            "event_type": ActivityLog.event_type,
        }
        sort_column = sort_columns[sort_by]
        order_clause = sort_column.asc() if sort_order == "asc" else sort_column.desc()

        count_stmt = select(func.count(ActivityLog.guid))
        data_stmt = select(ActivityLog).order_by(order_clause, ActivityLog.created_at.desc())
        if filters:
            count_stmt = count_stmt.where(*filters)
            data_stmt = data_stmt.where(*filters)

        total = await self.db.scalar(count_stmt) or 0
        result = await self.db.execute(data_stmt.offset(skip).limit(limit))
        return list(result.scalars().all()), total
