import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class NotificationType(StrEnum):
    """Types of notifications"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    SYSTEM = "system"


class NotificationStatus(StrEnum):
    """Status of notification delivery"""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    READ = "read"


class Notification(Base):
    """Model for user notifications"""

    __tablename__ = "notification"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Recipient user
    user_id: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, ForeignKey("user.guid", ondelete="CASCADE"), nullable=False, index=True
    )

    # Length caps so an unbounded notification can't poison the table.
    # Existing rows are shorter than these limits, so no migration data loss.

    # Notification type
    notification_type: Mapped[NotificationType] = mapped_column(
        default=NotificationType.INFO
    )

    # Notification status
    status: Mapped[NotificationStatus] = mapped_column(
        default=NotificationStatus.PENDING, index=True
    )

    # Subject/title of the notification
    subject: Mapped[str] = mapped_column(types.String(500))

    # Message body (plain text or HTML)
    message: Mapped[str] = mapped_column(types.Text())

    # Whether this notification should be sent via email
    send_email: Mapped[bool] = mapped_column(default=True)

    # Email template to use (optional, if None uses default)
    email_template: Mapped[str | None] = mapped_column()

    # When the notification was read (if read)
    read_at: Mapped[datetime | None] = mapped_column()

    # When the email was sent (if sent)
    sent_at: Mapped[datetime | None] = mapped_column()

    # Error message if failed to send
    error_message: Mapped[str | None] = mapped_column()

    # Number of send attempts
    send_attempts: Mapped[int] = mapped_column(default=0)

    # Optional extra data as JSON string
    extra_data: Mapped[str | None] = mapped_column()

    # Relationships
    user = relationship("User", back_populates="notifications")
