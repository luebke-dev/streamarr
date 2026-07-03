import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class MediaWatch(Base):
    """User watchlist entry — user wants to be notified when a media item becomes available."""

    __tablename__ = "media_watch"
    __table_args__ = (
        UniqueConstraint("user_guid", "media_item_guid", name="uq_media_watch_user_item"),
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    user_guid: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.guid", ondelete="CASCADE"), index=True
    )
    media_item_guid: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_item.guid", ondelete="CASCADE"), index=True
    )

    user = relationship("User")
    media_item = relationship("MediaItem")
