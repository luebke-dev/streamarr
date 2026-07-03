"""Tests for the System API endpoints (/api/system/*)."""

from httpx import AsyncClient

from pyrate.models.user import User


class TestSystemHealth:
    async def test_ping_does_not_require_auth(self, client: AsyncClient):
        resp = await client.get("/api/system/ping")

        assert resp.status_code == 200
        assert resp.json() == "pyrate.media"

    async def test_endpoint_does_not_require_auth(self, client: AsyncClient):
        resp = await client.get(
            "/api/system/endpoint",
            headers={"X-Forwarded-For": "192.168.1.20, 203.0.113.10"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["remote_address"] == "192.168.1.20"
        assert data["forwarded_for"] == "192.168.1.20, 203.0.113.10"
        assert data["is_local"] is False
        assert data["is_in_network"] is True

    async def test_utc_time_does_not_require_auth(self, client: AsyncClient):
        resp = await client.get("/api/system/utc-time")

        assert resp.status_code == 200
        data = resp.json()
        assert "request_reception_time" in data
        assert "response_transmission_time" in data
        assert data["request_reception_time"].endswith(("Z", "+00:00"))
        assert data["response_transmission_time"].endswith(("Z", "+00:00"))

class TestPublicSystemInfo:
    async def test_public_info_does_not_require_auth(self, client: AsyncClient):
        resp = await client.get("/api/system/info/public")

        assert resp.status_code == 200
        data = resp.json()
        assert data["product_name"] == "pyrate.media"
        assert "version" in data
        assert data["site_name"] == "pyrate.media"
        assert data["locale"]
        assert "database_configured" not in data
        assert "redis_configured" not in data

class TestSystemInfo:
    async def test_private_info_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/system/info")
        assert resp.status_code == 401

    async def test_private_info_forbidden_for_regular_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/system/info", headers=user_headers)
        assert resp.status_code == 403

    async def test_private_info_for_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/system/info", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["product_name"] == "pyrate.media"
        assert data["authenticated_as"] == str(test_superuser.guid)
        assert data["database_configured"] is True
        assert data["redis_configured"] is True
        assert "python_version" in data
        assert "platform" in data
        assert "elasticsearch" in data
        assert "database_url" not in data
        assert "redis_url" not in data

    async def test_diagnostics_for_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/system/diagnostics", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["product_name"] == "pyrate.media"
        assert data["authenticated_as"] == str(test_superuser.guid)
        assert "generated_at" in data
        assert "database_configured" in data
        assert "redis_configured" in data
        assert "database_url" not in data
