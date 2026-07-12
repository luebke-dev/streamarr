"""Tests for AuthService – covers uncovered lines."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.user import User
from pyrate.services.auth import AuthService, _get_app_url, _get_email_i18n


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(**overrides) -> User:
    defaults = dict(
        guid=uuid.uuid4(),
        email="alice@example.com",
        first_name="Alice",
        last_name="Smith",
        is_active=True,
        is_superuser=False,
        hashed_password="$2b$12$hashed",
        email_verified=False,
        ui_language="en-US",
    )
    defaults.update(overrides)
    u = MagicMock(spec=User)
    for k, v in defaults.items():
        setattr(u, k, v)
    return u


# ---------------------------------------------------------------------------
# _get_site_name exception fallback (line 97-98)
# ---------------------------------------------------------------------------

class TestGetSiteNameFallback:
    @pytest.mark.asyncio
    async def test_get_site_name_exception_returns_fallback(self, db_session: AsyncSession):
        """When SettingsService.get raises, fallback to 'Pyrate Media'."""
        service = AuthService(db_session)
        with patch("pyrate.services.auth.AuthService._get_site_name") as mock_gsn:
            # Simulate the real implementation hitting an exception
            pass

        # Test the actual implementation
        with patch("pyrate.services.settings.SettingsService.get", side_effect=Exception("db down")):
            result = await service._get_site_name()
        assert result == "Pyrate Media"


# ---------------------------------------------------------------------------
# _send_password_reset_email failure path (line 166)
# ---------------------------------------------------------------------------

class TestSendPasswordResetEmailFailure:
    @pytest.mark.asyncio
    async def test_send_password_reset_email_failure(self, db_session: AsyncSession):
        """When email sending fails, returns False and logs warning."""
        service = AuthService(db_session)
        user = _make_user()

        with patch("pyrate.services.auth.jwt_handler") as mock_jwt, \
             patch("pyrate.services.auth.email_service") as mock_email:
            mock_jwt.create_password_reset_token.return_value = "reset-token"
            mock_email.send_email = AsyncMock(return_value=False)

            result = await service._send_password_reset_email(user, app_name="TestApp")

        assert result is False


# ---------------------------------------------------------------------------
# _send_verification_email i18n path (line 108)
# ---------------------------------------------------------------------------

class TestSendVerificationEmail:
    @pytest.mark.asyncio
    async def test_send_verification_email_calls_i18n(self, db_session: AsyncSession):
        """Verify _send_verification_email uses i18n strings."""
        service = AuthService(db_session)
        user = _make_user(ui_language="de-DE")

        with patch("pyrate.services.auth.jwt_handler") as mock_jwt, \
             patch("pyrate.services.auth.email_service") as mock_email:
            mock_jwt.create_email_verify_token.return_value = "verify-token"
            mock_email.send_email = AsyncMock(return_value=True)

            result = await service._send_verification_email(user, app_name="TestApp")

        assert result is True
        call_kwargs = mock_email.send_email.call_args
        assert "verify_email" in str(call_kwargs)


# ---------------------------------------------------------------------------
# verify_email paths (lines 293, 299, 303, 396, 402)
# ---------------------------------------------------------------------------

class TestVerifyEmail:
    @pytest.mark.asyncio
    async def test_verify_email_invalid_payload(self, db_session: AsyncSession):
        """verify_email raises when payload has no sub or email (line 389)."""
        service = AuthService(db_session)
        with patch("pyrate.services.auth.jwt_handler") as mock_jwt:
            mock_jwt.verify_email_verify_token.return_value = {"sub": None, "email": None}
            with pytest.raises(ValueError, match="invalid_token_payload"):
                await service.verify_email("some-token")

    @pytest.mark.asyncio
    async def test_verify_email_user_not_found(self, db_session: AsyncSession):
        """verify_email raises when user not found (line 396)."""
        service = AuthService(db_session)
        with patch("pyrate.services.auth.jwt_handler") as mock_jwt:
            mock_jwt.verify_email_verify_token.return_value = {
                "sub": str(uuid.uuid4()),
                "email": "test@example.com",
            }
            with pytest.raises(ValueError, match="user_not_found"):
                await service.verify_email("some-token")

    @pytest.mark.asyncio
    async def test_verify_email_email_mismatch(self, db_session: AsyncSession, test_user: User):
        """verify_email raises when email doesn't match (line 402)."""
        service = AuthService(db_session)
        with patch("pyrate.services.auth.jwt_handler") as mock_jwt:
            mock_jwt.verify_email_verify_token.return_value = {
                "sub": str(test_user.guid),
                "email": "wrong@example.com",
            }
            with pytest.raises(ValueError, match="email_mismatch"):
                await service.verify_email("some-token")


# ---------------------------------------------------------------------------
# resend_verification_email send_failed (line 422)
# ---------------------------------------------------------------------------

