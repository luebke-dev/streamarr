"""Pydantic schemas for the mass-operation admin API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from pyrate.models.mass_operation import MassOperationRunStatus
from pyrate.schemas.base import BaseSchema
from pyrate.smart_collections.cron import parse_cron


class _MassOperationCommon(BaseSchema):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    target_filter: dict[str, Any] = Field(default_factory=dict)
    action: dict[str, Any] = Field(default_factory=dict)
    # Mass operations may be manual-only — cron is optional.
    schedule_cron: str | None = Field(default=None, max_length=128)
    enabled: bool = True

    @field_validator("schedule_cron")
    @classmethod
    def _validate_cron(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not parse_cron(value):
            raise ValueError(f"Invalid cron expression: {value!r}")
        return value


class MassOperationCreate(_MassOperationCommon):
    pass


class MassOperationUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    target_filter: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    schedule_cron: str | None = None
    enabled: bool | None = None

    @field_validator("schedule_cron")
    @classmethod
    def _validate_cron(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not parse_cron(value):
            raise ValueError(f"Invalid cron expression: {value!r}")
        return value


class MassOperationRead(_MassOperationCommon):
    guid: uuid.UUID
    is_system: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_run_status: MassOperationRunStatus | None
    last_run_error: str | None
    created_at: datetime
    updated_at: datetime


class MassOperationRunRead(BaseSchema):
    guid: uuid.UUID
    rule_guid: uuid.UUID
    started_at: datetime
    completed_at: datetime | None
    status: MassOperationRunStatus
    dry_run: bool
    items_matched: int
    items_updated: int
    items_skipped: int
    duration_ms: int | None
    error: str | None


class MassOperationDryRunResponse(BaseSchema):
    """Result of an inline (synchronous) dry-run preview."""

    rule_guid: uuid.UUID
    items_matched: int
    items_updated: int
    items_skipped: int
    duration_ms: int
    changed_sample: list[str]


class MassOperationRunResponse(BaseSchema):
    """Result of enqueueing an async run."""

    rule_guid: uuid.UUID
    enqueued: bool
    dry_run: bool
