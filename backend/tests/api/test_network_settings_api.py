"""Tests for network settings endpoints (/api/settings/network)."""

from httpx import AsyncClient
from sqlalchemy import select

from pyrate.models.activity_log import ActivityLog
from pyrate.models.user import User


class TestNetworkSettings:
    async def test_get_network_settings_requires_admin(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/network", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_network_settings_defaults(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/network", headers=admin_headers)

        assert resp.status_code == 200
        assert resp.json() == {
            "public_hostname": None,
            "bind_host": "0.0.0.0",
            "bind_port": 8000,
            "enable_https": False,
            "ssl_certificate_path": None,
            "ssl_key_path": None,
            "remote_access_enabled": True,
        }

    async def test_update_network_settings(
        self, client: AsyncClient, db_session, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/network",
            headers=admin_headers,
            json={
                "public_hostname": "media.example.test",
                "bind_host": "127.0.0.1",
                "bind_port": 9443,
                "enable_https": True,
                "ssl_certificate_path": "/config/certs/fullchain.pem",
                "ssl_key_path": "/config/certs/privkey.pem",
                "remote_access_enabled": False,
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "public_hostname": "media.example.test",
            "bind_host": "127.0.0.1",
            "bind_port": 9443,
            "enable_https": True,
            "ssl_certificate_path": "/config/certs/fullchain.pem",
            "ssl_key_path": "/config/certs/privkey.pem",
            "remote_access_enabled": False,
        }
        log_result = await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.event_type == "settings.network_update"
            )
        )
        log_entry = log_result.scalar_one()
        assert "bind_port" in log_entry.extra_data
        assert log_entry.actor_guid == test_superuser.guid

    async def test_update_network_settings_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.put(
            "/api/settings/network",
            headers=user_headers,
            json={"public_hostname": "media.example.test"},
        )

        assert resp.status_code == 403

    async def test_get_network_runtime_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers, monkeypatch
    ):
        await client.put(
            "/api/settings/network",
            headers=admin_headers,
            json={"bind_host": "127.0.0.1", "bind_port": 9443},
        )
        monkeypatch.setenv("PYRATE_EFFECTIVE_BIND_HOST", "0.0.0.0")
        monkeypatch.setenv("PYRATE_EFFECTIVE_BIND_PORT", "8000")

        resp = await client.get("/api/settings/network/runtime", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["bind_host"] == "127.0.0.1"
        assert data["bind_port"] == 9443
        assert data["source"] == "database"
        assert data["ssl_files_present"] is False
        assert data["restart_required"] is True
        assert data["internal_base_url"] == "http://127.0.0.1:9443"
        assert data["reverse_proxy_env"]["PYRATE_UPSTREAM_PORT"] == "9443"

    async def test_get_network_runtime_settings_reports_proxy_urls(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        await client.put(
            "/api/settings/network",
            headers=admin_headers,
            json={
                "public_hostname": "media.example.test",
                "bind_host": "0.0.0.0",
                "bind_port": 443,
                "enable_https": True,
            },
        )

        resp = await client.get("/api/settings/network/runtime", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["public_base_url"] == "https://media.example.test"
        assert data["internal_base_url"] == "https://127.0.0.1:443"
        assert data["reverse_proxy_env"] == {
            "PYRATE_UPSTREAM_HOST": "0.0.0.0",
            "PYRATE_UPSTREAM_PORT": "443",
            "PYRATE_UPSTREAM_SCHEME": "https",
            "PYRATE_PUBLIC_BASE_URL": "https://media.example.test",
            "PYRATE_INTERNAL_BASE_URL": "https://127.0.0.1:443",
        }

    async def test_get_network_runtime_settings_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/network/runtime", headers=user_headers)
        assert resp.status_code == 403
