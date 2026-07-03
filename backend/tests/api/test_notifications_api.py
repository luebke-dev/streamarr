"""Tests for notifications API endpoints (/api/notifications/*)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models import Notification, NotificationType, User
from pyrate.models.notification import NotificationStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _create_notification(
    db_session: AsyncSession,
    user: User,
    *,
    subject: str = "Test Notification",
    is_read: bool = False,
) -> Notification:
    notif = Notification(
        guid=uuid.uuid4(),
        user_id=user.guid,
        subject=subject,
        message="This is a test notification body.",
        notification_type=NotificationType.INFO,
        status=NotificationStatus.READ if is_read else NotificationStatus.PENDING,
        send_email=False,
        read_at=datetime.now(UTC) if is_read else None,
    )
    db_session.add(notif)
    await db_session.commit()
    await db_session.refresh(notif)
    return notif


# ---------------------------------------------------------------------------
# GET /api/notifications/
# ---------------------------------------------------------------------------
class TestNotificationSettings:
    async def test_regular_user_cannot_view_notification_catalogs(
        self, client: AsyncClient, user_headers
    ):
        provider_types = await client.get(
            "/api/notifications/admin/provider-types",
            headers=user_headers,
        )
        events = await client.get(
            "/api/notifications/admin/events",
            headers=user_headers,
        )

        assert provider_types.status_code == 403
        assert events.status_code == 403

    async def test_admin_can_view_provider_and_event_catalogs(
        self, client: AsyncClient, admin_headers
    ):
        provider_types = await client.get(
            "/api/notifications/admin/provider-types",
            headers=admin_headers,
        )
        events = await client.get(
            "/api/notifications/admin/events",
            headers=admin_headers,
        )

        assert provider_types.status_code == 200
        provider_type_ids = {item["type"] for item in provider_types.json()}
        assert {"webhook", "slack", "discord", "email"}.issubset(provider_type_ids)

        assert events.status_code == 200
        event_types = {item["event_type"] for item in events.json()}
        assert "activity.created" in event_types
        assert "offline.item_update" in event_types
        assert "session.command" in event_types
        assert "cast.command" in event_types
        assert "subtitle.download" in event_types
        assert "backup.database_restore" in event_types
        assert "settings.network_update" in event_types

    async def test_admin_event_catalog_includes_enabled_plugin_events(
        self, client: AsyncClient, admin_headers
    ):
        install = await client.post(
            "/api/plugins/installed/audit-plugin",
            headers=admin_headers,
            json={
                "name": "Audit Plugin",
                "version": "1.0.0",
                "notification_events": [
                    {
                        "event_type": "plugin.audit.alert",
                        "name": "Plugin Audit Alert",
                        "description": "A plugin-defined audit event.",
                        "payload_schema": {
                            "severity": {"type": "string", "required": False}
                        },
                        "default_severity": "warning",
                    }
                ],
            },
        )
        assert install.status_code == 200

        events = await client.get(
            "/api/notifications/admin/events",
            headers=admin_headers,
        )

        assert events.status_code == 200
        plugin_event = next(
            item
            for item in events.json()
            if item["event_type"] == "plugin.audit.alert"
        )
        assert plugin_event["name"] == "Plugin Audit Alert"
        assert plugin_event["default_severity"] == "warning"

    async def test_admin_event_catalog_ignores_disabled_plugin_events(
        self, client: AsyncClient, admin_headers
    ):
        install = await client.post(
            "/api/plugins/installed/disabled-plugin",
            headers=admin_headers,
            json={
                "name": "Disabled Plugin",
                "version": "1.0.0",
                "enabled": False,
                "notification_events": [
                    {
                        "event_type": "plugin.disabled.alert",
                        "name": "Disabled Plugin Alert",
                        "description": "A disabled plugin event.",
                    }
                ],
            },
        )
        assert install.status_code == 200

        events = await client.get(
            "/api/notifications/admin/events",
            headers=admin_headers,
        )

        assert events.status_code == 200
        event_types = {item["event_type"] for item in events.json()}
        assert "plugin.disabled.alert" not in event_types

    async def test_regular_user_cannot_view_notification_settings(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.get("/api/notifications/admin/settings", headers=user_headers)

        assert resp.status_code == 403

    async def test_admin_get_default_notification_settings(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.get("/api/notifications/admin/settings", headers=admin_headers)

        assert resp.status_code == 200
        assert resp.json() == {"providers": [], "event_subscriptions": []}

    async def test_admin_update_notification_settings(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            "/api/notifications/admin/settings",
            headers=admin_headers,
            json={
                "providers": [
                    {
                        "id": "email-main",
                        "type": "email",
                        "enabled": True,
                        "config": {"template": "default"},
                    },
                    {
                        "id": "webhook-admin",
                        "type": "webhook",
                        "enabled": False,
                        "config": {"url": "https://example.invalid/hook"},
                    },
                ],
                "event_subscriptions": [
                    {
                        "event_type": "task.failed",
                        "provider_ids": ["email-main", "webhook-admin"],
                        "enabled": True,
                        "filters": {"severity": "error"},
                    }
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["providers"][0]["id"] == "email-main"
        assert data["providers"][1]["enabled"] is False
        assert data["event_subscriptions"][0]["event_type"] == "task.failed"

        fetched = await client.get(
            "/api/notifications/admin/settings",
            headers=admin_headers,
        )
        assert fetched.status_code == 200
        assert fetched.json()["event_subscriptions"][0]["provider_ids"] == [
            "email-main",
            "webhook-admin",
        ]

    async def test_notification_settings_reject_unknown_provider(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            "/api/notifications/admin/settings",
            headers=admin_headers,
            json={
                "providers": [],
                "event_subscriptions": [
                    {
                        "event_type": "activity.created",
                        "provider_ids": ["missing"],
                    }
                ],
            },
        )

        assert resp.status_code == 400
        assert "missing" in resp.json()["detail"]

    async def test_notification_settings_reject_unsupported_provider_type(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            "/api/notifications/admin/settings",
            headers=admin_headers,
            json={
                "providers": [
                    {
                        "id": "unknown",
                        "type": "sms",
                        "enabled": True,
                        "config": {},
                    }
                ],
                "event_subscriptions": [],
            },
        )

        assert resp.status_code == 400
        assert "sms" in resp.json()["detail"]

    async def test_admin_dispatches_event_to_matching_webhook(
        self, client: AsyncClient, admin_headers
    ):
        settings = await client.put(
            "/api/notifications/admin/settings",
            headers=admin_headers,
            json={
                "providers": [
                    {
                        "id": "hook",
                        "type": "webhook",
                        "enabled": True,
                        "config": {"url": "https://example.invalid/hook"},
                    }
                ],
                "event_subscriptions": [
                    {
                        "event_type": "task.failed",
                        "provider_ids": ["hook"],
                        "filters": {"severity": "error"},
                    }
                ],
            },
        )
        assert settings.status_code == 200

        with patch("pyrate.services.notification.httpx.AsyncClient") as mock_client:
            response = AsyncMock()
            response.raise_for_status = Mock(return_value=None)
            mock_client.return_value.__aenter__.return_value.post.return_value = response

            resp = await client.post(
                "/api/notifications/admin/dispatch-event",
                headers=admin_headers,
                json={
                    "event_type": "task.failed",
                    "payload": {"severity": "error", "task_id": "reindex_all"},
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["event_type"] == "task.failed"
        assert data["results"] == [
            {"provider_id": "hook", "status": "sent", "detail": "Webhook delivered"}
        ]
        mock_client.return_value.__aenter__.return_value.post.assert_awaited_once()

    async def test_dispatch_skips_when_filters_do_not_match(
        self, client: AsyncClient, admin_headers
    ):
        await client.put(
            "/api/notifications/admin/settings",
            headers=admin_headers,
            json={
                "providers": [
                    {
                        "id": "hook",
                        "type": "webhook",
                        "enabled": True,
                        "config": {"url": "https://example.invalid/hook"},
                    }
                ],
                "event_subscriptions": [
                    {
                        "event_type": "task.failed",
                        "provider_ids": ["hook"],
                        "filters": {"severity": "error"},
                    }
                ],
            },
        )

        resp = await client.post(
            "/api/notifications/admin/dispatch-event",
            headers=admin_headers,
            json={
                "event_type": "task.failed",
                "payload": {"severity": "info"},
            },
        )

        assert resp.status_code == 200
        assert resp.json()["results"] == []

    async def test_admin_dispatches_event_to_slack_provider(
        self, client: AsyncClient, admin_headers
    ):
        await client.put(
            "/api/notifications/admin/settings",
            headers=admin_headers,
            json={
                "providers": [
                    {
                        "id": "slack-main",
                        "type": "slack",
                        "enabled": True,
                        "config": {
                            "url": "https://example.invalid/slack",
                            "username": "pyrate",
                        },
                    }
                ],
                "event_subscriptions": [
                    {
                        "event_type": "offline.item_update",
                        "provider_ids": ["slack-main"],
                    }
                ],
            },
        )

        with patch("pyrate.services.notification.httpx.AsyncClient") as mock_client:
            response = AsyncMock()
            response.raise_for_status = Mock(return_value=None)
            mock_client.return_value.__aenter__.return_value.post.return_value = response

            resp = await client.post(
                "/api/notifications/admin/dispatch-event",
                headers=admin_headers,
                json={
                    "event_type": "offline.item_update",
                    "payload": {
                        "severity": "info",
                        "message": "Movie is ready offline",
                        "media_guid": str(uuid.uuid4()),
                    },
                },
            )

        assert resp.status_code == 200
        assert resp.json()["results"] == [
            {
                "provider_id": "slack-main",
                "status": "sent",
                "detail": "Slack webhook delivered",
            }
        ]
        post = mock_client.return_value.__aenter__.return_value.post
        post.assert_awaited_once()
        payload = post.await_args.kwargs["json"]
        assert payload["username"] == "pyrate"
        assert "offline.item_update" in payload["text"]

    async def test_admin_dispatches_session_command_event(
        self, client: AsyncClient, admin_headers
    ):
        await client.put(
            "/api/notifications/admin/settings",
            headers=admin_headers,
            json={
                "providers": [
                    {
                        "id": "hook",
                        "type": "webhook",
                        "enabled": True,
                        "config": {"url": "https://example.invalid/hook"},
                    }
                ],
                "event_subscriptions": [
                    {
                        "event_type": "session.command",
                        "provider_ids": ["hook"],
                        "filters": {"command": "play_queue"},
                    }
                ],
            },
        )

        with patch("pyrate.services.notification.httpx.AsyncClient") as mock_client:
            response = AsyncMock()
            response.raise_for_status = Mock(return_value=None)
            mock_client.return_value.__aenter__.return_value.post.return_value = response

            resp = await client.post(
                "/api/notifications/admin/dispatch-event",
                headers=admin_headers,
                json={
                    "event_type": "session.command",
                    "payload": {
                        "device_id": "living-room",
                        "command": "play_queue",
                        "status": "sent",
                    },
                },
            )

        assert resp.status_code == 200
        assert resp.json()["results"] == [
            {"provider_id": "hook", "status": "sent", "detail": "Webhook delivered"}
        ]
        post = mock_client.return_value.__aenter__.return_value.post
        assert post.await_args.kwargs["json"]["event_type"] == "session.command"


# ---------------------------------------------------------------------------
# GET /api/notifications/
# ---------------------------------------------------------------------------
class TestListNotifications:
    async def test_list_empty(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/notifications/", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_own_notifications(self, client: AsyncClient, db_session, test_user, user_headers):
        await _create_notification(db_session, test_user, subject="N1")
        await _create_notification(db_session, test_user, subject="N2")

        resp = await client.get("/api/notifications/", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_list_unread_only(self, client: AsyncClient, db_session, test_user, user_headers):
        await _create_notification(db_session, test_user, subject="Unread", is_read=False)
        await _create_notification(db_session, test_user, subject="Read", is_read=True)

        resp = await client.get("/api/notifications/?unread_only=true", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    async def test_list_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/notifications/")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/notifications/unread-count
# ---------------------------------------------------------------------------
class TestUnreadCount:
    async def test_unread_count_zero(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/notifications/unread-count", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    async def test_unread_count(self, client: AsyncClient, db_session, test_user, user_headers):
        await _create_notification(db_session, test_user)
        await _create_notification(db_session, test_user)

        resp = await client.get("/api/notifications/unread-count", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 2


# ---------------------------------------------------------------------------
# GET /api/notifications/{notification_id}
# ---------------------------------------------------------------------------
class TestGetNotification:
    async def test_get_own_notification(self, client: AsyncClient, db_session, test_user, user_headers):
        notif = await _create_notification(db_session, test_user)

        resp = await client.get(f"/api/notifications/{notif.guid}", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["subject"] == "Test Notification"

    async def test_get_other_users_notification(
        self, client: AsyncClient, db_session, test_superuser, user_headers
    ):
        notif = await _create_notification(db_session, test_superuser)

        resp = await client.get(f"/api/notifications/{notif.guid}", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_notification_not_found(self, client: AsyncClient, user_headers):
        fake = uuid.uuid4()
        resp = await client.get(f"/api/notifications/{fake}", headers=user_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/notifications/{notification_id}/read
# ---------------------------------------------------------------------------
class TestMarkAsRead:
    async def test_mark_as_read(self, client: AsyncClient, db_session, test_user, user_headers):
        notif = await _create_notification(db_session, test_user)

        resp = await client.put(f"/api/notifications/{notif.guid}/read", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "read"

    async def test_mark_as_read_not_found(self, client: AsyncClient, user_headers):
        fake = uuid.uuid4()
        resp = await client.put(f"/api/notifications/{fake}/read", headers=user_headers)
        assert resp.status_code == 404

    async def test_mark_other_users_as_read(self, client: AsyncClient, db_session, test_superuser, user_headers):
        notif = await _create_notification(db_session, test_superuser)

        resp = await client.put(f"/api/notifications/{notif.guid}/read", headers=user_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /api/notifications/mark-all-read
# ---------------------------------------------------------------------------
class TestMarkAllRead:
    async def test_mark_all_read(self, client: AsyncClient, db_session, test_user, user_headers):
        await _create_notification(db_session, test_user, subject="A")
        await _create_notification(db_session, test_user, subject="B")

        resp = await client.put("/api/notifications/mark-all-read", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 2


# ---------------------------------------------------------------------------
# DELETE /api/notifications/{notification_id}
# ---------------------------------------------------------------------------
class TestDeleteNotification:
    async def test_delete_own(self, client: AsyncClient, db_session, test_user, user_headers):
        notif = await _create_notification(db_session, test_user)

        resp = await client.delete(f"/api/notifications/{notif.guid}", headers=user_headers)
        assert resp.status_code == 204

    async def test_delete_other_users(self, client: AsyncClient, db_session, test_superuser, user_headers):
        notif = await _create_notification(db_session, test_superuser)

        resp = await client.delete(f"/api/notifications/{notif.guid}", headers=user_headers)
        assert resp.status_code == 403

    async def test_delete_not_found(self, client: AsyncClient, user_headers):
        fake = uuid.uuid4()
        resp = await client.delete(f"/api/notifications/{fake}", headers=user_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/notifications/
# ---------------------------------------------------------------------------
class TestDeleteAllNotifications:
    async def test_delete_all(self, client: AsyncClient, db_session, test_user, user_headers):
        await _create_notification(db_session, test_user, subject="A")
        await _create_notification(db_session, test_user, subject="B")

        resp = await client.delete("/api/notifications/", headers=user_headers)
        assert resp.status_code == 204

        # Verify
        resp2 = await client.get("/api/notifications/", headers=user_headers)
        assert resp2.json() == []


# ---------------------------------------------------------------------------
# POST /api/notifications/ (create notification)
# ---------------------------------------------------------------------------
class TestCreateNotification:
    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_create_own_notification(
        self, mock_email, client: AsyncClient, test_user: User, user_headers
    ):
        """User can create a notification for themselves."""
        mock_email.kiq = AsyncMock()

        resp = await client.post(
            "/api/notifications/",
            headers=user_headers,
            json={
                "user_id": str(test_user.guid),
                "subject": "Self Notification",
                "message": "A notification for myself.",
                "notification_type": "info",
                "send_email": False,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["subject"] == "Self Notification"

    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_create_notification_for_other_user_forbidden(
        self,
        mock_email,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        user_headers,
    ):
        """Regular user cannot create notification for another user."""
        mock_email.kiq = AsyncMock()

        resp = await client.post(
            "/api/notifications/",
            headers=user_headers,
            json={
                "user_id": str(test_superuser.guid),
                "subject": "For Admin",
                "message": "Should fail.",
                "notification_type": "info",
                "send_email": False,
            },
        )
        assert resp.status_code == 403

    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_admin_create_notification_for_user(
        self,
        mock_email,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        admin_headers,
    ):
        """Admin can create notification for any user."""
        mock_email.kiq = AsyncMock()

        resp = await client.post(
            "/api/notifications/",
            headers=admin_headers,
            json={
                "user_id": str(test_user.guid),
                "subject": "Admin Notice",
                "message": "From admin to user.",
                "notification_type": "info",
                "send_email": False,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["subject"] == "Admin Notice"

    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_create_notification_with_email(
        self, mock_email, client: AsyncClient, test_user: User, user_headers
    ):
        """When send_email=True, email task is queued."""
        mock_email.kiq = AsyncMock()

        resp = await client.post(
            "/api/notifications/",
            headers=user_headers,
            json={
                "user_id": str(test_user.guid),
                "subject": "Email Test",
                "message": "This should trigger email.",
                "notification_type": "info",
                "send_email": True,
            },
        )
        assert resp.status_code == 201
        mock_email.kiq.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/notifications/bulk (bulk create)
# ---------------------------------------------------------------------------
class TestBulkCreateNotifications:
    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_bulk_create_as_admin(
        self,
        mock_email,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        admin_headers,
    ):
        """Admin can bulk-create notifications."""
        mock_email.kiq = AsyncMock()

        resp = await client.post(
            "/api/notifications/bulk",
            headers=admin_headers,
            json={
                "user_ids": [str(test_user.guid), str(test_superuser.guid)],
                "subject": "Bulk Notice",
                "message": "Bulk message body.",
                "notification_type": "info",
                "send_email": False,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["count"] == 2

    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_bulk_create_as_user_forbidden(
        self,
        mock_email,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        """Regular user cannot bulk create."""
        mock_email.kiq = AsyncMock()

        resp = await client.post(
            "/api/notifications/bulk",
            headers=user_headers,
            json={
                "user_ids": [str(test_user.guid)],
                "subject": "Bulk Fail",
                "message": "Should be denied.",
            },
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/notifications/admin/all
# ---------------------------------------------------------------------------
class TestAdminGetAllNotifications:
    async def test_admin_get_all(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        test_superuser: User,
        admin_headers,
    ):
        """Admin can get all notifications across users."""
        await _create_notification(db_session, test_user, subject="User Notif")
        await _create_notification(db_session, test_superuser, subject="Admin Notif")

        resp = await client.get(
            "/api/notifications/admin/all", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    async def test_admin_get_all_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        """Regular user cannot access admin endpoint."""
        resp = await client.get(
            "/api/notifications/admin/all", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_admin_get_all_with_status_filter(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        test_superuser: User,
        admin_headers,
    ):
        """Admin can filter notifications by status."""
        await _create_notification(db_session, test_user, is_read=False)
        await _create_notification(db_session, test_user, is_read=True)

        resp = await client.get(
            "/api/notifications/admin/all?status_filter=read",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # All returned should be read
        for notif in data:
            assert notif["status"] == "read"


# ---------------------------------------------------------------------------
# Pagination tests with filters
# ---------------------------------------------------------------------------
class TestNotificationPagination:
    async def test_list_with_skip_and_limit(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Pagination via skip/limit params."""
        for i in range(5):
            await _create_notification(db_session, test_user, subject=f"N{i}")

        resp = await client.get(
            "/api/notifications/?skip=0&limit=2", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_list_unread_only_filter(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Filter returns only unread notifications."""
        await _create_notification(db_session, test_user, subject="Unread1", is_read=False)
        await _create_notification(db_session, test_user, subject="Unread2", is_read=False)
        await _create_notification(db_session, test_user, subject="Read1", is_read=True)

        resp = await client.get(
            "/api/notifications/?unread_only=true", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2


# ---------------------------------------------------------------------------
# POST /api/notifications/ — with send_email=True (queues email)
# ---------------------------------------------------------------------------
class TestCreateNotificationWithEmail:
    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_create_with_email_sends_to_kiq(
        self, mock_email, client: AsyncClient, test_user: User, user_headers
    ):
        """Creating notification with send_email=True queues email task."""
        mock_email.kiq = AsyncMock()
        resp = await client.post(
            "/api/notifications/",
            headers=user_headers,
            json={
                "user_id": str(test_user.guid),
                "subject": "Email Queue Test",
                "message": "Should queue email.",
                "notification_type": "info",
                "send_email": True,
            },
        )
        assert resp.status_code == 201
        mock_email.kiq.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/notifications/bulk — with email
# ---------------------------------------------------------------------------
class TestBulkCreateWithEmail:
    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_bulk_create_with_email(
        self,
        mock_email,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        admin_headers,
    ):
        """Bulk create with send_email=True queues emails for each user."""
        mock_email.kiq = AsyncMock()
        resp = await client.post(
            "/api/notifications/bulk",
            headers=admin_headers,
            json={
                "user_ids": [str(test_user.guid), str(test_superuser.guid)],
                "subject": "Bulk Email",
                "message": "Bulk with email.",
                "notification_type": "info",
                "send_email": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["count"] == 2
        assert mock_email.kiq.call_count == 2


# ---------------------------------------------------------------------------
# POST /api/notifications/admin/send
# ---------------------------------------------------------------------------
class TestAdminSendNotification:
    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_admin_send_to_specific_users(
        self,
        mock_email,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        admin_headers,
    ):
        """Admin sends to specific user IDs."""
        mock_email.kiq = AsyncMock()
        resp = await client.post(
            "/api/notifications/admin/send",
            headers=admin_headers,
            json={
                "user_ids": [str(test_user.guid)],
                "subject": "Admin Send",
                "message": "From admin.",
                "notification_type": "system",
                "send_email": False,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["count"] == 1
        assert data["recipients"] == 1

    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_admin_send_to_all_users(
        self,
        mock_email,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        admin_headers,
    ):
        """Admin sends to all active users."""
        mock_email.kiq = AsyncMock()
        resp = await client.post(
            "/api/notifications/admin/send",
            headers=admin_headers,
            json={
                "subject": "Broadcast",
                "message": "For everyone.",
                "notification_type": "system",
                "send_email": False,
                "send_to_all": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["count"] >= 2
        assert data["recipients"] >= 2

    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_admin_send_no_targets(
        self,
        mock_email,
        client: AsyncClient,
        admin_headers,
    ):
        """Admin send without user_ids or send_to_all -> 400."""
        mock_email.kiq = AsyncMock()
        resp = await client.post(
            "/api/notifications/admin/send",
            headers=admin_headers,
            json={
                "subject": "No targets",
                "message": "Should fail.",
                "notification_type": "system",
                "send_email": False,
                "send_to_all": False,
            },
        )
        assert resp.status_code == 400
        assert "Must specify" in resp.json()["detail"]

    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_admin_send_with_email(
        self,
        mock_email,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        admin_headers,
    ):
        """Admin send with send_email=True queues email tasks."""
        mock_email.kiq = AsyncMock()
        resp = await client.post(
            "/api/notifications/admin/send",
            headers=admin_headers,
            json={
                "user_ids": [str(test_user.guid)],
                "subject": "Email Admin",
                "message": "With email.",
                "notification_type": "system",
                "send_email": True,
            },
        )
        assert resp.status_code == 201
        mock_email.kiq.assert_called_once()

    @patch("pyrate.api.v1.notifications.send_notification_email")
    async def test_admin_send_as_user_forbidden(
        self,
        mock_email,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        """Regular user cannot use admin send endpoint."""
        mock_email.kiq = AsyncMock()
        resp = await client.post(
            "/api/notifications/admin/send",
            headers=user_headers,
            json={
                "user_ids": [str(test_user.guid)],
                "subject": "Forbidden",
                "message": "Should fail.",
            },
        )
        assert resp.status_code == 403
