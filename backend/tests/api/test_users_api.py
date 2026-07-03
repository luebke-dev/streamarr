"""Tests for users API endpoints (/api/users/*)."""

import uuid
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.auth.jwt_handler import jwt_handler
from pyrate.models.library import Library
from pyrate.models.user import User

from .conftest import auth_headers


async def _create_library(db_session: AsyncSession, **overrides) -> Library:
    now = datetime.now()
    defaults = dict(
        guid=uuid.uuid4(),
        name="Movies",
        type="MOVIES",
        plugin_id="movies",
        path="/data/library/movies",
        enabled=True,
        settings=None,
        description=None,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    library = Library(**defaults)
    db_session.add(library)
    await db_session.commit()
    await db_session.refresh(library)
    return library


# ---------------------------------------------------------------------------
# GET /api/users
# ---------------------------------------------------------------------------
class TestListUsers:
    async def test_list_users(self, client: AsyncClient, test_superuser: User, admin_headers):
        resp = await client.get("/api/users", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    async def test_list_users_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/users", headers=user_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/users
# ---------------------------------------------------------------------------
class TestCreateUser:
    async def test_create_user(self, client: AsyncClient, admin_headers):
        resp = await client.post(
            "/api/users",
            json={
                "email": "newuser@example.com",
                "first_name": "New",
                "last_name": "User",
                "password": "StrongPass123",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "newuser@example.com"
        assert data["first_name"] == "New"
        assert "guid" in data

    async def test_create_user_without_password(self, client: AsyncClient, admin_headers):
        resp = await client.post(
            "/api/users",
            json={
                "email": "nopass@example.com",
                "first_name": "No",
                "last_name": "Pass",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200

    async def test_create_user_duplicate_email(self, client: AsyncClient, test_user: User, admin_headers):
        resp = await client.post(
            "/api/users",
            json={
                "email": test_user.email,
                "first_name": "Dup",
                "last_name": "User",
            },
            headers=admin_headers,
        )
        # Should fail due to unique constraint
        assert resp.status_code in (400, 409, 500)


# ---------------------------------------------------------------------------
# GET /api/users/{user_guid}
# ---------------------------------------------------------------------------
class TestGetUser:
    async def test_get_own_user(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get(f"/api/users/{test_user.guid}", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == test_user.email

    async def test_get_other_user_forbidden(self, client: AsyncClient, test_superuser: User, user_headers):
        resp = await client.get(f"/api/users/{test_superuser.guid}", headers=user_headers)
        assert resp.status_code == 403

    async def test_admin_get_any_user(self, client: AsyncClient, test_user: User, admin_headers):
        resp = await client.get(f"/api/users/{test_user.guid}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == test_user.email

    async def test_get_user_not_found(self, client: AsyncClient, user_headers):
        fake_guid = uuid.uuid4()
        resp = await client.get(f"/api/users/{fake_guid}", headers=user_headers)
        # Either 404 or 403 (since not superuser, they get 403 for other users)
        assert resp.status_code in (403, 404)


# ---------------------------------------------------------------------------
# PUT /api/users/{user_guid}
# ---------------------------------------------------------------------------
class TestUpdateUser:
    async def test_update_own_user(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.put(
            f"/api/users/{test_user.guid}",
            json={"first_name": "Updated"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["first_name"] == "Updated"

    async def test_update_other_user_forbidden(self, client: AsyncClient, test_superuser: User, user_headers):
        resp = await client.put(
            f"/api/users/{test_superuser.guid}",
            json={"first_name": "Hacked"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_admin_update_any_user(self, client: AsyncClient, test_user: User, admin_headers):
        resp = await client.put(
            f"/api/users/{test_user.guid}",
            json={"first_name": "AdminUpdated"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["first_name"] == "AdminUpdated"


# ---------------------------------------------------------------------------
# PUT /api/users/{user_guid}/password
# ---------------------------------------------------------------------------
class TestChangePassword:
    async def test_change_password(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.put(
            f"/api/users/{test_user.guid}/password",
            json={
                "current_password": "TestPassword123",
                "new_password": "NewPassword456",
            },
            headers=user_headers,
        )
        assert resp.status_code == 200

        # Verify new password works
        resp2 = await client.post(
            "/api/auth/local/login",
            json={"email": test_user.email, "password": "NewPassword456"},
        )
        assert resp2.status_code == 200

    async def test_change_password_wrong_current(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.put(
            f"/api/users/{test_user.guid}/password",
            json={
                "current_password": "WrongPassword",
                "new_password": "NewPassword456",
            },
            headers=user_headers,
        )
        assert resp.status_code == 400

    async def test_change_password_other_user(self, client: AsyncClient, test_superuser: User, user_headers):
        resp = await client.put(
            f"/api/users/{test_superuser.guid}/password",
            json={
                "current_password": "whatever",
                "new_password": "NewPassword456",
            },
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/users/{user_guid}
# ---------------------------------------------------------------------------
class TestDeleteUser:
    async def test_delete_own_account(self, client: AsyncClient, db_session: AsyncSession, user_headers):
        # Create a separate user to delete
        user = User(
            guid=uuid.uuid4(),
            email="todelete@example.com",
            first_name="To",
            last_name="Delete",
            is_active=True,
            hashed_password=jwt_handler.get_password_hash("DeleteMe123"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        headers = auth_headers(user)
        resp = await client.delete(f"/api/users/{user.guid}", headers=headers)
        assert resp.status_code == 200

    async def test_delete_other_user_forbidden(self, client: AsyncClient, test_superuser: User, user_headers):
        resp = await client.delete(f"/api/users/{test_superuser.guid}", headers=user_headers)
        assert resp.status_code == 403

    async def test_admin_delete_user(self, client: AsyncClient, db_session: AsyncSession, admin_headers):
        user = User(
            guid=uuid.uuid4(),
            email="deletable@example.com",
            first_name="Del",
            last_name="User",
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        resp = await client.delete(f"/api/users/{user.guid}", headers=admin_headers)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Language settings
# ---------------------------------------------------------------------------
class TestLanguageSettings:
    async def test_get_language_settings(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/users/me/language-settings", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "ui_language" in data
        assert "audio_language" in data
        assert "subtitle_language" in data

    async def test_update_language_settings(self, client: AsyncClient, user_headers):
        resp = await client.put(
            "/api/users/me/language-settings",
            json={
                "ui_language": "de-DE",
                "audio_language": "de",
                "subtitle_language": "en",
            },
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ui_language"] == "de-DE"
        assert data["audio_language"] == "de"
        assert data["subtitle_language"] == "en"


# ---------------------------------------------------------------------------
# GET /api/users/{user_guid}/stats
# ---------------------------------------------------------------------------
class TestUserStats:
    async def test_get_user_stats_as_admin(
        self, client: AsyncClient, test_user: User, test_superuser: User, admin_headers
    ):
        resp = await client.get(
            f"/api/users/{test_user.guid}/stats", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_watched" in data
        assert "total_movies_watched" in data
        assert "total_episodes_watched" in data
        assert "total_watch_time_seconds" in data
        assert "total_watch_time_hours" in data
        assert "completed_content" in data
        assert "in_progress_content" in data

    async def test_get_user_stats_as_user_forbidden(
        self, client: AsyncClient, test_user: User, test_superuser: User, user_headers
    ):
        resp = await client.get(
            f"/api/users/{test_user.guid}/stats", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_get_user_stats_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        fake_guid = uuid.uuid4()
        resp = await client.get(
            f"/api/users/{fake_guid}/stats", headers=admin_headers
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/users/{user_guid} (additional cases)
# ---------------------------------------------------------------------------
class TestDeleteUserExtended:
    async def test_delete_nonexistent_user(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        fake_guid = uuid.uuid4()
        resp = await client.delete(
            f"/api/users/{fake_guid}", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_self_delete(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User can delete their own account."""
        user = User(
            guid=uuid.uuid4(),
            email="selfdelete@example.com",
            first_name="Self",
            last_name="Delete",
            is_active=True,
            hashed_password=jwt_handler.get_password_hash("DeletePassword123"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        headers = auth_headers(user)
        resp = await client.delete(f"/api/users/{user.guid}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["message"] == "User deleted successfully"


# ---------------------------------------------------------------------------
# GET /api/users/{user_guid}/viewing-history (admin)
# ---------------------------------------------------------------------------
class TestUserViewingHistory:
    async def test_get_user_viewing_history_as_admin(
        self, client: AsyncClient, test_user: User, test_superuser: User, admin_headers
    ):
        resp = await client.get(
            f"/api/users/{test_user.guid}/viewing-history", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 0

    async def test_get_user_viewing_history_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/users/{test_user.guid}/viewing-history", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_get_user_viewing_history_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        fake_guid = uuid.uuid4()
        resp = await client.get(
            f"/api/users/{fake_guid}/viewing-history", headers=admin_headers
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/users/{user_guid} — OIDC email change branch
# ---------------------------------------------------------------------------
class TestUpdateUserOIDC:
    async def test_oidc_user_cannot_change_email(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """OIDC user cannot change their own email."""
        user = User(
            guid=uuid.uuid4(),
            email="oidcuser@example.com",
            first_name="OIDC",
            last_name="User",
            oidc_sub="oidc-sub-xxx",
            is_active=True,
            hashed_password=jwt_handler.get_password_hash("OidcPass123"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        headers = auth_headers(user)
        resp = await client.put(
            f"/api/users/{user.guid}",
            json={"email": "newemail@example.com"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "OIDC users cannot change" in resp.json()["detail"]

    async def test_oidc_user_can_change_other_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """OIDC user can update non-email fields."""
        user = User(
            guid=uuid.uuid4(),
            email="oidcfields@example.com",
            first_name="OIDC",
            last_name="Fields",
            oidc_sub="oidc-sub-yyy",
            is_active=True,
            hashed_password=jwt_handler.get_password_hash("OidcPass123"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        headers = auth_headers(user)
        resp = await client.put(
            f"/api/users/{user.guid}",
            json={"first_name": "UpdatedOIDC"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["first_name"] == "UpdatedOIDC"

    async def test_update_user_not_found_as_admin(
        self, client: AsyncClient, admin_headers
    ):
        fake_guid = uuid.uuid4()
        resp = await client.put(
            f"/api/users/{fake_guid}",
            json={"first_name": "Ghost"},
            headers=admin_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/users/{user_guid}/password — additional branches
# ---------------------------------------------------------------------------
class TestChangePasswordExtended:
    async def test_oidc_user_cannot_change_password(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """OIDC user cannot change password."""
        user = User(
            guid=uuid.uuid4(),
            email="oidcnopass@example.com",
            first_name="OIDC",
            last_name="NoPass",
            oidc_sub="oidc-nopass-sub",
            is_active=True,
            hashed_password=jwt_handler.get_password_hash("OidcPassXYZ"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        headers = auth_headers(user)
        resp = await client.put(
            f"/api/users/{user.guid}/password",
            json={"current_password": "OidcPassXYZ", "new_password": "NewPass123"},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "OIDC users cannot change" in resp.json()["detail"]

    async def test_user_no_password_set(
        self, client: AsyncClient, db_session: AsyncSession, admin_headers
    ):
        """User with no hashed_password returns 400."""
        user = User(
            guid=uuid.uuid4(),
            email="nopassset@example.com",
            first_name="No",
            last_name="Pass",
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Admin can try to change any user's password
        resp = await client.put(
            f"/api/users/{user.guid}/password",
            json={"current_password": "anything", "new_password": "NewPass123"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "no password set" in resp.json()["detail"]

    async def test_change_password_user_not_found(
        self, client: AsyncClient, admin_headers
    ):
        fake_guid = uuid.uuid4()
        resp = await client.put(
            f"/api/users/{fake_guid}/password",
            json={"current_password": "x", "new_password": "y"},
            headers=admin_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Codec settings
# ---------------------------------------------------------------------------
class TestCodecSettings:
    async def test_get_codec_settings(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/users/me/codec-settings", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "supported_video_codecs" in data
        assert "supported_audio_codecs" in data
        assert "codec_match_bonus" in data
        assert "codec_mismatch_penalty" in data

    async def test_update_codec_settings(self, client: AsyncClient, user_headers):
        resp = await client.put(
            "/api/users/me/codec-settings",
            json={
                "supported_video_codecs": ["h264", "h265"],
                "supported_audio_codecs": ["aac", "opus"],
                "codec_match_bonus": 10,
                "codec_mismatch_penalty": 5,
            },
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["supported_video_codecs"] == ["h264", "h265"]
        assert data["supported_audio_codecs"] == ["aac", "opus"]
        assert data["codec_match_bonus"] == 10

    async def test_get_codec_settings_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/users/me/codec-settings")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Display preferences
# ---------------------------------------------------------------------------
class TestDisplayPreferences:
    async def test_get_display_preferences_defaults(self, client: AsyncClient, user_headers):
        resp = await client.get(
            "/api/users/me/display-preferences/home?client=web",
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["preference_id"] == "home"
        assert data["client"] == "web"
        assert data["view_type"] == "poster"
        assert data["sort_by"] == "name"
        assert data["sort_order"] == "ascending"
        assert data["show_backdrops"] is True

    async def test_update_display_preferences_for_client_view(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        resp = await client.put(
            "/api/users/me/display-preferences/home?client=web",
            json={
                "view_type": "list",
                "sort_by": "release_date",
                "sort_order": "descending",
                "index_by": "genre",
                "remember_indexing": True,
                "show_backdrops": False,
                "show_sidebar": False,
                "chromecast_version": "stable",
                "custom": {"card_size": "compact"},
            },
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["preference_id"] == "home"
        assert data["client"] == "web"
        assert data["view_type"] == "list"
        assert data["sort_by"] == "release_date"
        assert data["sort_order"] == "descending"
        assert data["index_by"] == "genre"
        assert data["remember_indexing"] is True
        assert data["show_backdrops"] is False
        assert data["chromecast_version"] == "stable"
        assert data["custom"] == {"card_size": "compact"}

        await db_session.refresh(test_user)
        assert test_user.display_preferences["web:home"]["view_type"] == "list"
        assert test_user.display_preferences["web:home"]["chromecast_version"] == "stable"

        mobile = await client.get(
            "/api/users/me/display-preferences/home?client=mobile",
            headers=user_headers,
        )
        assert mobile.status_code == 200
        assert mobile.json()["view_type"] == "poster"

    async def test_display_preferences_require_auth(self, client: AsyncClient):
        resp = await client.get("/api/users/me/display-preferences/home")

        assert resp.status_code == 401

    async def test_admin_can_manage_user_display_preferences(
        self, client: AsyncClient, test_user: User, admin_headers
    ):
        resp = await client.put(
            f"/api/users/{test_user.guid}/display-preferences/library?client=tv",
            json={
                "view_type": "grid",
                "sort_by": "date_added",
                "sort_order": "descending",
                "show_sidebar": False,
                "enable_theme_songs": True,
            },
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["client"] == "tv"
        assert resp.json()["view_type"] == "grid"
        assert resp.json()["enable_theme_songs"] is True

        fetched = await client.get(
            f"/api/users/{test_user.guid}/display-preferences/library?client=tv",
            headers=admin_headers,
        )
        assert fetched.status_code == 200
        assert fetched.json()["sort_by"] == "date_added"

    async def test_regular_user_cannot_manage_other_display_preferences(
        self, client: AsyncClient, test_superuser: User, user_headers
    ):
        resp = await client.get(
            f"/api/users/{test_superuser.guid}/display-preferences/home",
            headers=user_headers,
        )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# User policy overrides
# ---------------------------------------------------------------------------
class TestUserPolicyOverrides:
    async def test_me_library_access_maps_effective_permissions_to_libraries(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, admin_headers, user_headers
    ):
        movies = await _create_library(db_session, name="Movies", type="MOVIES")
        shows = await _create_library(
            db_session,
            name="Shows",
            type="SHOWS",
            plugin_id="shows",
            path="/data/library/shows",
        )

        override_resp = await client.put(
            f"/api/users/{test_user.guid}/permission-overrides",
            headers=admin_headers,
            json={"allowed_libraries": ["movies"]},
        )
        assert override_resp.status_code == 200

        resp = await client.get("/api/users/me/library-access", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == str(test_user.guid)
        access = {item["library_guid"]: item for item in data["items"]}
        assert access[str(movies.guid)]["permission_key"] == "movies"
        assert access[str(movies.guid)]["allowed"] is True
        assert access[str(shows.guid)]["permission_key"] == "series"
        assert access[str(shows.guid)]["allowed"] is False

    async def test_admin_can_view_user_library_access(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, admin_headers
    ):
        library = await _create_library(db_session, name="Books", type="BOOKS")

        resp = await client.get(
            f"/api/users/{test_user.guid}/library-access",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == str(test_user.guid)
        assert data["total"] >= 1
        access = {item["library_guid"]: item for item in data["items"]}
        assert access[str(library.guid)]["permission_key"] == "books"

    async def test_regular_user_cannot_view_other_user_library_access(
        self, client: AsyncClient, test_superuser: User, user_headers
    ):
        resp = await client.get(
            f"/api/users/{test_superuser.guid}/library-access",
            headers=user_headers,
        )

        assert resp.status_code == 403

    async def test_admin_sets_remote_access_and_access_schedules(
        self, client: AsyncClient, test_user: User, admin_headers, user_headers
    ):
        today = datetime.now().strftime("%A").lower()

        resp = await client.put(
            f"/api/users/{test_user.guid}/permission-overrides",
            headers=admin_headers,
            json={
                "remote_access_enabled": False,
                "access_schedules": [
                    {"day_of_week": today, "start_hour": 0, "end_hour": 24}
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["remote_access_enabled"] is False
        assert data["access_schedules"] == [
            {"day_of_week": today, "start_hour": 0, "end_hour": 24}
        ]

        permissions = await client.get(
            "/api/users/me/permissions", headers=user_headers
        )
        assert permissions.status_code == 200
        effective = permissions.json()
        assert effective["remote_access_enabled"] is False
        assert effective["access_schedule_active"] is True
        assert effective["access_schedules"][0]["day_of_week"] == today

    async def test_access_schedule_can_block_current_window(
        self, client: AsyncClient, test_user: User, admin_headers, user_headers
    ):
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%A").lower()

        resp = await client.put(
            f"/api/users/{test_user.guid}/permission-overrides",
            headers=admin_headers,
            json={
                "access_schedules": [
                    {"day_of_week": tomorrow, "start_hour": 0, "end_hour": 24}
                ],
            },
        )

        assert resp.status_code == 200
        permissions = await client.get(
            "/api/users/me/permissions", headers=user_headers
        )
        assert permissions.status_code == 200
        assert permissions.json()["access_schedule_active"] is False

    async def test_regular_user_cannot_update_policy_overrides(
        self, client: AsyncClient, test_superuser: User, user_headers
    ):
        resp = await client.put(
            f"/api/users/{test_superuser.guid}/permission-overrides",
            headers=user_headers,
            json={"remote_access_enabled": False},
        )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/users/{user_guid}/invites — admin endpoint
# ---------------------------------------------------------------------------
class TestUserInvites:
    async def test_get_user_invites_as_admin(
        self, client: AsyncClient, test_user: User, admin_headers
    ):
        resp = await client.get(
            f"/api/users/{test_user.guid}/invites", headers=admin_headers
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_user_invites_not_found(
        self, client: AsyncClient, admin_headers
    ):
        fake_guid = uuid.uuid4()
        resp = await client.get(
            f"/api/users/{fake_guid}/invites", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_get_user_invites_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/users/{test_user.guid}/invites", headers=user_headers
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/users/{user_guid}/friendships — admin endpoint
# ---------------------------------------------------------------------------
class TestUserFriendships:
    async def test_get_user_friendships_as_admin(
        self, client: AsyncClient, test_user: User, admin_headers
    ):
        resp = await client.get(
            f"/api/users/{test_user.guid}/friendships", headers=admin_headers
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_user_friendships_not_found(
        self, client: AsyncClient, admin_headers
    ):
        fake_guid = uuid.uuid4()
        resp = await client.get(
            f"/api/users/{fake_guid}/friendships", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_get_user_friendships_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/users/{test_user.guid}/friendships", headers=user_headers
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Language settings — user not found edge case
# ---------------------------------------------------------------------------
class TestLanguageSettingsEdge:
    async def test_update_language_settings_partial(self, client: AsyncClient, user_headers):
        """Update only one language setting."""
        resp = await client.put(
            "/api/users/me/language-settings",
            json={"ui_language": "ja-JP"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ui_language"] == "ja-JP"
