"""Pydantic schemas for the overlay-template admin API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from pyrate.models.overlay import OverlayMediaScope, OverlayTarget
from pyrate.schemas.base import BaseSchema


class _OverlayTemplateCommon(BaseSchema):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    media_scope: OverlayMediaScope = OverlayMediaScope.BOTH
    target: OverlayTarget = OverlayTarget.POSTER
    condition: dict[str, Any] | None = None
    elements: list[dict[str, Any]] = Field(default_factory=list)
    z_order: int = 0
    enabled: bool = True


class OverlayTemplateCreate(_OverlayTemplateCommon):
    pass


class OverlayTemplateUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    media_scope: OverlayMediaScope | None = None
    target: OverlayTarget | None = None
    condition: dict[str, Any] | None = None
    elements: list[dict[str, Any]] | None = None
    z_order: int | None = None
    enabled: bool | None = None


class OverlayTemplateRead(_OverlayTemplateCommon):
    guid: uuid.UUID
    version: int
    is_system: bool
    created_at: datetime
    updated_at: datetime


class OverlayApplyResponse(BaseSchema):
    """Response of a single-item apply / preview request."""

    media_guid: uuid.UUID
    target: OverlayTarget
    rendered: bool
    output_path: str | None = None
    source_hash: str | None = None
    templates_evaluated: int = 0
    templates_applied: int = 0
    skipped_reason: str | None = None


class BulkRerenderResponse(BaseSchema):
    template_guid: uuid.UUID
    enqueued: int
