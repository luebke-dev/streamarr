"""Schemas for activity log entries."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from streamarr.schemas.base import BaseSchema, PaginatedResponse


class ActivityLogCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    severity: str = Field(default="info", max_length=20)
    entity_type: str | None = Field(default=None, max_length=100)
    entity_guid: uuid.UUID | None = None
    extra_data: str | None = None


class ActivityLogRead(BaseSchema):
    guid: uuid.UUID
    created_at: datetime
    actor_guid: uuid.UUID | None = None
    event_type: str
    severity: str
    message: str
    entity_type: str | None = None
    entity_guid: uuid.UUID | None = None
    extra_data: str | None = None


class PaginatedActivityLogResponse(PaginatedResponse[ActivityLogRead]):
    pass
