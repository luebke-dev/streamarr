"""Media item translations for multi-language metadata support."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, UniqueConstraint, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from streamarr.database import Base


class MediaItemTranslation(Base):
    """Stores translated metadata (title, description, tagline) per language."""

    __tablename__ = "media_item_translation"
    __table_args__ = (
        UniqueConstraint(
            "media_item_guid", "language",
            name="uq_media_translation_item_language",
        ),
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, primary_key=True, default=uuid.uuid4
    )
    media_item_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(index=True, nullable=False)  # ISO 639-1 e.g. "de", "en"
    title: Mapped[str | None] = mapped_column(nullable=True)
    description: Mapped[str | None] = mapped_column(nullable=True)
    tagline: Mapped[str | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    media_item = relationship("MediaItem", back_populates="translations")
