from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pyrate.schemas.base import BaseSchema

from pyrate.models.notification import NotificationStatus, NotificationType


class NotificationBase(BaseModel):
    """Base Notification Schema"""

    subject: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    notification_type: NotificationType = NotificationType.INFO
    send_email: bool = True
    email_template: str | None = None
    extra_data: str | None = None


class NotificationCreate(NotificationBase):
    """Schema for creating a notification"""

    user_id: UUID


class NotificationUpdate(BaseModel):
    """Schema for updating a notification"""

    status: NotificationStatus | None = None
    read_at: datetime | None = None
    sent_at: datetime | None = None
    error_message: str | None = None


class NotificationResponse(NotificationBase):
    """Schema for notification responses"""

    guid: UUID
    created_at: datetime | None
    updated_at: datetime | None
    user_id: UUID
    status: NotificationStatus
    read_at: datetime | None
    sent_at: datetime | None
    error_message: str | None
    send_attempts: int = 0

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseSchema):
    """Schema for listing notifications (minimal info)"""

    guid: UUID
    created_at: datetime | None
    subject: str
    notification_type: NotificationType
    status: NotificationStatus
    read_at: datetime | None

class NotificationMarkAsRead(BaseModel):
    """Schema for marking notification as read"""

    notification_id: UUID


class NotificationBulkCreate(BaseModel):
    """Schema for creating notifications for multiple users"""

    user_ids: list[UUID]
    subject: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    notification_type: NotificationType = NotificationType.INFO
    send_email: bool = True
    email_template: str | None = None
    extra_data: str | None = None


class AdminNotificationCreate(BaseModel):
    """Schema for admin to send notification to specific users or all users"""

    subject: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    notification_type: NotificationType = NotificationType.SYSTEM
    send_email: bool = True
    email_template: str | None = None
    extra_data: str | None = None
    user_ids: list[UUID] | None = None  # If None, send to all users
    send_to_all: bool = False
