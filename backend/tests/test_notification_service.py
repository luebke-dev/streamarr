"""Tests for the NotificationService."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.notification import Notification, NotificationStatus, NotificationType
from streamarr.models.user import User
from streamarr.schemas.notification import NotificationCreate, NotificationUpdate
from streamarr.services.notification import NotificationService


class TestNotificationCRUD:
    """Test basic CRUD operations for notifications."""

    @pytest.mark.asyncio
    async def test_create_notification(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test creating a notification."""
        service = NotificationService(db_session)

        notification_data = NotificationCreate(
            user_id=test_user.guid,
            subject="Test Notification",
            message="This is a test notification",
            notification_type=NotificationType.INFO,
            send_email=False,
        )
        notification = await service.create(notification_data)

        assert notification is not None
        assert notification.subject == "Test Notification"
        assert notification.message == "This is a test notification"
        assert notification.notification_type == NotificationType.INFO
        assert notification.status == NotificationStatus.PENDING
        assert notification.user_id == test_user.guid
        assert notification.send_email is False
        assert notification.read_at is None
        assert notification.sent_at is None

    @pytest.mark.asyncio
    async def test_create_notification_with_email(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test creating a notification with email enabled."""
        service = NotificationService(db_session)

        notification_data = NotificationCreate(
            user_id=test_user.guid,
            subject="Email Notification",
            message="Check your email!",
            notification_type=NotificationType.WARNING,
            send_email=True,
            email_template="default",
        )
        notification = await service.create(notification_data)

        assert notification.send_email is True
        assert notification.email_template == "default"
        assert notification.notification_type == NotificationType.WARNING

    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session: AsyncSession, test_user: User):
        """Test getting a notification by ID."""
        service = NotificationService(db_session)
        created = await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Test",
                message="Message",
            )
        )

        retrieved = await service.get_by_id(created.guid)

        assert retrieved is not None
        assert retrieved.guid == created.guid
        assert retrieved.subject == "Test"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session: AsyncSession):
        """Test getting a non-existent notification."""
        service = NotificationService(db_session)

        result = await service.get_by_id(uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_update_notification(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test updating a notification."""
        service = NotificationService(db_session)
        created = await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Original",
                message="Original message",
            )
        )

        updated = await service.update(
            created.guid,
            NotificationUpdate(status=NotificationStatus.SENT),
        )

        assert updated is not None
        assert updated.status == NotificationStatus.SENT

    @pytest.mark.asyncio
    async def test_update_nonexistent_notification(self, db_session: AsyncSession):
        """Test updating a non-existent notification."""
        service = NotificationService(db_session)

        result = await service.update(
            uuid.uuid4(), NotificationUpdate(status=NotificationStatus.READ)
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_notification(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test deleting a notification."""
        service = NotificationService(db_session)
        created = await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Delete me",
                message="Goodbye",
            )
        )

        result = await service.delete(created.guid)

        assert result is True
        deleted = await service.get_by_id(created.guid)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_notification(self, db_session: AsyncSession):
        """Test deleting a non-existent notification."""
        service = NotificationService(db_session)

        result = await service.delete(uuid.uuid4())

        assert result is False


class TestNotificationReadStatus:
    """Test notification read/unread status management."""

    @pytest.mark.asyncio
    async def test_mark_as_read(self, db_session: AsyncSession, test_user: User):
        """Test marking a notification as read."""
        service = NotificationService(db_session)
        notification = await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Read me",
                message="Please read this",
            )
        )

        result = await service.mark_as_read(notification.guid)

        assert result is not None
        assert result.status == NotificationStatus.READ
        assert result.read_at is not None

    @pytest.mark.asyncio
    async def test_mark_as_read_nonexistent(self, db_session: AsyncSession):
        """Test marking a non-existent notification as read."""
        service = NotificationService(db_session)

        result = await service.mark_as_read(uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_mark_all_as_read(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test marking all notifications as read for a user."""
        service = NotificationService(db_session)

        for i in range(3):
            await service.create(
                NotificationCreate(
                    user_id=test_user.guid,
                    subject=f"Notification {i}",
                    message=f"Message {i}",
                )
            )

        count = await service.mark_all_as_read(test_user.guid)

        assert count == 3

    @pytest.mark.asyncio
    async def test_mark_all_as_read_no_unread(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test marking all as read when there are none unread."""
        service = NotificationService(db_session)

        count = await service.mark_all_as_read(test_user.guid)

        assert count == 0

    @pytest.mark.asyncio
    async def test_get_unread_count(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test getting unread notification count."""
        service = NotificationService(db_session)

        # Create 3 notifications
        notifications = []
        for i in range(3):
            n = await service.create(
                NotificationCreate(
                    user_id=test_user.guid,
                    subject=f"Notification {i}",
                    message=f"Message {i}",
                )
            )
            notifications.append(n)

        # Mark one as read
        await service.mark_as_read(notifications[0].guid)

        unread_count = await service.get_unread_count(test_user.guid)

        assert unread_count == 2


class TestNotificationListing:
    """Test notification listing and filtering."""

    @pytest.mark.asyncio
    async def test_get_user_notifications(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test getting notifications for a specific user."""
        service = NotificationService(db_session)

        # Create notifications for different users
        await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="User 1 notification",
                message="For user 1",
            )
        )
        await service.create(
            NotificationCreate(
                user_id=test_user2.guid,
                subject="User 2 notification",
                message="For user 2",
            )
        )

        notifications, total = await service.get_user_notifications(test_user.guid)

        assert total == 1
        assert len(notifications) == 1
        assert notifications[0].subject == "User 1 notification"

    @pytest.mark.asyncio
    async def test_get_user_notifications_unread_only(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test getting only unread notifications."""
        service = NotificationService(db_session)

        n1 = await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Read notification",
                message="Already read",
            )
        )
        await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Unread notification",
                message="Not yet read",
            )
        )
        await service.mark_as_read(n1.guid)

        notifications, total = await service.get_user_notifications(
            test_user.guid, unread_only=True
        )

        assert total == 1
        assert notifications[0].subject == "Unread notification"

    @pytest.mark.asyncio
    async def test_get_user_notifications_pagination(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test paginated notification listing."""
        service = NotificationService(db_session)

        for i in range(5):
            await service.create(
                NotificationCreate(
                    user_id=test_user.guid,
                    subject=f"Notification {i}",
                    message=f"Message {i}",
                )
            )

        notifications, total = await service.get_user_notifications(
            test_user.guid, skip=0, limit=2
        )

        assert total == 5
        assert len(notifications) == 2

    @pytest.mark.asyncio
    async def test_get_all_notifications(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test getting all notifications across users."""
        service = NotificationService(db_session)

        await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Notification 1",
                message="Message 1",
            )
        )
        await service.create(
            NotificationCreate(
                user_id=test_user2.guid,
                subject="Notification 2",
                message="Message 2",
            )
        )

        notifications, total = await service.get_all()

        assert total == 2
        assert len(notifications) == 2

    @pytest.mark.asyncio
    async def test_get_all_filter_by_user(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test filtering notifications by user."""
        service = NotificationService(db_session)

        await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="User 1",
                message="M",
            )
        )
        await service.create(
            NotificationCreate(
                user_id=test_user2.guid,
                subject="User 2",
                message="M",
            )
        )

        notifications, total = await service.get_all(user_id=test_user.guid)

        assert total == 1

    @pytest.mark.asyncio
    async def test_get_all_filter_by_status(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test filtering notifications by status."""
        service = NotificationService(db_session)

        n1 = await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Pending",
                message="M",
            )
        )
        n2 = await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Read",
                message="M",
            )
        )
        await service.mark_as_read(n2.guid)

        pending, pending_total = await service.get_all(
            status=NotificationStatus.PENDING
        )
        read, read_total = await service.get_all(status=NotificationStatus.READ)

        assert pending_total == 1
        assert read_total == 1


