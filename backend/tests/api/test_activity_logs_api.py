"""Tests for activity log API endpoints (/api/activity-logs)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from pyrate.models.activity_log import ActivityLog
from pyrate.models.user import User


class TestActivityLogs:
    async def test_list_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/activity-logs")
        assert resp.status_code == 401

    async def test_list_forbidden_for_regular_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/activity-logs", headers=user_headers)
        assert resp.status_code == 403

    async def test_create_and_list_activity_log(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        created = await client.post(
            "/api/activity-logs",
            headers=admin_headers,
            json={
                "event_type": "admin.note",
                "message": "Manual admin note",
                "severity": "info",
                "entity_type": "system",
            },
        )

        assert created.status_code == 201
        created_data = created.json()
        assert created_data["event_type"] == "admin.note"
        assert created_data["actor_guid"] == str(test_superuser.guid)

        listed = await client.get("/api/activity-logs", headers=admin_headers)

        assert listed.status_code == 200
        data = listed.json()
        assert data["total"] >= 1
        assert data["items"][0]["event_type"] == "admin.note"

    async def test_filter_activity_logs_by_event_type(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        await client.post(
            "/api/activity-logs",
            headers=admin_headers,
            json={"event_type": "one", "message": "One"},
        )
        await client.post(
            "/api/activity-logs",
            headers=admin_headers,
            json={"event_type": "two", "message": "Two"},
        )

        resp = await client.get(
            "/api/activity-logs",
            headers=admin_headers,
            params={"event_type": "two"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["event_type"] == "two"

    async def test_filter_activity_logs_by_severity_message_and_actor(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        await client.post(
            "/api/activity-logs",
            headers=admin_headers,
            json={
                "event_type": "task.failed",
                "message": "Library refresh failed",
                "severity": "error",
            },
        )
        await client.post(
            "/api/activity-logs",
            headers=admin_headers,
            json={
                "event_type": "task.completed",
                "message": "Library refresh completed",
                "severity": "info",
            },
        )

        resp = await client.get(
            "/api/activity-logs",
            headers=admin_headers,
            params={
                "severity": "error",
                "message": "refresh",
                "has_actor": "true",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["event_type"] == "task.failed"
        assert data["items"][0]["actor_guid"] == str(test_superuser.guid)

    async def test_filter_activity_logs_by_date_and_sort(
        self, client: AsyncClient, db_session, test_superuser: User, admin_headers
    ):
        older = datetime.now(UTC) - timedelta(days=2)
        newer = datetime.now(UTC) - timedelta(hours=1)
        db_session.add_all(
            [
                ActivityLog(
                    event_type="alpha",
                    message="Older",
                    severity="warning",
                    created_at=older,
                ),
                ActivityLog(
                    event_type="beta",
                    message="Newer",
                    severity="error",
                    created_at=newer,
                ),
            ]
        )
        await db_session.commit()

        resp = await client.get(
            "/api/activity-logs",
            headers=admin_headers,
            params={
                "min_date": (older + timedelta(hours=1)).isoformat(),
                "sort_by": "event_type",
                "sort_order": "asc",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["event_type"] == "beta"

    async def test_api_key_creation_writes_activity_log(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        created = await client.post(
            "/api/api-keys",
            headers=admin_headers,
            json={"name": "Logged Key"},
        )
        assert created.status_code == 201

        resp = await client.get(
            "/api/activity-logs",
            headers=admin_headers,
            params={"event_type": "api_key.created"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert data["items"][0]["message"] == "API key 'Logged Key' was created"

    async def test_activity_log_dispatches_notification_event(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        with patch(
            "pyrate.services.activity_log.NotificationDispatchService"
        ) as dispatch_service:
            dispatch_service.return_value.dispatch_event = AsyncMock(return_value=[])

            created = await client.post(
                "/api/activity-logs",
                headers=admin_headers,
                json={
                    "event_type": "task.failed",
                    "message": "Task failed",
                    "severity": "error",
                    "extra_data": "{\"task_id\":\"reindex_all\"}",
                },
            )

        assert created.status_code == 201
        dispatch_service.return_value.dispatch_event.assert_awaited_once()
        event_type, payload = dispatch_service.return_value.dispatch_event.await_args.args
        assert event_type == "task.failed"
        assert payload["severity"] == "error"
        assert payload["actor_guid"] == str(test_superuser.guid)
        assert payload["extra_data"] == {"task_id": "reindex_all"}
