"""Tests for metadata provider admin endpoints (/api/metadata/*)."""

from httpx import AsyncClient


class TestMetadataProviders:
    async def test_list_providers_requires_admin(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/metadata/providers", headers=user_headers)

        assert resp.status_code == 403

    async def test_list_providers_includes_capabilities(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.get("/api/metadata/providers", headers=admin_headers)

        assert resp.status_code == 200
        providers = {provider["domain"]: provider for provider in resp.json()}
        assert "tmdb" in providers
        assert providers["tmdb"]["capabilities"]["remote_images"] is True
        assert providers["tmdb"]["capabilities"]["trending"] is True
        assert providers["shazam"]["capabilities"]["audio_identification"] is True

    async def test_get_provider_capabilities(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.get(
            "/api/metadata/providers/tmdb/capabilities",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["domain"] == "tmdb"
        assert "movies" in data["media_types"]
        assert data["capabilities"]["identify"] is True
        assert data["capabilities"]["translations"] is True

    async def test_get_unknown_provider_capabilities_returns_404(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.get(
            "/api/metadata/providers/missing/capabilities",
            headers=admin_headers,
        )

        assert resp.status_code == 404
