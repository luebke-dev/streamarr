"""Tests for auth API endpoints (/api/auth/*)."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.auth.jwt_handler import jwt_handler
from streamarr.models.invite import Invite
from streamarr.models.library import Library
from streamarr.models.media import MediaItem, MediaType
from streamarr.models.user import User

from .conftest import auth_headers


# ---------------------------------------------------------------------------
# GET /api/auth/status
# ---------------------------------------------------------------------------
class TestAuthStatus:
    async def test_status_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["user"] is None
        assert "local" in data["auth_methods"]

    async def test_status_authenticated(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get("/api/auth/status", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"]["email"] == test_user.email

    async def test_status_invalid_token(self, client: AsyncClient):
        resp = await client.get(
            "/api/auth/status",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False


# ---------------------------------------------------------------------------
# POST /api/auth/local/login
# ---------------------------------------------------------------------------
class TestLocalLogin:
    async def test_login_success(self, client: AsyncClient, test_user: User):
        resp = await client.post(
            "/api/auth/local/login",
            json={"email": test_user.email, "password": "TestPassword123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    async def test_login_wrong_password(self, client: AsyncClient, test_user: User):
        resp = await client.post(
            "/api/auth/local/login",
            json={"email": test_user.email, "password": "WrongPassword"},
        )
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        resp = await client.post(
            "/api/auth/local/login",
            json={"email": "nobody@example.com", "password": "whatever"},
        )
        assert resp.status_code == 401

    async def test_login_inactive_user(self, client: AsyncClient, db_session):
        from streamarr.models.user import User as UserModel

        import uuid

        user = UserModel(
            guid=uuid.uuid4(),
            email="inactive@example.com",
            first_name="In",
            last_name="Active",
            is_active=False,
            hashed_password=jwt_handler.get_password_hash("SomePassword1"),
        )
        db_session.add(user)
        await db_session.commit()

        resp = await client.post(
            "/api/auth/local/login",
            json={"email": "inactive@example.com", "password": "SomePassword1"},
        )
        assert resp.status_code == 401

    async def test_login_with_device_id(self, client: AsyncClient, test_user: User):
        resp = await client.post(
            "/api/auth/local/login",
            json={
                "email": test_user.email,
                "password": "TestPassword123",
                "device_id": "test-device-001",
                "device_info": {"browser": "Chrome", "platform": "Linux"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    async def test_login_user_no_password(self, client: AsyncClient, db_session):
        import uuid

        user = User(
            guid=uuid.uuid4(),
            email="nopassword@example.com",
            first_name="No",
            last_name="Password",
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()

        resp = await client.post(
            "/api/auth/local/login",
            json={"email": "nopassword@example.com", "password": "anything"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------
class TestRefreshToken:
    async def test_refresh_success(self, client: AsyncClient, test_user: User):
        refresh = jwt_handler.create_refresh_token({"sub": str(test_user.guid)})
        resp = await client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {refresh}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_with_access_token_fails(self, client: AsyncClient, test_user: User):
        access = jwt_handler.create_access_token({"sub": str(test_user.guid)})
        resp = await client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 401

    async def test_refresh_no_token(self, client: AsyncClient):
        resp = await client.post("/api/auth/refresh")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------
class TestGetMe:
    async def test_me_authenticated(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get("/api/auth/me", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == test_user.email
        assert data["first_name"] == test_user.first_name
        assert data["is_active"] is True

    async def test_me_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/auth/me")
        assert resp.status_code in (401, 403)

    async def test_me_superuser(self, client: AsyncClient, test_superuser: User, admin_headers):
        resp = await client.get("/api/auth/me", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_superuser"] is True


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------
class TestLogout:
    async def test_logout(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.post("/api/auth/logout", headers=user_headers)
        assert resp.status_code == 200

    async def test_logout_unauthenticated(self, client: AsyncClient):
        resp = await client.post("/api/auth/logout")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/auth/background
# ---------------------------------------------------------------------------
class TestBackground:
    async def test_background_with_media(self, client: AsyncClient, db_session: AsyncSession):
        _now = datetime.now(UTC)
        library = Library(
            guid=uuid.uuid4(),
            name="Test Movies",
            type="MOVIES",
            plugin_id="movies",
            path="/library/movies",
            enabled=True,
            created_at=_now,
            updated_at=_now,
        )
        db_session.add(library)
        await db_session.flush()

        media = MediaItem(
            guid=uuid.uuid4(),
            title="Test Movie",
            media_type=MediaType.MOVIES,
            backdrop_path="/testbackdrop.jpg",
            release_date=datetime(2024, 1, 15),
            library_guid=library.guid,
        )
        db_session.add(media)
        await db_session.commit()

        resp = await client.get("/api/auth/background")
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] is not None
        assert "testbackdrop.jpg" in data["url"]
        assert data["title"] == "Test Movie"
        assert data["year"] == 2024

    async def test_background_empty_db(self, client: AsyncClient):
        resp = await client.get("/api/auth/background")
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] is None
        assert data["title"] is None
        assert data["year"] is None

    async def test_background_no_release_date(self, client: AsyncClient, db_session: AsyncSession):
        _now = datetime.now(UTC)
        library = Library(
            guid=uuid.uuid4(),
            name="Test Movies 2",
            type="MOVIES",
            plugin_id="movies",
            path="/library/movies2",
            enabled=True,
            created_at=_now,
            updated_at=_now,
        )
        db_session.add(library)
        await db_session.flush()

        media = MediaItem(
            guid=uuid.uuid4(),
            title="No Date Movie",
            media_type=MediaType.MOVIES,
            backdrop_path="/nodate.jpg",
            release_date=None,
            library_guid=library.guid,
        )
        db_session.add(media)
        await db_session.commit()

        resp = await client.get("/api/auth/background")
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] is not None
        assert data["year"] is None


# ---------------------------------------------------------------------------
# POST /api/auth/register
# ---------------------------------------------------------------------------
class TestRegister:
    async def test_register_success(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User
    ):
        invite_token = jwt_handler.create_invite_token(
            {"created_by_user_id": str(test_superuser.guid)},
            expires_delta=timedelta(hours=24),
        )
        invite = Invite(
            guid=uuid.uuid4(),
            token=invite_token,
            created_by_user_id=test_superuser.guid,
            is_active=True,
            is_used=False,
            expires_at=datetime(2030, 1, 1),
            max_uses=1,
            current_uses=0,
        )
        db_session.add(invite)
        await db_session.commit()

        resp = await client.post(
            "/api/auth/register",
            json={
                "invite_token": invite_token,
                "email": "newuser@example.com",
                "first_name": "New",
                "last_name": "User",
                "preferred_username": "newuser",
                "password": "SecurePass123!",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Registration is a hard email gate: no tokens until the address is
        # verified — the endpoint returns a verification_required result.
        assert data["status"] == "verification_required"
        assert data["email"] == "newuser@example.com"
        assert "access_token" not in data

    async def test_register_invites_disabled(self, client: AsyncClient):
        with patch("streamarr.services.auth.settings") as mock_settings:
            mock_settings.invites.enabled = False
            resp = await client.post(
                "/api/auth/register",
                json={
                    "invite_token": "sometoken",
                    "email": "test@example.com",
                    "first_name": "Test",
                    "last_name": "User",
                },
            )
            assert resp.status_code == 403

    async def test_register_invalid_token(self, client: AsyncClient):
        resp = await client.post(
            "/api/auth/register",
            json={
                "invite_token": "invalid.jwt.token",
                "email": "test@example.com",
                "first_name": "Test",
                "last_name": "User",
            },
        )
        assert resp.status_code == 400

    async def test_register_expired_invite(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User
    ):
        invite_token = jwt_handler.create_invite_token(
            {"created_by_user_id": str(test_superuser.guid)},
            expires_delta=timedelta(hours=24),
        )
        # Invite exists in DB but is expired
        invite = Invite(
            guid=uuid.uuid4(),
            token=invite_token,
            created_by_user_id=test_superuser.guid,
            is_active=True,
            is_used=False,
            expires_at=datetime(2020, 1, 1),  # expired
            max_uses=1,
            current_uses=0,
        )
        db_session.add(invite)
        await db_session.commit()

        resp = await client.post(
            "/api/auth/register",
            json={
                "invite_token": invite_token,
                "email": "expired@example.com",
                "first_name": "Expired",
                "last_name": "User",
            },
        )
        assert resp.status_code == 400

    async def test_register_duplicate_email(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User
    ):
        invite_token = jwt_handler.create_invite_token(
            {"created_by_user_id": str(test_superuser.guid)},
            expires_delta=timedelta(hours=24),
        )
        invite = Invite(
            guid=uuid.uuid4(),
            token=invite_token,
            created_by_user_id=test_superuser.guid,
            is_active=True,
            is_used=False,
            expires_at=datetime(2030, 1, 1),
            max_uses=1,
            current_uses=0,
        )
        db_session.add(invite)

        # Create existing user with same email
        existing = User(
            guid=uuid.uuid4(),
            email="duplicate@example.com",
            first_name="Existing",
            last_name="User",
            is_active=True,
        )
        db_session.add(existing)
        await db_session.commit()

        resp = await client.post(
            "/api/auth/register",
            json={
                "invite_token": invite_token,
                "email": "duplicate@example.com",
                "first_name": "New",
                "last_name": "User",
            },
        )
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    async def test_register_with_password(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User
    ):
        invite_token = jwt_handler.create_invite_token(
            {"created_by_user_id": str(test_superuser.guid)},
            expires_delta=timedelta(hours=24),
        )
        invite = Invite(
            guid=uuid.uuid4(),
            token=invite_token,
            created_by_user_id=test_superuser.guid,
            is_active=True,
            is_used=False,
            expires_at=datetime(2030, 1, 1),
            max_uses=1,
            current_uses=0,
        )
        db_session.add(invite)
        await db_session.commit()

        resp = await client.post(
            "/api/auth/register",
            json={
                "invite_token": invite_token,
                "email": "withpass@example.com",
                "first_name": "With",
                "last_name": "Pass",
                "password": "StrongPassword1!",
                "ui_language": "de-DE",
                "audio_language": "de",
                "subtitle_language": "de",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "verification_required"
        assert "access_token" not in data


# ---------------------------------------------------------------------------
# GET /api/auth/login (OIDC)
# ---------------------------------------------------------------------------
class TestOIDCLogin:
    async def test_oidc_login_redirect(self, client: AsyncClient):
        """OIDC login should create a signed state and redirect to the provider."""
        with (
            patch("streamarr.api.v1.auth.require_oidc_enabled"),
            patch("streamarr.api.v1.auth.oidc_client") as mock_oidc,
        ):
            mock_oidc.get_authorization_url = AsyncMock(
                return_value="https://idp.example.com/authorize?state=test"
            )
            resp = await client.get("/api/auth/login", follow_redirects=False)
            assert resp.status_code in (302, 307)
            assert resp.headers["location"] == "https://idp.example.com/authorize?state=test"
            assert mock_oidc.get_authorization_url.await_args.args[0]
            assert mock_oidc.get_authorization_url.await_args.kwargs["nonce"]


# ---------------------------------------------------------------------------
# GET /api/auth/callback (OIDC)
# ---------------------------------------------------------------------------
class TestOIDCCallback:
    async def test_callback_invalid_state(self, client: AsyncClient):
        """Invalid signed state is rejected without requiring SessionMiddleware."""
        with patch("streamarr.api.v1.auth.require_oidc_enabled"):
            resp = await client.get(
                "/api/auth/callback",
                params={"code": "authcode", "state": "bad_state"},
            )
            assert resp.status_code == 400

    async def test_callback_success_redirects_to_frontend(
        self, client: AsyncClient, test_user: User
    ):
        from streamarr.api.v1.auth import _create_oidc_state

        state, _nonce = _create_oidc_state(return_to="/media/abc")
        with (
            patch("streamarr.api.v1.auth.require_oidc_enabled"),
            patch("streamarr.api.v1.auth.get_app_url", return_value="http://frontend.local"),
            patch("streamarr.api.v1.auth.oidc_client") as mock_oidc,
            patch("streamarr.api.v1.auth.AuthService") as mock_auth_service,
        ):
            mock_oidc.exchange_code_for_tokens = AsyncMock(
                return_value={"id_token": "id-token"}
            )
            mock_oidc.verify_id_token = AsyncMock(
                return_value={"sub": "oidc-sub", "email": test_user.email}
            )
            mock_oidc.map_claims_to_user_data.return_value = {
                "oidc_sub": "oidc-sub",
                "email": test_user.email,
            }
            svc = mock_auth_service.return_value
            svc.get_or_create_oidc_user = AsyncMock(return_value=test_user)
            svc._create_token_pair.return_value = ("access-token", "refresh-token", 1800)

            resp = await client.get(
                "/api/auth/callback",
                params={"code": "authcode", "state": state},
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        location = resp.headers["location"]
        assert location.startswith("http://frontend.local/auth/callback?return_to=/media/abc")
        # Only the short-lived access token travels in the fragment now; the
        # refresh token is delivered as an httpOnly cookie, not in the URL.
        assert "#access_token=access-token" in location
        assert "refresh_token" not in location
        assert "streamarr_refresh=refresh-token" in resp.headers.get("set-cookie", "")


# ---------------------------------------------------------------------------
# get_or_create_oidc_user (AuthService)
# ---------------------------------------------------------------------------
class TestGetOrCreateUser:
    async def test_existing_oidc_user(self, db_session: AsyncSession):
        from streamarr.services.auth import AuthService

        user = User(
            guid=uuid.uuid4(),
            email="oidcexisting@example.com",
            first_name="OIDC",
            last_name="Existing",
            oidc_sub="oidc-sub-123",
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()

        result = await AuthService(db_session).get_or_create_oidc_user(
            {
                "oidc_sub": "oidc-sub-123",
                "email": "oidcexisting@example.com",
                "first_name": "Updated",
            },
        )
        assert result.guid == user.guid
        assert result.first_name == "Updated"

    async def test_existing_email_user_link(self, db_session: AsyncSession):
        from streamarr.services.auth import AuthService

        user = User(
            guid=uuid.uuid4(),
            email="linkemail@example.com",
            first_name="Link",
            last_name="Email",
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()

        result = await AuthService(db_session).get_or_create_oidc_user(
            {
                "oidc_sub": "new-oidc-sub",
                "email": "linkemail@example.com",
                "first_name": "Link",
            },
        )
        assert result.guid == user.guid
        assert result.oidc_sub == "new-oidc-sub"

    async def test_new_user_auto_register(self, db_session: AsyncSession):
        from streamarr.services.auth import AuthService

        with patch("streamarr.services.auth.settings") as mock_settings:
            mock_settings.oidc.auto_register_users = True
            mock_settings.oidc.default_user_active = True
            mock_settings.oidc.default_user_superuser = False

            result = await AuthService(db_session).get_or_create_oidc_user(
                {
                    "oidc_sub": "brand-new-sub",
                    "email": "brandnew@example.com",
                    "first_name": "Brand",
                    "last_name": "New",
                    "oidc_provider": "keycloak",
                },
            )
            assert result.email == "brandnew@example.com"
            assert result.oidc_sub == "brand-new-sub"

    async def test_missing_oidc_sub(self, db_session: AsyncSession):
        from streamarr.services.auth import AuthService

        with pytest.raises(ValueError, match="missing_oidc_sub"):
            await AuthService(db_session).get_or_create_oidc_user(
                {"email": "nosub@example.com"}
            )

    async def test_auto_register_disabled(self, db_session: AsyncSession):
        from streamarr.services.auth import AuthService

        with patch("streamarr.services.auth.settings") as mock_settings:
            mock_settings.oidc.auto_register_users = False

            with pytest.raises(ValueError, match="registration_disabled"):
                await AuthService(db_session).get_or_create_oidc_user(
                    {
                        "oidc_sub": "disabled-sub",
                        "email": "disabled@example.com",
                    },
                )

    async def test_no_email_for_creation(self, db_session: AsyncSession):
        from streamarr.services.auth import AuthService

        with patch("streamarr.services.auth.settings") as mock_settings:
            mock_settings.oidc.auto_register_users = True

            with pytest.raises(ValueError, match="email_required"):
                await AuthService(db_session).get_or_create_oidc_user(
                    {"oidc_sub": "no-email-sub"},
                )


# ---------------------------------------------------------------------------
# POST /api/auth/local/login — local_auth_not_enabled branch
# ---------------------------------------------------------------------------
class TestLocalLoginNotEnabled:
    async def test_local_auth_disabled(self, client: AsyncClient, test_user: User):
        """When local auth is disabled, login should return 501."""
        with patch("streamarr.services.auth.settings") as mock_settings:
            mock_settings.oidc.local_auth_enabled = False
            resp = await client.post(
                "/api/auth/local/login",
                json={"email": test_user.email, "password": "TestPassword123"},
            )
            assert resp.status_code == 501
            assert "not enabled" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/auth/logout — OIDC vs local logout branch
# ---------------------------------------------------------------------------
class TestLogoutBranches:
    async def test_logout_oidc_enabled(self, client: AsyncClient, test_user: User, user_headers):
        """When OIDC is enabled, logout returns a logout_url."""
        with patch("streamarr.api.v1.auth.oidc_client") as mock_oidc:
            mock_oidc.is_enabled.return_value = True
            mock_oidc.get_logout_url = AsyncMock(return_value="https://idp.example.com/logout")
            resp = await client.post("/api/auth/logout", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "logout_url" in data
        assert "https://idp.example.com/logout" == data["logout_url"]

    async def test_logout_local(self, client: AsyncClient, test_user: User, user_headers):
        """When OIDC is disabled, logout returns a success message."""
        with patch("streamarr.api.v1.auth.oidc_client") as mock_oidc:
            mock_oidc.is_enabled.return_value = False
            resp = await client.post("/api/auth/logout", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Logged out successfully"


# ---------------------------------------------------------------------------
# GET /api/auth/status — OIDC enabled branch
# ---------------------------------------------------------------------------
class TestAuthStatusOIDC:
    async def test_status_oidc_enabled(self, client: AsyncClient):
        """When OIDC is enabled, auth_methods should include 'oidc'."""
        with patch("streamarr.api.v1.auth.oidc_client") as mock_oidc:
            mock_oidc.is_enabled.return_value = True
            with patch("streamarr.api.v1.auth.settings") as mock_settings:
                mock_settings.oidc.local_auth_enabled = True
                resp = await client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "oidc" in data["auth_methods"]
        assert "local" in data["auth_methods"]
        assert data["oidc_enabled"] is True

    async def test_status_no_auth_methods(self, client: AsyncClient):
        """When both OIDC and local are disabled, auth_methods is empty."""
        with patch("streamarr.api.v1.auth.oidc_client") as mock_oidc:
            mock_oidc.is_enabled.return_value = False
            with patch("streamarr.api.v1.auth.settings") as mock_settings:
                mock_settings.oidc.local_auth_enabled = False
                resp = await client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_methods"] == []


# ---------------------------------------------------------------------------
# POST /api/auth/register — additional edge cases
# ---------------------------------------------------------------------------
class TestRegisterEdgeCases:
    async def test_register_without_password(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User
    ):
        """Register without password (local auth enabled, but no password provided)."""
        invite_token = jwt_handler.create_invite_token(
            {"created_by_user_id": str(test_superuser.guid)},
            expires_delta=timedelta(hours=24),
        )
        invite = Invite(
            guid=uuid.uuid4(),
            token=invite_token,
            created_by_user_id=test_superuser.guid,
            is_active=True,
            is_used=False,
            expires_at=datetime(2030, 1, 1),
            max_uses=1,
            current_uses=0,
        )
        db_session.add(invite)
        await db_session.commit()

        resp = await client.post(
            "/api/auth/register",
            json={
                "invite_token": invite_token,
                "email": "nopassregister@example.com",
                "first_name": "NoPass",
                "last_name": "Register",
                "preferred_username": "nopassreg",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "verification_required"
        assert "access_token" not in data

    async def test_register_with_language_settings(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User
    ):
        """Register with custom language settings."""
        invite_token = jwt_handler.create_invite_token(
            {"created_by_user_id": str(test_superuser.guid)},
            expires_delta=timedelta(hours=24),
        )
        invite = Invite(
            guid=uuid.uuid4(),
            token=invite_token,
            created_by_user_id=test_superuser.guid,
            is_active=True,
            is_used=False,
            expires_at=datetime(2030, 1, 1),
            max_uses=1,
            current_uses=0,
        )
        db_session.add(invite)
        await db_session.commit()

        resp = await client.post(
            "/api/auth/register",
            json={
                "invite_token": invite_token,
                "email": "languser@example.com",
                "first_name": "Lang",
                "last_name": "User",
                "ui_language": "fr-FR",
                "audio_language": "fr",
                "subtitle_language": "en",
            },
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/auth/forgot-password
# ---------------------------------------------------------------------------
class TestForgotPassword:
    async def test_forgot_password_existing_user(
        self, client: AsyncClient, test_user: User
    ):
        """Sends reset email for existing user, returns generic message."""
        with patch("streamarr.services.auth.email_service") as mock_email:
            mock_email.send_email = AsyncMock(return_value=True)
            resp = await client.post(
                "/api/auth/forgot-password",
                json={"email": test_user.email},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        # Must not reveal whether user exists
        assert "if" in data["message"].lower()

    async def test_forgot_password_nonexistent_email(self, client: AsyncClient):
        """Returns same message for non-existent email (no enumeration)."""
        resp = await client.post(
            "/api/auth/forgot-password",
            json={"email": "nobody@example.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

    async def test_forgot_password_sends_email(
        self, client: AsyncClient, test_user: User
    ):
        """Verify that the email service is called for valid users."""
        with patch("streamarr.services.auth.email_service") as mock_email:
            mock_email.send_email = AsyncMock(return_value=True)
            await client.post(
                "/api/auth/forgot-password",
                json={"email": test_user.email},
            )
            mock_email.send_email.assert_called_once()
            call_kwargs = mock_email.send_email.call_args
            assert call_kwargs.kwargs["to_email"] == test_user.email
            assert call_kwargs.kwargs["template_name"] == "password_reset"

    async def test_forgot_password_does_not_send_for_unknown(self, client: AsyncClient):
        """No email sent for unknown address."""
        with patch("streamarr.services.auth.email_service") as mock_email:
            mock_email.send_email = AsyncMock(return_value=True)
            await client.post(
                "/api/auth/forgot-password",
                json={"email": "nobody@example.com"},
            )
            mock_email.send_email.assert_not_called()

    async def test_forgot_password_inactive_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Inactive user should not receive reset email."""
        user = User(
            guid=uuid.uuid4(),
            email="inactive-reset@example.com",
            first_name="Inactive",
            last_name="User",
            is_active=False,
            hashed_password=jwt_handler.get_password_hash("SomePassword1"),
        )
        db_session.add(user)
        await db_session.commit()

        with patch("streamarr.services.auth.email_service") as mock_email:
            mock_email.send_email = AsyncMock(return_value=True)
            resp = await client.post(
                "/api/auth/forgot-password",
                json={"email": "inactive-reset@example.com"},
            )
            assert resp.status_code == 200
            mock_email.send_email.assert_not_called()

    async def test_forgot_password_oidc_only_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User without password (OIDC-only) should not get reset email."""
        user = User(
            guid=uuid.uuid4(),
            email="oidconly@example.com",
            first_name="OIDC",
            last_name="Only",
            is_active=True,
            hashed_password=None,
        )
        db_session.add(user)
        await db_session.commit()

        with patch("streamarr.services.auth.email_service") as mock_email:
            mock_email.send_email = AsyncMock(return_value=True)
            resp = await client.post(
                "/api/auth/forgot-password",
                json={"email": "oidconly@example.com"},
            )
            assert resp.status_code == 200
            mock_email.send_email.assert_not_called()

    async def test_forgot_password_local_auth_disabled(self, client: AsyncClient):
        """When local auth is disabled, forgot-password returns 501."""
        with patch("streamarr.services.auth.settings") as mock_settings:
            mock_settings.oidc.local_auth_enabled = False
            resp = await client.post(
                "/api/auth/forgot-password",
                json={"email": "test@example.com"},
            )
            assert resp.status_code == 501
            assert "not enabled" in resp.json()["detail"]

    async def test_forgot_password_case_insensitive(
        self, client: AsyncClient, test_user: User
    ):
        """Email lookup should be case-insensitive."""
        with patch("streamarr.services.auth.email_service") as mock_email:
            mock_email.send_email = AsyncMock(return_value=True)
            resp = await client.post(
                "/api/auth/forgot-password",
                json={"email": test_user.email.upper()},
            )
            assert resp.status_code == 200
            mock_email.send_email.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/auth/reset-password
# ---------------------------------------------------------------------------
class TestResetPassword:
    async def test_reset_password_success(
        self, client: AsyncClient, test_user: User
    ):
        """Successful password reset with valid token."""
        token = jwt_handler.create_password_reset_token(
            user_id=str(test_user.guid),
            email=test_user.email,
            password_hash=test_user.hashed_password,
        )
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "password": "NewSecurePass123!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "successfully" in data["message"].lower()

        # Verify new password works for login
        resp2 = await client.post(
            "/api/auth/local/login",
            json={"email": test_user.email, "password": "NewSecurePass123!"},
        )
        assert resp2.status_code == 200
        assert "access_token" in resp2.json()

    async def test_reset_password_old_password_no_longer_works(
        self, client: AsyncClient, test_user: User
    ):
        """After reset, old password should fail."""
        token = jwt_handler.create_password_reset_token(
            user_id=str(test_user.guid),
            email=test_user.email,
            password_hash=test_user.hashed_password,
        )
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "password": "BrandNewPass456!"},
        )
        assert resp.status_code == 200

        resp2 = await client.post(
            "/api/auth/local/login",
            json={"email": test_user.email, "password": "TestPassword123"},
        )
        assert resp2.status_code == 401

    async def test_reset_password_invalid_token(self, client: AsyncClient):
        """Invalid token should be rejected."""
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": "invalid.jwt.token", "password": "NewPassword123!"},
        )
        assert resp.status_code == 400
        assert "invalid" in resp.json()["detail"].lower() or "expired" in resp.json()["detail"].lower()

    async def test_reset_password_expired_token(
        self, client: AsyncClient, test_user: User
    ):
        """Expired token should be rejected."""
        # Create a token with negative expiry
        from datetime import UTC
        from unittest.mock import patch as _patch
        import jose.jwt as jose_jwt

        payload = {
            "sub": str(test_user.guid),
            "email": test_user.email,
            "type": "password_reset",
            "jti": str(uuid.uuid4()),
            "exp": datetime.now(UTC) + timedelta(seconds=-10),
            "iat": datetime.now(UTC) + timedelta(seconds=-70),
        }
        expired_token = jose_jwt.encode(
            payload, jwt_handler.secret_key, algorithm=jwt_handler.algorithm
        )

        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": expired_token, "password": "NewPassword123!"},
        )
        assert resp.status_code == 400

    async def test_reset_password_wrong_token_type(
        self, client: AsyncClient, test_user: User
    ):
        """Access token should not work as a reset token."""
        access_token = jwt_handler.create_access_token({"sub": str(test_user.guid)})
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": access_token, "password": "NewPassword123!"},
        )
        assert resp.status_code == 400

    async def test_reset_password_too_short(
        self, client: AsyncClient, test_user: User
    ):
        """Password below minimum length should be rejected."""
        token = jwt_handler.create_password_reset_token(
            user_id=str(test_user.guid),
            email=test_user.email,
            password_hash=test_user.hashed_password,
        )
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "password": "short"},
        )
        assert resp.status_code == 400
        assert "at least" in resp.json()["detail"].lower()

    async def test_reset_password_email_mismatch(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Token with different email than user's current email should fail."""
        user = User(
            guid=uuid.uuid4(),
            email="current@example.com",
            first_name="Email",
            last_name="Changed",
            is_active=True,
            hashed_password=jwt_handler.get_password_hash("OldPassword123"),
        )
        db_session.add(user)
        await db_session.commit()

        # Create token with old email
        token = jwt_handler.create_password_reset_token(
            user_id=str(user.guid),
            email="old@example.com",
        )
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "password": "NewPassword123!"},
        )
        assert resp.status_code == 400
        assert "match" in resp.json()["detail"].lower()

    async def test_reset_password_local_auth_disabled(self, client: AsyncClient):
        """When local auth is disabled, reset-password returns 501."""
        with patch("streamarr.services.auth.settings") as mock_settings:
            mock_settings.oidc.local_auth_enabled = False
            resp = await client.post(
                "/api/auth/reset-password",
                json={"token": "sometoken", "password": "NewPassword123!"},
            )
            assert resp.status_code == 501
            assert "not enabled" in resp.json()["detail"]

    async def test_reset_password_nonexistent_user(self, client: AsyncClient):
        """Token for a deleted/nonexistent user should fail."""
        fake_guid = str(uuid.uuid4())
        token = jwt_handler.create_password_reset_token(
            user_id=fake_guid,
            email="deleted@example.com",
        )
        resp = await client.post(
            "/api/auth/reset-password",
            json={"token": token, "password": "NewPassword123!"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/auth/verify-email
# ---------------------------------------------------------------------------
class TestVerifyEmail:
    async def test_verify_email_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Successful email verification with valid token."""
        user = User(
            guid=uuid.uuid4(),
            email="unverified@example.com",
            first_name="Unverified",
            last_name="User",
            is_active=True,
            email_verified=False,
            hashed_password=jwt_handler.get_password_hash("Password123"),
        )
        db_session.add(user)
        await db_session.commit()

        token = jwt_handler.create_email_verify_token(
            user_id=str(user.guid),
            email=user.email,
        )
        resp = await client.get(f"/api/auth/verify-email?token={token}")
        assert resp.status_code == 200
        data = resp.json()
        assert "verified" in data["message"].lower()

        # Verify user is now verified in DB
        await db_session.refresh(user)
        assert user.email_verified is True

    async def test_verify_email_invalid_token(self, client: AsyncClient):
        """Invalid token should be rejected."""
        resp = await client.get("/api/auth/verify-email?token=invalid.jwt.token")
        assert resp.status_code == 400

    async def test_verify_email_no_token(self, client: AsyncClient):
        """Missing token parameter should fail."""
        resp = await client.get("/api/auth/verify-email")
        assert resp.status_code == 422 or resp.status_code == 400

    async def test_verify_email_wrong_token_type(
        self, client: AsyncClient, test_user: User
    ):
        """Access token should not work as a verify token."""
        access_token = jwt_handler.create_access_token({"sub": str(test_user.guid)})
        resp = await client.get(f"/api/auth/verify-email?token={access_token}")
        assert resp.status_code == 400

    async def test_verify_email_already_verified(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verifying an already-verified email should still succeed."""
        user = User(
            guid=uuid.uuid4(),
            email="alreadyverified@example.com",
            first_name="Already",
            last_name="Verified",
            is_active=True,
            email_verified=True,
            hashed_password=jwt_handler.get_password_hash("Password123"),
        )
        db_session.add(user)
        await db_session.commit()

        token = jwt_handler.create_email_verify_token(
            user_id=str(user.guid),
            email=user.email,
        )
        resp = await client.get(f"/api/auth/verify-email?token={token}")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/auth/resend-verification
# ---------------------------------------------------------------------------
class TestResendVerification:
    async def test_resend_verification_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Resend verification for unverified user."""
        user = User(
            guid=uuid.uuid4(),
            email="resendme@example.com",
            first_name="Resend",
            last_name="Me",
            is_active=True,
            email_verified=False,
            hashed_password=jwt_handler.get_password_hash("Password123"),
        )
        db_session.add(user)
        await db_session.commit()

        with patch("streamarr.services.auth.email_service") as mock_email:
            mock_email.send_email = AsyncMock(return_value=True)
            resp = await client.post(
                "/api/auth/resend-verification", json={"email": user.email}
            )
        assert resp.status_code == 200
        # Public + enumeration-safe: a generic message regardless of account state.
        assert "verification" in resp.json()["message"].lower()

    async def test_resend_verification_already_verified(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Already verified user gets the same generic message, no email sent."""
        user = User(
            guid=uuid.uuid4(),
            email="alreadydone@example.com",
            first_name="Already",
            last_name="Done",
            is_active=True,
            email_verified=True,
            hashed_password=jwt_handler.get_password_hash("Password123"),
        )
        db_session.add(user)
        await db_session.commit()

        with patch("streamarr.services.auth.email_service") as mock_email:
            mock_email.send_email = AsyncMock(return_value=True)
            resp = await client.post(
                "/api/auth/resend-verification", json={"email": user.email}
            )
        assert resp.status_code == 200
        # Same generic response as for an unverified/unknown address.
        assert "verification" in resp.json()["message"].lower()
        # No email is sent for an already-verified account.
        mock_email.send_email.assert_not_called()

    async def test_resend_verification_requires_email(self, client: AsyncClient):
        """The public endpoint validates its body: missing email -> 422."""
        resp = await client.post("/api/auth/resend-verification", json={})
        assert resp.status_code == 422
