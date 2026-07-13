"""Pydantic schemas for the smart-collection admin API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from streamarr.models.smart_collection import (
    SmartCollectionMediaType,
    SmartCollectionRunStatus,
    SmartCollectionSyncMode,
)
from streamarr.schemas.base import BaseSchema
from streamarr.smart_collections.cron import parse_cron


class _SmartCollectionCommon(BaseSchema):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    media_type: SmartCollectionMediaType
    builder_type: str = Field(min_length=1, max_length=50)
    builder_config: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    sync_mode: SmartCollectionSyncMode = SmartCollectionSyncMode.SYNC
    item_limit: int | None = Field(default=None, ge=1, le=2000)
    schedule_cron: str = Field(min_length=1, max_length=128)
    enabled: bool = True

    @field_validator("schedule_cron")
    @classmethod
    def _validate_cron(cls, value: str) -> str:
        if not parse_cron(value):
            raise ValueError(f"Invalid cron expression: {value!r}")
        return value


class SmartCollectionCreate(_SmartCollectionCommon):
    pass


class SmartCollectionUpdate(BaseSchema):
    # All fields optional — partial PATCH semantics.
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    media_type: SmartCollectionMediaType | None = None
    builder_type: str | None = None
    builder_config: dict[str, Any] | None = None
    filters: dict[str, Any] | None = None
    sync_mode: SmartCollectionSyncMode | None = None
    item_limit: int | None = Field(default=None, ge=1, le=2000)
    schedule_cron: str | None = None
    enabled: bool | None = None

    @field_validator("schedule_cron")
    @classmethod
    def _validate_cron(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not parse_cron(value):
            raise ValueError(f"Invalid cron expression: {value!r}")
        return value


class SmartCollectionRead(_SmartCollectionCommon):
    guid: uuid.UUID
    list_guid: uuid.UUID | None
    is_system: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_run_status: SmartCollectionRunStatus | None
    last_run_error: str | None
    created_at: datetime
    updated_at: datetime


class SmartCollectionRunRead(BaseSchema):
    guid: uuid.UUID
    rule_guid: uuid.UUID
    started_at: datetime
    completed_at: datetime | None
    status: SmartCollectionRunStatus
    items_fetched: int
    items_filtered: int
    items_resolved: int
    items_added: int
    items_removed: int
    items_unresolved: int
    duration_ms: int | None
    error: str | None


class BuilderInfo(BaseSchema):
    """One entry in the ``GET /smart-collections/builders`` response."""

    type: str
    supported_media_types: list[str]
    requires_api_key: bool
    config_schema: dict[str, Any]
