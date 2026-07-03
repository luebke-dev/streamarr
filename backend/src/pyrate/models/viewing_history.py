import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class ViewingHistory(Base):
    __tablename__ = "viewing_history"
    __table_args__ = (
        UniqueConstraint(
            "user_guid", "media_item_guid", name="uq_viewing_history_user_item"
        ),
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # User reference
    user_guid: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.guid", ondelete="CASCADE"), index=True
    )

    # Unified media item reference
    media_item_guid: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_item.guid", ondelete="CASCADE"), index=True
    )

    # Progress tracking
    progress_seconds: Mapped[int] = mapped_column(
        default=0
    )  # Current position in seconds
    duration_seconds: Mapped[int | None] = mapped_column()  # Total content duration
    progress_percentage: Mapped[float] = mapped_column(
        default=0.0
    )  # Calculated percentage

    # Status tracking
    is_completed: Mapped[bool] = mapped_column(default=False)  # Fully watched
    extra_data: Mapped[str | None] = mapped_column(default=None)  # JSON: book CFI position, etc.
    last_watched_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), index=True
    )
    first_watched_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="viewing_history")
    media_item = relationship("MediaItem", back_populates="viewing_history")

    def calculate_progress_percentage(self) -> float:
        """Calculate progress percentage based on current progress and duration."""
        if not self.duration_seconds or self.duration_seconds == 0:
            return 0.0
        return min(100.0, (self.progress_seconds / self.duration_seconds) * 100.0)

    def update_progress(self, progress_seconds: int, duration_seconds: int = None):
        """Update progress and recalculate percentage."""
        self.progress_seconds = progress_seconds
        if duration_seconds:
            self.duration_seconds = duration_seconds
        self.progress_percentage = self.calculate_progress_percentage()

        # Auto-mark as completed if progress is > 90%
        # Also reset completed status if user seeks back to earlier position
        if self.progress_percentage > 90.0:
            self.is_completed = True
        elif self.progress_percentage < 85.0:
            # Reset completed status if user seeks back significantly
            self.is_completed = False
