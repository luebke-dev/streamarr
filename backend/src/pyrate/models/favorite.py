import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Favorite(Base):
    """User favorites for any media item (movies, shows, games, etc.)."""

    __tablename__ = "favorite"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    # User who favorited the item
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.guid", ondelete="CASCADE"), index=True
    )

    # Unified media item reference
    media_item_guid: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_item.guid", ondelete="CASCADE"), index=True
    )

    # Relationships
    user = relationship("User", back_populates="favorites")
    media_item = relationship("MediaItem", back_populates="favorites")

    # Ensure a user can only favorite an item once
    __table_args__ = (
        UniqueConstraint("user_id", "media_item_guid", name="uq_favorite_user_media"),
    )
