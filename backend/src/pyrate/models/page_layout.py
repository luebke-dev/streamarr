"""Page Layout Models - Configurable page sections for the media browse page."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, ForeignKey, types
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class SectionType(StrEnum):
    """Types of page sections that can be configured."""

    HERO_CAROUSEL = "hero_carousel"
    GENRE = "genre"
    ALL_GENRES = "all_genres"
    LIST = "list"
    DYNAMIC_SEARCH = "dynamic_search"
    LATEST_ITEMS = "latest_items"
    CONTINUE_WATCHING = "continue_watching"
    FAVORITES = "favorites"
    PLATFORMS = "platforms"
    TRAILERS = "trailers"


class PageLayout(Base):
    """A configurable page layout consisting of ordered sections."""

    __tablename__ = "page_layout"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime | None] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    name: Mapped[str] = mapped_column(index=True)
    slug: Mapped[str] = mapped_column(unique=True, index=True)

    # Optional library association — if null, this is a global layout (e.g. "home")
    library_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("libraries.guid", ondelete="SET NULL"),
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(default=True, index=True)

    # Relationships
    library = relationship("Library", lazy="selectin")
    sections = relationship(
        "PageSection",
        back_populates="layout",
        cascade="all, delete-orphan",
        order_by="PageSection.order_index",
        lazy="selectin",
    )


class PageSection(Base):
    """A single section within a page layout."""

    __tablename__ = "page_section"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime | None] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    layout_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("page_layout.guid", ondelete="CASCADE"),
        index=True,
    )

    section_type: Mapped[SectionType] = mapped_column(
        SAEnum(SectionType, values_callable=lambda cls: [e.value for e in cls], native_enum=False),
        index=True,
    )
    order_index: Mapped[int] = mapped_column(default=0)
    title: Mapped[str | None] = mapped_column()
    config: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    is_enabled: Mapped[bool] = mapped_column(default=True)

    # Relationships
    layout = relationship("PageLayout", back_populates="sections")
