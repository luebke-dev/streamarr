"""Tests for invites API endpoints (/api/invites/*)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.auth.jwt_handler import jwt_handler
from streamarr.models import Invite, User

from .conftest import auth_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _create_invite(
    db_session: AsyncSession,
    user: User,
    *,
    is_active: bool = True,
    hours_until_expiry: int = 72,
) -> Invite:
    token_data = {"created_by_user_id": str(user.guid)}
    token = jwt_handler.create_invite_token(token_data, timedelta(hours=hours_until_expiry))
    invite = Invite(
        guid=uuid.uuid4(),
        created_by_user_id=user.guid,
        token=token,
        expires_at=datetime.now(UTC) + timedelta(hours=hours_until_expiry),
        is_active=is_active,
        max_uses=1,
    )
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    return invite


# ---------------------------------------------------------------------------
# POST /api/invites
# ---------------------------------------------------------------------------
class TestCreateInvite:
    async def test_create_invite(self, client: AsyncClient, admin_headers):
        resp = await client.post(
            "/api/invites",
            json={"description": "Test invite", "max_uses": 3, "expiry_hours": 48},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["max_uses"] == 3
        assert "token" in data
        assert data["is_active"] is True

    async def test_create_invite_default_values(self, client: AsyncClient, admin_headers):
        resp = await client.post(
            "/api/invites",
            json={},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["max_uses"] == 1

    async def test_create_invite_unauthenticated(self, client: AsyncClient):
        resp = await client.post("/api/invites", json={})
        assert resp.status_code in (401, 403)

    async def test_create_invite_disabled(self, client: AsyncClient, admin_headers):
        """Invite creation is blocked when the invite system is disabled."""
        from unittest.mock import patch

        from streamarr.config import settings

        with patch.object(settings.invites, "enabled", False):
            resp = await client.post("/api/invites", json={}, headers=admin_headers)
        assert resp.status_code == 403

    async def test_create_invite_require_admin_blocks_regular_user(
        self, client: AsyncClient, user_headers
    ):
        """When require_admin_creation is True, regular users cannot create invites."""
        from unittest.mock import patch

        from streamarr.config import settings

        with patch.object(settings.invites, "require_admin_creation", True):
            resp = await client.post("/api/invites", json={}, headers=user_headers)
        assert resp.status_code == 403

    async def test_create_invite_with_explicit_expires_at(
        self, client: AsyncClient, admin_headers
    ):
        """Passing expires_at directly is accepted and used as the expiry timestamp."""
        from datetime import UTC, datetime, timedelta

        future = (datetime.now(UTC) + timedelta(hours=48)).isoformat()
        resp = await client.post(
            "/api/invites",
            json={"expires_at": future},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        assert "token" in resp.json()

    async def test_create_invite_expiry_hours_exceeds_max(
        self, client: AsyncClient, admin_headers
    ):
        """expiry_hours greater than max_expiry_hours returns 400.

        Note: InviteCreate.expiry_hours has le=168, so we must send a value
        <= 168 but larger than the mocked max_expiry_hours.
        """
        from unittest.mock import patch

        from streamarr.config import settings

        with patch.object(settings.invites, "max_expiry_hours", 10):
            resp = await client.post(
                "/api/invites",
                json={"expiry_hours": 48},
                headers=admin_headers,
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/invites
# ---------------------------------------------------------------------------
class TestListInvites:
    async def test_list_invites_empty(self, client: AsyncClient, admin_headers):
        resp = await client.get("/api/invites", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_list_invites(self, client: AsyncClient, db_session, test_superuser, admin_headers):
        await _create_invite(db_session, test_superuser)
        await _create_invite(db_session, test_superuser)

        resp = await client.get("/api/invites", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

    async def test_list_invites_pagination(self, client: AsyncClient, db_session, test_superuser, admin_headers):
        for _ in range(5):
            await _create_invite(db_session, test_superuser)

        resp = await client.get("/api/invites?page=1&size=2", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 5
        assert len(data["items"]) == 2

    async def test_list_invites_as_regular_user(
        self, client: AsyncClient, db_session, test_user, user_headers
    ):
        """Regular users can list their own invites (non-superuser path)."""
        await _create_invite(db_session, test_user)

        resp = await client.get("/api/invites", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    async def test_list_invites_disabled(self, client: AsyncClient, admin_headers):
        """Listing invites is blocked when the invite system is disabled."""
        from unittest.mock import patch

        from streamarr.config import settings

        with patch.object(settings.invites, "enabled", False):
            resp = await client.get("/api/invites", headers=admin_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/invites/{invite_id}
# ---------------------------------------------------------------------------
class TestGetInvite:
    async def test_get_invite(self, client: AsyncClient, db_session, test_superuser, admin_headers):
        invite = await _create_invite(db_session, test_superuser)

        resp = await client.get(f"/api/invites/{invite.guid}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["guid"] == str(invite.guid)

    async def test_get_invite_not_found(self, client: AsyncClient, admin_headers):
        fake = uuid.uuid4()
        resp = await client.get(f"/api/invites/{fake}", headers=admin_headers)
        assert resp.status_code == 404

    async def test_get_other_users_invite_forbidden(
        self, client: AsyncClient, db_session, test_superuser, test_user, user_headers
    ):
        invite = await _create_invite(db_session, test_superuser)

        resp = await client.get(f"/api/invites/{invite.guid}", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_invite_disabled(
        self, client: AsyncClient, db_session, test_superuser, admin_headers
    ):
        """Getting an invite is blocked when the invite system is disabled."""
        from unittest.mock import patch

        from streamarr.config import settings

        invite = await _create_invite(db_session, test_superuser)
        with patch.object(settings.invites, "enabled", False):
            resp = await client.get(f"/api/invites/{invite.guid}", headers=admin_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /api/invites/{invite_id}
# ---------------------------------------------------------------------------
class TestUpdateInvite:
    async def test_update_invite(self, client: AsyncClient, db_session, test_superuser, admin_headers):
        invite = await _create_invite(db_session, test_superuser)

        resp = await client.put(
            f"/api/invites/{invite.guid}",
            json={"description": "Updated desc", "max_uses": 5},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Updated desc"

    async def test_update_invite_deactivate(self, client: AsyncClient, db_session, test_superuser, admin_headers):
        invite = await _create_invite(db_session, test_superuser)

        resp = await client.put(
            f"/api/invites/{invite.guid}",
            json={"is_active": False},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_update_invite_disabled(
        self, client: AsyncClient, db_session, test_superuser, admin_headers
    ):
        """Updating an invite is blocked when the invite system is disabled."""
        from unittest.mock import patch

        from streamarr.config import settings

        invite = await _create_invite(db_session, test_superuser)
        with patch.object(settings.invites, "enabled", False):
            resp = await client.put(
                f"/api/invites/{invite.guid}",
                json={"description": "x"},
                headers=admin_headers,
            )
        assert resp.status_code == 403

    async def test_update_invite_not_found(self, client: AsyncClient, admin_headers):
        """Updating a non-existent invite returns 404."""
        resp = await client.put(
            f"/api/invites/{uuid.uuid4()}",
            json={"description": "x"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_update_invite_forbidden(
        self, client: AsyncClient, db_session, test_superuser, user_headers
    ):
        """Regular user cannot update another user's invite."""
        invite = await _create_invite(db_session, test_superuser)

        resp = await client.put(
            f"/api/invites/{invite.guid}",
            json={"description": "hijacked"},
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/invites/{invite_id}
# ---------------------------------------------------------------------------
class TestDeleteInvite:
    async def test_delete_invite(self, client: AsyncClient, db_session, test_superuser, admin_headers):
        invite = await _create_invite(db_session, test_superuser)

        resp = await client.delete(f"/api/invites/{invite.guid}", headers=admin_headers)
        assert resp.status_code == 204

        resp2 = await client.get(f"/api/invites/{invite.guid}", headers=admin_headers)
        assert resp2.status_code == 404

    async def test_delete_invite_not_found(self, client: AsyncClient, admin_headers):
        fake = uuid.uuid4()
        resp = await client.delete(f"/api/invites/{fake}", headers=admin_headers)
        assert resp.status_code == 404

    async def test_delete_invite_disabled(
        self, client: AsyncClient, db_session, test_superuser, admin_headers
    ):
        """Deleting an invite is blocked when the invite system is disabled."""
        from unittest.mock import patch

        from streamarr.config import settings

        invite = await _create_invite(db_session, test_superuser)
        with patch.object(settings.invites, "enabled", False):
            resp = await client.delete(f"/api/invites/{invite.guid}", headers=admin_headers)
        assert resp.status_code == 403

    async def test_delete_invite_forbidden(
        self, client: AsyncClient, db_session, test_superuser, user_headers
    ):
        """Regular user cannot delete another user's invite."""
        invite = await _create_invite(db_session, test_superuser)

        resp = await client.delete(f"/api/invites/{invite.guid}", headers=user_headers)
        assert resp.status_code == 403

    async def test_delete_invite_deletion_failure(
        self, client: AsyncClient, db_session, test_superuser, admin_headers
    ):
        """When the service fails to delete, a 500 is returned."""
        from unittest.mock import AsyncMock, patch

        invite = await _create_invite(db_session, test_superuser)
        with patch("streamarr.services.invite.InviteService.delete", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = False
            resp = await client.delete(f"/api/invites/{invite.guid}", headers=admin_headers)
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/invites/validate
# ---------------------------------------------------------------------------
class TestValidateInvite:
    async def test_validate_invite_valid(self, client: AsyncClient, db_session, test_superuser):
        invite = await _create_invite(db_session, test_superuser)

        resp = await client.post("/api/invites/validate", json={"token": invite.token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    async def test_validate_invite_invalid_token(self, client: AsyncClient):
        resp = await client.post("/api/invites/validate", json={"token": "bad.token.here"})
        assert resp.status_code == 400

    async def test_validate_invite_disabled(self, client: AsyncClient):
        """Validation endpoint returns 403 when the invite system is disabled."""
        from unittest.mock import patch

        from streamarr.config import settings

        with patch.object(settings.invites, "enabled", False):
            resp = await client.post("/api/invites/validate", json={"token": "some.tok.en"})
        assert resp.status_code == 403

    async def test_validate_invite_not_found_in_db(self, client: AsyncClient):
        """Returns 400 when token has valid signature but invite not found/expired in DB."""
        from unittest.mock import AsyncMock, patch

        from streamarr.auth.jwt_handler import jwt_handler as jh

        with patch.object(jh, "verify_invite_token", return_value={"invite_id": "x"}), \
             patch("streamarr.api.v1.invites.InviteService") as MockService:
            MockService.return_value.get_valid_by_token = AsyncMock(return_value=None)
            resp = await client.post("/api/invites/validate", json={"token": "any.jwt.token"})
        assert resp.status_code == 400
        assert "invalid" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/invites/cleanup
# ---------------------------------------------------------------------------
class TestCleanupInvites:
    async def test_cleanup_admin(self, client: AsyncClient, admin_headers):
        resp = await client.post("/api/invites/cleanup", headers=admin_headers)
        assert resp.status_code == 200
        assert "message" in resp.json()

    async def test_cleanup_regular_user_forbidden(self, client: AsyncClient, user_headers):
        resp = await client.post("/api/invites/cleanup", headers=user_headers)
        assert resp.status_code == 403
