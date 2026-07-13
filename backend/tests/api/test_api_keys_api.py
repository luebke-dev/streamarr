"""Tests for the API Keys API endpoints (/api/api-keys)."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.auth.dependencies import _resolve_user_from_api_key
from streamarr.models.user import User


class TestApiKeys:
    async def test_list_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/api-keys")
        assert resp.status_code == 401

    async def test_list_forbidden_for_regular_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/api-keys", headers=user_headers)
        assert resp.status_code == 403

    async def test_create_api_key(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/api-keys",
            headers=admin_headers,
            json={"name": "Automation"},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Automation"
        assert data["user_guid"] == str(test_superuser.guid)
        assert data["key"].startswith("pmak_")
        assert data["key_prefix"] == data["key"][:12]
        assert "key_hash" not in data

    async def test_create_for_missing_user(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/api-keys",
            headers=admin_headers,
            json={"name": "Missing", "user_guid": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    async def test_list_api_keys(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        created = await client.post(
            "/api/api-keys",
            headers=admin_headers,
            json={"name": "List Me"},
        )
        assert created.status_code == 201

        resp = await client.get("/api/api-keys", headers=admin_headers)

        assert resp.status_code == 200
        names = [row["name"] for row in resp.json()]
        assert "List Me" in names

    async def test_revoke_api_key(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        created = await client.post(
            "/api/api-keys",
            headers=admin_headers,
            json={"name": "Revoke Me"},
        )
        guid = created.json()["guid"]

        resp = await client.post(f"/api/api-keys/{guid}/revoke", headers=admin_headers)

        assert resp.status_code == 200
        assert resp.json()["revoked_at"] is not None

    async def test_delete_api_key(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        created = await client.post(
            "/api/api-keys",
            headers=admin_headers,
            json={"name": "Delete Me"},
        )
        guid = created.json()["guid"]

        resp = await client.delete(f"/api/api-keys/{guid}", headers=admin_headers)

        assert resp.status_code == 204

    async def test_api_key_resolves_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        created = await client.post(
            "/api/api-keys",
            headers=admin_headers,
            json={"name": "Auth Key"},
        )
        raw_key = created.json()["key"]

        user = await _resolve_user_from_api_key(raw_key, db_session)

        assert user is not None
        assert user.guid == test_superuser.guid

