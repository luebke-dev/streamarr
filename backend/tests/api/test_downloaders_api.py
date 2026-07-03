"""Tests for downloaders API endpoints (/api/downloaders/*)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.downloader import Downloader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _create_downloader(db_session: AsyncSession, **kwargs) -> Downloader:
    dl = Downloader(
        guid=kwargs.get("guid", uuid.uuid4()),
        host=kwargs.get("host", "http://localhost:8080"),
        api_key=kwargs.get("api_key", "test-api-key-123"),
        ssl=kwargs.get("ssl", False),
        verify_ssl=kwargs.get("verify_ssl", True),
        type=kwargs.get("type", "sabnzbd"),
        label=kwargs.get("label", "Test SABnzbd"),
    )
    db_session.add(dl)
    await db_session.commit()
    await db_session.refresh(dl)
    return dl


# ---------------------------------------------------------------------------
# GET /api/downloaders/types
# ---------------------------------------------------------------------------
class TestListDownloaderTypes:
    async def test_list_types(self, client: AsyncClient, admin_headers):
        """Returns the native downloader types exposed by the API."""
        resp = await client.get("/api/downloaders/types", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        by_domain = {entry["domain"]: entry for entry in data}
        assert set(by_domain) == {"sabnzbd", "deluge", "spotdl"}
        assert by_domain["sabnzbd"]["name"] == "SABnzbd"
        assert by_domain["deluge"]["description"] == "Deluge BitTorrent client"
        assert by_domain["spotdl"]["config_schema"] == {}

    async def test_list_types_is_static(self, client: AsyncClient, admin_headers):
        """The native downloader list does not depend on plugin registry state."""
        resp = await client.get("/api/downloaders/types", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert [entry["domain"] for entry in data] == ["sabnzbd", "deluge", "spotdl"]

    async def test_list_types_regular_user_forbidden(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/downloaders/types", headers=user_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/downloaders
# ---------------------------------------------------------------------------
class TestListDownloaders:
    async def test_list_empty(self, client: AsyncClient, admin_headers):
        resp = await client.get("/api/downloaders", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_downloaders(self, client: AsyncClient, db_session, admin_headers):
        await _create_downloader(db_session, label="SAB1")
        await _create_downloader(db_session, label="SAB2", host="http://localhost:9090")

        resp = await client.get("/api/downloaders", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_list_downloaders_regular_user_forbidden(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/downloaders", headers=user_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/downloaders
# ---------------------------------------------------------------------------
class TestCreateDownloader:
    async def test_create_downloader(self, client: AsyncClient, admin_headers):
        resp = await client.post(
            "/api/downloaders",
            json={
                "host": "http://sab.local:8080",
                "api_key": "my-api-key",
                "ssl": False,
                "verify_ssl": True,
                "type": "sabnzbd",
                "label": "My SABnzbd",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "My SABnzbd"
        assert data["type"] == "sabnzbd"
        assert "guid" in data

    async def test_create_downloader_regular_user_forbidden(self, client: AsyncClient, user_headers):
        resp = await client.post(
            "/api/downloaders",
            json={
                "host": "http://sab.local",
                "api_key": "key",
                "type": "sabnzbd",
                "label": "Test",
            },
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/downloaders/{downloader_id}
# ---------------------------------------------------------------------------
class TestGetDownloader:
    async def test_get_downloader(self, client: AsyncClient, db_session, admin_headers):
        dl = await _create_downloader(db_session)

        resp = await client.get(f"/api/downloaders/{dl.guid}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["label"] == "Test SABnzbd"

    async def test_get_downloader_not_found(self, client: AsyncClient, admin_headers):
        fake = uuid.uuid4()
        resp = await client.get(f"/api/downloaders/{fake}", headers=admin_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/downloaders/{downloader_id}
# ---------------------------------------------------------------------------
class TestUpdateDownloader:
    async def test_update_downloader(self, client: AsyncClient, db_session, admin_headers):
        dl = await _create_downloader(db_session)

        resp = await client.put(
            f"/api/downloaders/{dl.guid}",
            json={
                "host": "http://updated.local:9090",
                "api_key": "new-key",
                "ssl": True,
                "verify_ssl": False,
                "type": "sabnzbd",
                "label": "Updated SABnzbd",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "Updated SABnzbd"
        assert data["host"] == "http://updated.local:9090"

    async def test_update_downloader_not_found(self, client: AsyncClient, admin_headers):
        fake = uuid.uuid4()
        resp = await client.put(
            f"/api/downloaders/{fake}",
            json={
                "host": "http://x",
                "api_key": "k",
                "type": "sabnzbd",
                "label": "X",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/downloaders/{downloader_id}
# ---------------------------------------------------------------------------
class TestDeleteDownloader:
    async def test_delete_downloader(self, client: AsyncClient, db_session, admin_headers):
        dl = await _create_downloader(db_session)

        resp = await client.delete(f"/api/downloaders/{dl.guid}", headers=admin_headers)
        assert resp.status_code == 204

    async def test_delete_downloader_not_found(self, client: AsyncClient, admin_headers):
        fake = uuid.uuid4()
        resp = await client.delete(f"/api/downloaders/{fake}", headers=admin_headers)
        assert resp.status_code == 404

    async def test_delete_downloader_regular_user_forbidden(self, client: AsyncClient, db_session, user_headers):
        dl = await _create_downloader(db_session)

        resp = await client.delete(f"/api/downloaders/{dl.guid}", headers=user_headers)
        assert resp.status_code == 403
