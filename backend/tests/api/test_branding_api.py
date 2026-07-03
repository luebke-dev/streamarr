"""Tests for public branding endpoints (/api/branding/*)."""

from httpx import AsyncClient
from sqlalchemy import select

from pyrate.models import ActivityLog


class TestBrandingConfiguration:
    async def test_public_can_read_branding_configuration(self, client: AsyncClient):
        resp = await client.get("/api/branding/configuration")

        assert resp.status_code == 200
        data = resp.json()
        assert data["server_name"] == "pyrate.media"
        assert data["login_disclaimer"] == ""
        assert data["custom_css"] == ""
        assert data["logo_url"] is None

    async def test_regular_user_cannot_update_branding(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.put(
            "/api/branding/configuration",
            headers=user_headers,
            json={"server_name": "Nope"},
        )

        assert resp.status_code == 403

    async def test_admin_updates_branding_configuration(
        self, client: AsyncClient, db_session, admin_headers
    ):
        resp = await client.put(
            "/api/branding/configuration",
            headers=admin_headers,
            json={
                "server_name": "Pyrate Test",
                "login_disclaimer": "Private server",
                "custom_css": "body { color: rgb(1, 2, 3); }",
                "logo_url": "https://cdn.example.test/logo.png",
                "splashscreen_enabled": True,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["server_name"] == "Pyrate Test"
        assert data["login_disclaimer"] == "Private server"
        assert data["custom_css"] == "body { color: rgb(1, 2, 3); }"
        assert data["logo_url"] == "https://cdn.example.test/logo.png"
        assert data["splashscreen_enabled"] is True

        public = await client.get("/api/branding/configuration")
        assert public.status_code == 200
        assert public.json()["server_name"] == "Pyrate Test"

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "branding.update")
        )
        assert "Updated branding configuration" in log_result.scalar_one().message

    async def test_public_css_endpoint_returns_text_css(
        self, client: AsyncClient, admin_headers
    ):
        await client.put(
            "/api/branding/configuration",
            headers=admin_headers,
            json={"custom_css": ".skin { background: #111; }"},
        )

        resp = await client.get("/api/branding/css.css")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/css")
        assert resp.text == ".skin { background: #111; }"


class TestBrandingThemes:
    async def test_public_lists_enabled_themes_only(
        self, client: AsyncClient, admin_headers
    ):
        await client.put(
            "/api/branding/themes",
            headers=admin_headers,
            json={
                "themes": [
                    {
                        "id": "dark",
                        "name": "Dark",
                        "dark": True,
                        "colors": {"primary": "#00aaff"},
                    },
                    {
                        "id": "disabled",
                        "name": "Disabled",
                        "enabled": False,
                    },
                ]
            },
        )

        resp = await client.get("/api/branding/themes")

        assert resp.status_code == 200
        assert [theme["id"] for theme in resp.json()] == ["dark"]

    async def test_regular_user_cannot_update_themes(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.put(
            "/api/branding/themes",
            headers=user_headers,
            json={"themes": []},
        )

        assert resp.status_code == 403

    async def test_admin_sets_active_theme(
        self, client: AsyncClient, admin_headers
    ):
        await client.put(
            "/api/branding/themes",
            headers=admin_headers,
            json={
                "themes": [
                    {
                        "id": "teal",
                        "name": "Teal",
                        "dark": False,
                        "variables": {"radius": "4px"},
                    }
                ]
            },
        )

        update = await client.put(
            "/api/branding/themes/active",
            headers=admin_headers,
            json={"theme_id": "teal"},
        )
        assert update.status_code == 200
        assert update.json()["active_theme_id"] == "teal"

        active = await client.get("/api/branding/themes/active")
        assert active.status_code == 200
        assert active.json()["id"] == "teal"
        assert active.json()["variables"] == {"radius": "4px"}

    async def test_unknown_active_theme_returns_404(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            "/api/branding/themes/active",
            headers=admin_headers,
            json={"theme_id": "missing"},
        )

        assert resp.status_code == 404

    async def test_duplicate_theme_ids_are_rejected(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            "/api/branding/themes",
            headers=admin_headers,
            json={
                "themes": [
                    {"id": "same", "name": "One"},
                    {"id": "same", "name": "Two"},
                ]
            },
        )

        assert resp.status_code == 422
        assert "Duplicate theme id" in resp.json()["detail"]
