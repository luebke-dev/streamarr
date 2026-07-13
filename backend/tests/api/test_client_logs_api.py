"""Tests for the Client Logs API endpoint (/api/client-logs)."""

from unittest.mock import patch

from httpx import AsyncClient

from streamarr.models.user import User


class TestClientLogs:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            "/api/client-logs",
            json={"level": "error", "message": "Browser error"},
        )
        assert resp.status_code == 401

    async def test_invalid_level(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            "/api/client-logs",
            headers=user_headers,
            json={"level": "verbose", "message": "Browser error"},
        )
        assert resp.status_code == 422

    async def test_ingest_client_log(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        with patch("streamarr.api.v1.client_logs.logger.error") as log_error:
            resp = await client.post(
                "/api/client-logs",
                headers=user_headers,
                json={
                    "level": "error",
                    "message": "Browser error",
                    "source": "frontend",
                    "url": "https://app.example.test/media/1",
                    "user_agent": "test-agent",
                    "context": {"component": "Player"},
                },
            )

        assert resp.status_code == 204
        log_error.assert_called_once()
        args, kwargs = log_error.call_args
        assert args == ("Browser error",)
        assert kwargs["extra"]["client_source"] == "frontend"
        assert kwargs["extra"]["client_context"] == {"component": "Player"}
        assert kwargs["extra"]["user_guid"] == str(test_user.guid)

