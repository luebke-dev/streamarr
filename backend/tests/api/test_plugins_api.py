"""Tests for plugin package lifecycle endpoints (/api/plugins/*)."""

from httpx import AsyncClient
from sqlalchemy import select

from streamarr.models import ActivityLog


class TestPluginRepositories:
    async def test_repositories_require_admin(
        self, client: AsyncClient, user_headers
    ):
        unauthenticated = await client.get("/api/plugins/repositories")
        forbidden = await client.put(
            "/api/plugins/repositories",
            headers=user_headers,
            json={"repositories": []},
        )

        assert unauthenticated.status_code == 401
        assert forbidden.status_code == 403

    async def test_admin_updates_and_syncs_repositories(
        self, client: AsyncClient, db_session, admin_headers
    ):
        resp = await client.put(
            "/api/plugins/repositories",
            headers=admin_headers,
            json={
                "repositories": [
                    {
                        "id": "official",
                        "name": "Official",
                        "url": "https://plugins.example.test/manifest.json",
                        "priority": 10,
                    },
                    {
                        "id": "disabled",
                        "name": "Disabled",
                        "url": "https://disabled.example.test/manifest.json",
                        "enabled": False,
                        "priority": 20,
                    },
                ]
            },
        )

        assert resp.status_code == 200
        assert [repository["id"] for repository in resp.json()] == [
            "official",
            "disabled",
        ]

        listed = await client.get("/api/plugins/repositories", headers=admin_headers)
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == "official"

        sync = await client.post(
            "/api/plugins/repositories/official/sync",
            headers=admin_headers,
        )
        assert sync.status_code == 200
        assert sync.json()["status"] == "queued"

        skipped = await client.post(
            "/api/plugins/repositories/disabled/sync",
            headers=admin_headers,
        )
        assert skipped.status_code == 200
        assert skipped.json()["status"] == "skipped"

        log_result = await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.event_type == "plugins.repositories_update"
            )
        )
        assert "Updated 2 plugin repositories" in log_result.scalar_one().message

    async def test_sync_unknown_repository_returns_404(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.post(
            "/api/plugins/repositories/missing/sync",
            headers=admin_headers,
        )

        assert resp.status_code == 404

    async def test_duplicate_repository_ids_are_rejected(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            "/api/plugins/repositories",
            headers=admin_headers,
            json={
                "repositories": [
                    {"id": "same", "name": "One", "url": "https://one.test"},
                    {"id": "same", "name": "Two", "url": "https://two.test"},
                ]
            },
        )

        assert resp.status_code == 422
        assert "Duplicate plugin id" in resp.json()["detail"]

    async def test_invalid_plugin_notification_event_is_rejected(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.post(
            "/api/plugins/installed/bad-events",
            headers=admin_headers,
            json={
                "name": "Bad Events",
                "version": "1.0.0",
                "notification_events": [
                    {
                        "event_type": "Plugin.Bad.Event",
                        "name": "Bad Event",
                        "description": "Invalid uppercase event type.",
                    }
                ],
            },
        )

        assert resp.status_code == 422

    async def test_core_notification_event_conflict_is_rejected(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.post(
            "/api/plugins/installed/core-event-conflict",
            headers=admin_headers,
            json={
                "name": "Core Event Conflict",
                "version": "1.0.0",
                "notification_events": [
                    {
                        "event_type": "activity.created",
                        "name": "Conflicting Event",
                        "description": "Attempts to redefine a core event.",
                    }
                ],
            },
        )

        assert resp.status_code == 422
        assert "core notification catalog" in resp.json()["detail"][0]["message"]


class TestInstalledPlugins:
    async def test_installed_plugins_require_admin(
        self, client: AsyncClient, user_headers
    ):
        unauthenticated = await client.get("/api/plugins/installed")
        forbidden = await client.put(
            "/api/plugins/installed",
            headers=user_headers,
            json={"plugins": []},
        )

        assert unauthenticated.status_code == 401
        assert forbidden.status_code == 403

    async def test_install_enable_disable_update_and_delete_plugin(
        self, client: AsyncClient, db_session, admin_headers
    ):
        install = await client.post(
            "/api/plugins/installed/theme-pack",
            headers=admin_headers,
            json={
                "name": "Theme Pack",
                "version": "1.0.0",
                "source_repository_id": "official",
                "description": "Admin dashboard theme package",
                "runtime_kind": "static",
                "entry_point": "themes/theme-pack.json",
                "requires_restart": True,
                "capabilities": ["branding.theme"],
                "configuration": {"accent": "teal"},
                "notification_events": [
                    {
                        "event_type": "plugin.theme_pack.updated",
                        "name": "Theme Pack Updated",
                        "description": "Theme pack metadata changed.",
                    }
                ],
            },
        )
        assert install.status_code == 200
        data = install.json()
        assert data["id"] == "theme-pack"
        assert data["status"] == "installed"
        assert data["enabled"] is True
        assert data["runtime_kind"] == "static"
        assert data["entry_point"] == "themes/theme-pack.json"
        assert data["requires_restart"] is True
        assert data["capabilities"] == ["branding.theme"]
        assert data["notification_events"][0]["event_type"] == "plugin.theme_pack.updated"

        policy = await client.get("/api/plugins/runtime-policy", headers=admin_headers)
        assert policy.status_code == 200
        assert policy.json()["policy"]["execution_allowed"] is False
        assert policy.json()["advertised_capabilities"] == ["branding.theme"]

        validation = await client.get("/api/plugins/validation", headers=admin_headers)
        assert validation.status_code == 200
        assert validation.json()["valid"] is True
        assert validation.json()["runtime_warnings"][0]["plugin_id"] == "theme-pack"

        disable = await client.post(
            "/api/plugins/installed/theme-pack/disable",
            headers=admin_headers,
        )
        assert disable.status_code == 200
        assert disable.json()["status"] == "disabled"
        assert disable.json()["enabled"] is False

        enable = await client.post(
            "/api/plugins/installed/theme-pack/enable",
            headers=admin_headers,
        )
        assert enable.status_code == 200
        assert enable.json()["status"] == "installed"
        assert enable.json()["enabled"] is True

        update = await client.post(
            "/api/plugins/installed/theme-pack/update",
            headers=admin_headers,
            json={
                "version": "1.1.0",
                "status": "restart_required",
                "configuration": {"accent": "blue"},
                "notification_events": [
                    {
                        "event_type": "plugin.theme_pack.refreshed",
                        "name": "Theme Pack Refreshed",
                        "description": "Theme pack data refreshed.",
                    }
                ],
            },
        )
        assert update.status_code == 200
        assert update.json()["version"] == "1.1.0"
        assert update.json()["status"] == "restart_required"
        assert update.json()["configuration"] == {"accent": "blue"}
        assert update.json()["notification_events"][0]["event_type"] == "plugin.theme_pack.refreshed"

        listed = await client.get("/api/plugins/installed", headers=admin_headers)
        assert listed.status_code == 200
        assert [plugin["id"] for plugin in listed.json()] == ["theme-pack"]

        delete = await client.delete(
            "/api/plugins/installed/theme-pack",
            headers=admin_headers,
        )
        assert delete.status_code == 200
        assert delete.json()["status"] == "uninstalled"
        assert delete.json()["enabled"] is False

        empty = await client.get("/api/plugins/installed", headers=admin_headers)
        assert empty.status_code == 200
        assert empty.json() == []

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "plugins.update")
        )
        assert "Theme Pack" in log_result.scalar_one().message

    async def test_unknown_plugin_lifecycle_returns_404(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.post(
            "/api/plugins/installed/missing/disable",
            headers=admin_headers,
        )

        assert resp.status_code == 404

    async def test_bulk_installed_update_rejects_duplicate_ids(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            "/api/plugins/installed",
            headers=admin_headers,
            json={
                "plugins": [
                    {"id": "same", "name": "One", "version": "1.0.0"},
                    {"id": "same", "name": "Two", "version": "1.0.0"},
                ]
            },
        )

        assert resp.status_code == 422
        assert "Duplicate plugin id" in resp.json()["detail"]
