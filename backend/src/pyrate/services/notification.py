"""
Notification Service

This service handles all notification-related operations including
creating, reading, updating, and managing notifications.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import and_, delete, select, update
from sqlalchemy import func as sql_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.notification import Notification, NotificationStatus
from pyrate.models.user import User
from pyrate.schemas.notification import (
    AdminNotificationCreate,
    NotificationCreate,
    NotificationUpdate,
)
from pyrate.services.settings import SettingsService

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for managing notifications"""

    def __init__(self, db: AsyncSession, email_task=None):
        self.db = db
        self.email_task = email_task

    async def create(self, notification_create: NotificationCreate) -> Notification:
        """Create a new notification"""
        db_notification = Notification(
            user_id=notification_create.user_id,
            subject=notification_create.subject,
            message=notification_create.message,
            notification_type=notification_create.notification_type,
            send_email=notification_create.send_email,
            email_template=notification_create.email_template,
            extra_data=notification_create.extra_data,
            status=NotificationStatus.PENDING,
        )
        self.db.add(db_notification)
        await self.db.commit()
        await self.db.refresh(db_notification)
        logger.info("Created notification id=%s user_id=%s type=%s", db_notification.guid, notification_create.user_id, notification_create.notification_type)
        return db_notification

    async def get_by_id(self, notification_id: UUID) -> Notification | None:
        """Get notification by ID"""
        result = await self.db.execute(
            select(Notification)
            .options(selectinload(Notification.user))
            .where(Notification.guid == notification_id)
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        user_id: UUID | None = None,
        status: NotificationStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Notification], int]:
        """
        Get all notifications with optional filters

        Args:
            user_id: Filter by user ID
            status: Filter by status
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (notifications, total_count)
        """
        # Build query
        query = select(Notification).options(selectinload(Notification.user))

        # Apply filters
        filters = []
        if user_id:
            filters.append(Notification.user_id == user_id)
        if status:
            filters.append(Notification.status == status)

        if filters:
            query = query.where(and_(*filters))

        # Get total count using SQL count
        count_query = select(sql_func.count()).select_from(Notification)
        if filters:
            count_query = count_query.where(and_(*filters))
        count_result = await self.db.execute(count_query)
        total_count = count_result.scalar()

        # Apply pagination and order
        query = query.order_by(Notification.created_at.desc())
        query = query.offset(skip).limit(limit)

        # Execute query
        result = await self.db.execute(query)
        notifications = result.scalars().all()

        return list(notifications), total_count

    async def get_user_notifications(
        self,
        user_id: UUID,
        unread_only: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Notification], int]:
        """
        Get notifications for a specific user

        Args:
            user_id: User ID
            unread_only: If True, only return unread notifications
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (notifications, total_count)
        """
        query = select(Notification).where(Notification.user_id == user_id)

        if unread_only:
            query = query.where(Notification.read_at.is_(None))

        # Get total count using SQL count
        count_query = (
            select(sql_func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id)
        )
        if unread_only:
            count_query = count_query.where(Notification.read_at.is_(None))
        count_result = await self.db.execute(count_query)
        total_count = count_result.scalar()

        # Apply pagination and order
        query = query.order_by(Notification.created_at.desc())
        query = query.offset(skip).limit(limit)

        # Execute query
        result = await self.db.execute(query)
        notifications = result.scalars().all()

        return list(notifications), total_count

    async def update(
        self, notification_id: UUID, notification_update: NotificationUpdate
    ) -> Notification | None:
        """Update a notification"""
        notification = await self.get_by_id(notification_id)
        if not notification:
            return None

        update_data = notification_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(notification, key, value)

        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def mark_as_read(self, notification_id: UUID) -> Notification | None:
        """Mark a notification as read"""
        notification = await self.get_by_id(notification_id)
        if not notification:
            logger.warning("Notification not found for mark_as_read: %s", notification_id)
            return None

        notification.status = NotificationStatus.READ
        notification.read_at = datetime.now(UTC)

        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        logger.debug("Marked notification as read id=%s", notification_id)
        return notification

    async def mark_all_as_read(self, user_id: UUID) -> int:
        """
        Mark all unread notifications as read for a user using bulk UPDATE

        Returns:
            Number of notifications marked as read
        """
        # Use bulk UPDATE for better performance
        stmt = (
            update(Notification)
            .where(
                and_(Notification.user_id == user_id, Notification.read_at.is_(None))
            )
            .values(status=NotificationStatus.READ, read_at=datetime.now(UTC))
        )

        result = await self.db.execute(stmt)
        await self.db.commit()

        logger.info("Marked all notifications as read for user_id=%s count=%d", user_id, result.rowcount)
        return result.rowcount

    async def delete(self, notification_id: UUID) -> bool:
        """Delete a notification"""
        notification = await self.get_by_id(notification_id)
        if not notification:
            return False

        await self.db.delete(notification)
        await self.db.commit()
        return True

    async def delete_all_for_user(self, user_id: UUID) -> int:
        """
        Delete all notifications for a user using bulk DELETE

        Returns:
            Number of notifications deleted
        """
        # Use bulk DELETE for better performance
        stmt = delete(Notification).where(Notification.user_id == user_id)

        result = await self.db.execute(stmt)
        await self.db.commit()

        return result.rowcount

    async def get_unread_count(self, user_id: UUID) -> int:
        """Get count of unread notifications for a user"""
        query = (
            select(sql_func.count())
            .select_from(Notification)
            .where(
                and_(Notification.user_id == user_id, Notification.read_at.is_(None))
            )
        )

        result = await self.db.execute(query)
        return result.scalar()

    async def mark_as_sent(
        self,
        notification_id: UUID,
        success: bool = True,
        error_message: str | None = None,
    ) -> Notification | None:
        """Mark a notification as sent (or failed)"""
        notification = await self.get_by_id(notification_id)
        if not notification:
            return None

        notification.send_attempts += 1

        if success:
            notification.status = NotificationStatus.SENT
            notification.sent_at = datetime.now(UTC)
            notification.error_message = None
        else:
            notification.status = NotificationStatus.FAILED
            notification.error_message = error_message

        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def _resolve_target_user_ids(
        self, admin_notification: AdminNotificationCreate
    ) -> list[UUID]:
        """Resolve the list of target user IDs for an admin broadcast.

        If send_to_all is True, fetches all active user GUIDs.
        Otherwise returns the explicitly provided user_ids.

        Args:
            admin_notification: The admin notification request

        Returns:
            List of user UUIDs to send to

        Raises:
            ValueError: If neither user_ids nor send_to_all is specified
        """
        if admin_notification.send_to_all:
            result = await self.db.execute(
                select(User.guid).where(User.is_active.is_(True))
            )
            return list(result.scalars().all())
        elif admin_notification.user_ids:
            return admin_notification.user_ids
        else:
            raise ValueError("Must specify either user_ids or send_to_all")

    async def send_admin_broadcast(
        self, admin_notification: AdminNotificationCreate
    ) -> dict:
        """Create notifications for targeted or all users and queue emails.

        Determines target users (all active users or explicit IDs),
        creates a notification per user, and queues email sending for
        notifications that have send_email enabled.

        Args:
            admin_notification: The admin broadcast request

        Returns:
            Dict with message, count, and recipients fields

        Raises:
            ValueError: If neither user_ids nor send_to_all is specified
        """
        target_user_ids = await self._resolve_target_user_ids(admin_notification)
        logger.info(
            "Sending admin broadcast subject=%r to %d users (send_to_all=%s)",
            admin_notification.subject, len(target_user_ids), admin_notification.send_to_all,
        )

        created_notifications = []
        for user_id in target_user_ids:
            notification_create = NotificationCreate(
                user_id=user_id,
                subject=admin_notification.subject,
                message=admin_notification.message,
                notification_type=admin_notification.notification_type,
                send_email=admin_notification.send_email,
                email_template=admin_notification.email_template,
                extra_data=admin_notification.extra_data,
            )
            notification = await self.create(notification_create)
            created_notifications.append(notification)

            if notification.send_email:
                email_task = self.email_task
                if email_task is None:
                    from pyrate.worker import send_notification_email

                    email_task = send_notification_email
                await email_task.kiq(str(notification.guid))

        return {
            "message": f"Created and sent {len(created_notifications)} notifications",
            "count": len(created_notifications),
            "recipients": len(target_user_ids),
        }