class TestResendVerificationEmail:
    @pytest.mark.asyncio
    async def test_resend_verification_send_failed(self, db_session: AsyncSession):
        """resend_verification_email raises 'send_failed' when email fails."""
        service = AuthService(db_session)
        user = _make_user(email_verified=False)

        with patch.object(service, "_get_site_name", return_value="TestApp"), \
             patch.object(service, "_send_verification_email", return_value=False):
            with pytest.raises(ValueError, match="send_failed"):
                await service.resend_verification_email(user)


# ---------------------------------------------------------------------------
# register_with_invite: invite_use_failed (line 324)
# ---------------------------------------------------------------------------

class TestRegisterWithInvite:
    @pytest.mark.asyncio
    async def test_register_invite_use_failed(self, db_session: AsyncSession):
        """register_with_invite raises when use_invite returns None."""
        service = AuthService(db_session)

        mock_invite_svc = MagicMock()
        mock_invite_svc.get_valid_by_token = AsyncMock(return_value=MagicMock(guid=uuid.uuid4()))
        mock_invite_svc.use_invite = AsyncMock(return_value=None)

        with patch("pyrate.services.auth.settings") as mock_settings, \
             patch("pyrate.services.auth.jwt_handler") as mock_jwt, \
             patch("pyrate.services.auth.AuthService._get_site_name", return_value="Test"), \
             patch("pyrate.services.invite.InviteService", return_value=mock_invite_svc):
            mock_settings.invites.enabled = True
            mock_settings.oidc.local_auth_enabled = True
            mock_settings.oidc.min_password_length = 8
            mock_jwt.verify_invite_token.return_value = {"invite_id": "abc"}

            # Mock db to return no existing user
            original_execute = db_session.execute

            async def mock_execute(stmt, *args, **kwargs):
                result = await original_execute(stmt, *args, **kwargs)
                return result

            with pytest.raises(ValueError, match="invite_use_failed"):
                await service.register_with_invite(
                    email="newuser@example.com",
                    password="Longpassword123!",
                    first_name="New",
                    last_name="User",
                    invite_token="valid-token",
                )

    @pytest.mark.asyncio
    async def test_register_auto_befriend_failure(self, db_session: AsyncSession):
        """Auto-befriend exception is caught and logged (lines 358-359)."""
        service = AuthService(db_session)

        mock_invite = MagicMock()
        mock_invite.guid = uuid.uuid4()
        mock_invite.created_by_user_id = uuid.uuid4()

        mock_invite_svc = MagicMock()
        mock_invite_svc.get_valid_by_token = AsyncMock(return_value=mock_invite)
        mock_invite_result = MagicMock()
        mock_invite_svc.use_invite = AsyncMock(return_value=mock_invite_result)

        mock_friendship_svc = MagicMock()
        mock_friendship_svc.create_accepted = AsyncMock(side_effect=Exception("friendship error"))

        with patch("pyrate.services.auth.settings") as mock_settings, \
             patch("pyrate.services.auth.jwt_handler") as mock_jwt, \
             patch("pyrate.services.auth.AuthService._get_site_name", return_value="Test"), \
             patch("pyrate.services.auth.AuthService._send_verification_email", return_value=True), \
             patch("pyrate.services.invite.InviteService", return_value=mock_invite_svc), \
             patch("pyrate.services.friendship.FriendshipService", return_value=mock_friendship_svc):
            mock_settings.invites.enabled = True
            mock_settings.oidc.local_auth_enabled = True
            mock_settings.oidc.min_password_length = 8
            mock_jwt.verify_invite_token.return_value = {"invite_id": "abc"}
            mock_jwt.get_password_hash.return_value = "$2b$hashed"
            mock_jwt.create_access_token.return_value = "access"
            mock_jwt.create_refresh_token.return_value = "refresh"
            mock_settings.oidc.jwt_access_token_expire_minutes = 30

            user = await service.register_with_invite(
                email="newuser2@example.com",
                password="Longpassword123!",
                first_name="New",
                last_name="User",
                invite_token="valid-token",
            )

            # Should succeed despite friendship error. Registration no longer
            # issues tokens (email must be verified first) — it returns the User.
            assert user is not None
            assert user.email == "newuser2@example.com"
            assert user.email_verified is False


# ---------------------------------------------------------------------------
# reset_password: invalid_token_payload (line 471)
# ---------------------------------------------------------------------------

class TestResetPassword:
    @pytest.mark.asyncio
    async def test_reset_password_invalid_token_payload(self, db_session: AsyncSession):
        """reset_password raises when payload missing sub/email."""
        service = AuthService(db_session)
        with patch("pyrate.services.auth.settings") as mock_settings, \
             patch("pyrate.services.auth.jwt_handler") as mock_jwt:
            mock_settings.oidc.local_auth_enabled = True
            mock_jwt.verify_password_reset_token.return_value = {"sub": None, "email": None}
            with pytest.raises(ValueError, match="invalid_token_payload"):
                await service.reset_password("token", "newpass123")
