"""Tests for subtitle settings endpoints (/api/settings/subtitles)."""

from httpx import AsyncClient

from streamarr.models.user import User


class TestSubtitleSettings:
    async def test_get_subtitle_settings_defaults(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/subtitles", headers=user_headers)

        assert resp.status_code == 200
        assert resp.json() == {
            "fallback_font_family": "Arial",
            "fallback_font_path": None,
            "fallback_font_enabled": True,
            "subtitle_providers": [],
            "subtitle_provider_urls": {},
            "subtitle_provider_api_key_configured": {},
        }

    async def test_update_subtitle_settings_as_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/subtitles",
            headers=admin_headers,
            json={
                "fallback_font_family": "Noto Sans",
                "fallback_font_path": "/config/fonts/NotoSans-Regular.ttf",
                "fallback_font_enabled": False,
                "subtitle_providers": ["opensubtitles"],
                "subtitle_provider_urls": {
                    "opensubtitles": "https://subs.example/search"
                },
                "subtitle_provider_api_keys": {"opensubtitles": "secret-key"},
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "fallback_font_family": "Noto Sans",
            "fallback_font_path": "/config/fonts/NotoSans-Regular.ttf",
            "fallback_font_enabled": False,
            "subtitle_providers": ["opensubtitles"],
            "subtitle_provider_urls": {
                "opensubtitles": "https://subs.example/search"
            },
            "subtitle_provider_api_key_configured": {"opensubtitles": True},
        }

    async def test_update_subtitle_settings_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.put(
            "/api/settings/subtitles",
            headers=user_headers,
            json={"fallback_font_family": "Noto Sans"},
        )

        assert resp.status_code == 403
