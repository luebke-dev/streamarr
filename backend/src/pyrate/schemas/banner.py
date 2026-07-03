"""Pydantic schemas for banner API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BannerBase(BaseModel):
    """Base banner schema."""

    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=2000)
    banner_type: str = Field(default="info", pattern="^(info|warning|error|success)$")
    is_active: bool = Field(default=True)
    dismissible: bool = Field(
        default=True, description="Whether users can dismiss this banner"
    )
    start_date: datetime | None = Field(
        None, description="Optional start date/time for banner visibility"
    )
    end_date: datetime | None = Field(
        None, description="Optional end date/time for banner visibility"
    )


class BannerCreate(BannerBase):
    """Schema for creating a banner."""

    pass


class BannerUpdate(BaseModel):
    """Schema for updating a banner."""

    title: str | None = Field(None, min_length=1, max_length=200)
    message: str | None = Field(None, min_length=1, max_length=2000)
    banner_type: str | None = Field(None, pattern="^(info|warning|error|success)$")
    is_active: bool | None = None
    dismissible: bool | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class BannerRead(BannerBase):
    """Schema for reading a banner."""

    guid: uuid.UUID
    created_at: datetime
    created_by_guid: uuid.UUID
    updated_at: datetime | None = None
    is_dismissed: bool = Field(
        default=False, description="Whether the current user has dismissed this banner"
    )

    model_config = ConfigDict(from_attributes=True)


class BannerListResponse(BaseModel):
    """Response for banner list."""

    items: list[BannerRead]
    total: int
    page: int
    per_page: int
    total_pages: int
