"""Media marker models for intro/outro/credits detection."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from streamarr.database import Base


class MarkerType(StrEnum):
    INTRO = "intro"
    OUTRO = "outro"
    CREDITS = "credits"
    SONG = "song"
    AD = "ad"


class MarkerSource(StrEnum):
    MANUAL = "manual"
    CHROMAPRINT = "chromaprint"
    SILENCE = "silence"


class MediaMarker(Base):
    """Marks intro/outro/credits segments on a media item."""

    __tablename__ = "media_marker"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, primary_key=True, default=uuid.uuid4
    )
    media_item_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    marker_type: Mapped[MarkerType] = mapped_column(
        SQLEnum(MarkerType, values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    source: Mapped[MarkerSource] = mapped_column(
        SQLEnum(MarkerSource, values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=MarkerSource.MANUAL,
    )
    start_seconds: Mapped[float] = mapped_column(nullable=False)
    end_seconds: Mapped[float] = mapped_column(nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    label: Mapped[str | None] = mapped_column(nullable=True)  # e.g. song title

    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    media_item = relationship("MediaItem", back_populates="markers")
