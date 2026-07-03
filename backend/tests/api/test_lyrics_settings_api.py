"""Tests for lyrics settings endpoints (/api/settings/lyrics)."""

from httpx import AsyncClient

from pyrate.models.user import User


class TestLyricsSettings:
    async def test_get_lyrics_settings_defaults(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/lyrics", headers=user_headers)

        assert resp.status_code == 200
        assert resp.json() == {
            "lyrics_providers": [],
            "lyrics_provider_urls": {},
            "lyrics_provider_api_key_configured": {},
        }

    async def test_update_lyrics_settings_as_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/lyrics",
            headers=admin_headers,
            json={
                "lyrics_providers": ["lrclib"],
                "lyrics_provider_urls": {
                    "lrclib": "https://lyrics.example/search"
                },
                "lyrics_provider_api_keys": {"lrclib": "secret-key"},
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "lyrics_providers": ["lrclib"],
            "lyrics_provider_urls": {
                "lrclib": "https://lyrics.example/search"
            },
            "lyrics_provider_api_key_configured": {"lrclib": True},
        }

    async def test_update_lyrics_settings_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.put(
            "/api/settings/lyrics",
            headers=user_headers,
            json={"lyrics_providers": ["lrclib"]},
        )

        assert resp.status_code == 403
