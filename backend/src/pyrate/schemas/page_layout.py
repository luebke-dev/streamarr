"""Page Layout Schemas - Request/Response models for page layout configuration."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pyrate.models.page_layout import SectionType
from pyrate.schemas.base import BaseSchema

# ---------------------------------------------------------------------------
# PageSection schemas
# ---------------------------------------------------------------------------


class PageSectionBase(BaseModel):
    section_type: SectionType
    order_index: int = 0
    title: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True


class PageSectionCreate(PageSectionBase):
    pass


class PageSectionUpdate(BaseModel):
    section_type: SectionType | None = None
    order_index: int | None = None
    title: str | None = None
    config: dict[str, Any] | None = None
    is_enabled: bool | None = None


class PageSectionRead(PageSectionBase):
    model_config = ConfigDict(from_attributes=True)

    guid: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PageSectionRendered(PageSectionRead):
    rendered_items: list[dict[str, Any]] = Field(default_factory=list)
    rendered_prefix_lists: list[dict[str, Any]] = Field(default_factory=list)
    rendered_list_guid: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# PageLayout schemas
# ---------------------------------------------------------------------------


class PageLayoutBase(BaseModel):
    name: str
    slug: str
    library_guid: uuid.UUID | None = None
    is_active: bool = True


class PageLayoutCreate(PageLayoutBase):
    sections: list[PageSectionCreate] = Field(default_factory=list)


class PageLayoutUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    library_guid: uuid.UUID | None = None
    is_active: bool | None = None


class PageLayoutRead(PageLayoutBase):
    model_config = ConfigDict(from_attributes=True)

    guid: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    sections: list[PageSectionRead] = Field(default_factory=list)


class PageLayoutRenderedRead(PageLayoutBase):
    model_config = ConfigDict(from_attributes=True)

    guid: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    sections: list[PageSectionRendered] = Field(default_factory=list)
    cache_status: str = "fresh"
    # Count of sections the server skipped because they had no content
    # for this user. Surfaced for admin/debug tooling — frontend doesn't
    # need to react.
    empty_sections_dropped: int = 0


class PageLayoutSummary(BaseSchema):
    """Lightweight layout representation for list views."""

    guid: uuid.UUID
    name: str
    slug: str
    library_guid: uuid.UUID | None = None
    is_active: bool
    section_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ReorderSectionsRequest(BaseModel):
    """Request body for reordering sections."""

    section_order: list[uuid.UUID] = Field(
        ..., description="Ordered list of section GUIDs"
    )