class TestNotificationSendStatus:
    """Test notification send tracking."""

    @pytest.mark.asyncio
    async def test_mark_as_sent_success(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test marking a notification as successfully sent."""
        service = NotificationService(db_session)
        notification = await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="To send",
                message="Send me",
                send_email=True,
            )
        )

        result = await service.mark_as_sent(notification.guid, success=True)

        assert result is not None
        assert result.status == NotificationStatus.SENT
        assert result.sent_at is not None
        assert result.send_attempts == 1
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_mark_as_sent_failure(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test marking a notification send as failed."""
        service = NotificationService(db_session)
        notification = await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Failing send",
                message="Will fail",
                send_email=True,
            )
        )

        result = await service.mark_as_sent(
            notification.guid,
            success=False,
            error_message="SMTP connection refused",
        )

        assert result is not None
        assert result.status == NotificationStatus.FAILED
        assert result.send_attempts == 1
        assert result.error_message == "SMTP connection refused"

    @pytest.mark.asyncio
    async def test_mark_as_sent_nonexistent(self, db_session: AsyncSession):
        """Test marking send for non-existent notification."""
        service = NotificationService(db_session)

        result = await service.mark_as_sent(uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_send_attempts_increment(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that send attempts increment correctly."""
        service = NotificationService(db_session)
        notification = await service.create(
            NotificationCreate(
                user_id=test_user.guid,
                subject="Retry",
                message="Will retry",
                send_email=True,
            )
        )

        # First attempt fails
        await service.mark_as_sent(
            notification.guid, success=False, error_message="Timeout"
        )
        # Second attempt succeeds
        result = await service.mark_as_sent(notification.guid, success=True)

        assert result.send_attempts == 2
        assert result.status == NotificationStatus.SENT


class TestNotificationBulkOperations:
    """Test bulk notification operations."""

    @pytest.mark.asyncio
    async def test_delete_all_for_user(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test deleting all notifications for a user."""
        service = NotificationService(db_session)

        # Create notifications for both users
        for i in range(3):
            await service.create(
                NotificationCreate(
                    user_id=test_user.guid,
                    subject=f"User 1 - {i}",
                    message="M",
                )
            )
        await service.create(
            NotificationCreate(
                user_id=test_user2.guid,
                subject="User 2",
                message="M",
            )
        )

        deleted_count = await service.delete_all_for_user(test_user.guid)

        assert deleted_count == 3

        # User 2's notifications should still exist
        user2_notifications, total = await service.get_user_notifications(
            test_user2.guid
        )
        assert total == 1

    @pytest.mark.asyncio
    async def test_delete_all_for_user_empty(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test deleting notifications for user with none."""
        service = NotificationService(db_session)

        deleted_count = await service.delete_all_for_user(test_user.guid)

        assert deleted_count == 0