class NotificationDispatchService:
    """Dispatch configured notification event subscriptions."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = SettingsService(db)

    async def dispatch_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        providers = await self.settings.get("notifications.providers", [])
        subscriptions = await self.settings.get(
            "notifications.event_subscriptions", []
        )
        providers_by_id = {
            provider.get("id"): provider
            for provider in providers
            if isinstance(provider, dict) and provider.get("enabled", True)
        }
        matched_provider_ids: set[str] = set()
        for subscription in subscriptions:
            if not isinstance(subscription, dict) or not subscription.get("enabled", True):
                continue
            if subscription.get("event_type") not in {event_type, "*"}:
                continue
            if not self._filters_match(subscription.get("filters", {}), payload or {}):
                continue
            matched_provider_ids.update(subscription.get("provider_ids", []))

        results: list[dict[str, Any]] = []
        for provider_id in sorted(matched_provider_ids):
            provider = providers_by_id.get(provider_id)
            if not provider:
                results.append(
                    {
                        "provider_id": provider_id,
                        "status": "skipped",
                        "detail": "Provider is missing or disabled",
                    }
                )
                continue
            results.append(await self._dispatch_provider(provider, event_type, payload or {}))
        return results

    def _filters_match(self, filters: Any, payload: dict[str, Any]) -> bool:
        if not isinstance(filters, dict) or not filters:
            return True
        for key, expected in filters.items():
            if payload.get(key) != expected:
                return False
        return True

    async def _dispatch_provider(
        self,
        provider: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        provider_type = provider.get("type")
        provider_id = provider.get("id")
        if provider_type == "webhook":
            return await self._dispatch_webhook(provider, event_type, payload)
        if provider_type == "slack":
            return await self._dispatch_slack(provider, event_type, payload)
        if provider_type == "discord":
            return await self._dispatch_discord(provider, event_type, payload)
        if provider_type == "email":
            logger.info(
                "Notification event %s matched email provider %s; "
                "email provider dispatch is handled by notification records",
                event_type,
                provider_id,
            )
            return {
                "provider_id": provider_id,
                "status": "skipped",
                "detail": "Email dispatch is handled by notification records",
            }
        return {
            "provider_id": provider_id,
            "status": "skipped",
            "detail": f"Unsupported provider type: {provider_type}",
        }

    async def _dispatch_webhook(
        self,
        provider: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        provider_id = provider.get("id")
        config = provider.get("config") if isinstance(provider.get("config"), dict) else {}
        url = config.get("url")
        if not url:
            return {
                "provider_id": provider_id,
                "status": "failed",
                "detail": "Webhook URL is missing",
            }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json={"event_type": event_type, "payload": payload},
                )
                response.raise_for_status()
        except Exception as exc:
            logger.warning("Webhook notification provider %s failed: %s", provider_id, exc)
            return {
                "provider_id": provider_id,
                "status": "failed",
                "detail": str(exc),
            }
        return {
            "provider_id": provider_id,
            "status": "sent",
            "detail": "Webhook delivered",
        }

    async def _post_webhook_payload(
        self,
        provider: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        provider_id = provider.get("id")
        config = provider.get("config") if isinstance(provider.get("config"), dict) else {}
        url = config.get("url")
        if not url:
            return {
                "provider_id": provider_id,
                "status": "failed",
                "detail": "Webhook URL is missing",
            }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except Exception as exc:
            logger.warning("Notification provider %s failed: %s", provider_id, exc)
            return {
                "provider_id": provider_id,
                "status": "failed",
                "detail": str(exc),
            }
        return None

    def _event_text(self, event_type: str, payload: dict[str, Any]) -> str:
        message = payload.get("message") or payload.get("title") or event_type
        severity = payload.get("severity")
        if severity:
            return f"[{severity}] {event_type}: {message}"
        return f"{event_type}: {message}"

    async def _dispatch_slack(
        self,
        provider: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        config = provider.get("config") if isinstance(provider.get("config"), dict) else {}
        slack_payload: dict[str, Any] = {
            "text": self._event_text(event_type, payload),
            "attachments": [
                {
                    "fallback": self._event_text(event_type, payload),
                    "fields": [
                        {"title": key, "value": str(value), "short": True}
                        for key, value in sorted(payload.items())
                        if value is not None
                    ][:10],
                }
            ],
        }
        if config.get("username"):
            slack_payload["username"] = config["username"]
        if config.get("channel"):
            slack_payload["channel"] = config["channel"]

        error = await self._post_webhook_payload(provider, slack_payload)
        if error:
            return error
        return {
            "provider_id": provider.get("id"),
            "status": "sent",
            "detail": "Slack webhook delivered",
        }

    async def _dispatch_discord(
        self,
        provider: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        config = provider.get("config") if isinstance(provider.get("config"), dict) else {}
        discord_payload: dict[str, Any] = {
            "content": self._event_text(event_type, payload),
            "embeds": [
                {
                    "title": event_type,
                    "description": payload.get("message") or payload.get("title"),
                    "fields": [
                        {"name": key, "value": str(value), "inline": True}
                        for key, value in sorted(payload.items())
                        if value is not None
                    ][:10],
                }
            ],
        }
        if config.get("username"):
            discord_payload["username"] = config["username"]

        error = await self._post_webhook_payload(provider, discord_payload)
        if error:
            return error
        return {
            "provider_id": provider.get("id"),
            "status": "sent",
            "detail": "Discord webhook delivered",
        }
