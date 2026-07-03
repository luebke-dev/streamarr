"""
Coverage boost tests targeting the lowest-coverage areas.

Covers:
- auth/dependencies.py (get_current_user, get_current_user_optional, etc.)
- auth/oidc_client.py (OIDCClient methods)
- auth/password.py (PasswordService edge cases)
- api/v1/ws.py (update_device_status, websocket_endpoint)
- database.py (DatabaseSessionManager)
- plugins/loader.py (Plugin class, loading, registry)
- services/download.py (DownloadService methods)
- config.py (AppSettings, ConnectionSettings, dataclass configs)
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.auth.jwt_handler import jwt_handler
from pyrate.auth.password import PasswordService, password_service
from pyrate.config import (
    AppSettings,
    ConnectionSettings,
    EmailConfig,
    InvitesConfig,
    LibraryConfig,
    MetadataConfig,
    OIDCConfig,
    PaymentConfig,
    TranscodingConfig,
)
from pyrate.database import DatabaseSessionManager
from pyrate.models.user import User


# ===================================================================
# auth/password.py
# ===================================================================


class TestPasswordService:
    """Tests for password.py edge cases."""

    def test_verify_wrong_password(self):
        hashed = password_service.get_password_hash("correct-password")
        assert password_service.verify_password("wrong-password", hashed) is False

    def test_verify_correct_password(self):
        hashed = password_service.get_password_hash("correct-password")
        assert password_service.verify_password("correct-password", hashed) is True

    def test_hash_produces_different_hashes(self):
        h1 = password_service.get_password_hash("same-password")
        h2 = password_service.get_password_hash("same-password")
        # Salt should differ
        assert h1 != h2

    def test_password_service_init_fallback(self):
        """Test the fallback branch in PasswordService.__init__."""
        with patch(
            "pyrate.auth.password.CryptContext",
            side_effect=[Exception("fail"), MagicMock()],
        ):
            svc = PasswordService()
            assert svc.pwd_context is not None


# ===================================================================
# auth/dependencies.py
# ===================================================================


class TestAuthDependencies:
    """Tests for auth dependency functions."""

    @pytest.mark.asyncio
    async def test_resolve_user_from_token_valid(self, test_user):
        from pyrate.auth.dependencies import _resolve_user_from_token

        mock_session = AsyncMock()
        mock_session.get.return_value = test_user

        token = jwt_handler.create_access_token({"sub": str(test_user.guid)})
        user, payload = await _resolve_user_from_token(token, "access", mock_session)
        assert user is not None
        assert user.guid == test_user.guid
        assert payload["type"] == "access"

    @pytest.mark.asyncio
    async def test_resolve_user_from_token_invalid_token(self):
        from pyrate.auth.dependencies import _resolve_user_from_token

        mock_session = AsyncMock()
        user, payload = await _resolve_user_from_token("bad-token", "access", mock_session)
        assert user is None
        assert payload is None

    @pytest.mark.asyncio
    async def test_resolve_user_from_token_wrong_type(self, test_user):
        from pyrate.auth.dependencies import _resolve_user_from_token

        mock_session = AsyncMock()
        token = jwt_handler.create_access_token({"sub": str(test_user.guid)})
        user, payload = await _resolve_user_from_token(token, "refresh", mock_session)
        assert user is None
        assert payload is None

    @pytest.mark.asyncio
    async def test_resolve_user_from_token_no_sub(self):
        from pyrate.auth.dependencies import _resolve_user_from_token

        mock_session = AsyncMock()
        token = jwt_handler.create_access_token({})  # no sub
        user, payload = await _resolve_user_from_token(token, "access", mock_session)
        assert user is None
        assert payload is None

    @pytest.mark.asyncio
    async def test_resolve_user_from_token_user_not_found(self):
        from pyrate.auth.dependencies import _resolve_user_from_token

        mock_session = AsyncMock()
        mock_session.get.return_value = None

        token = jwt_handler.create_access_token({"sub": str(uuid.uuid4())})
        user, payload = await _resolve_user_from_token(token, "access", mock_session)
        assert user is None
        assert payload is None

    @pytest.mark.asyncio
    async def test_resolve_user_from_token_inactive_user(self):
        from pyrate.auth.dependencies import _resolve_user_from_token

        inactive = MagicMock()
        inactive.is_active = False

        mock_session = AsyncMock()
        mock_session.get.return_value = inactive

        token = jwt_handler.create_access_token({"sub": str(uuid.uuid4())})
        user, payload = await _resolve_user_from_token(token, "access", mock_session)
        assert user is None

    @pytest.mark.asyncio
    async def test_get_current_user_optional_no_creds(self):
        from pyrate.auth.dependencies import get_current_user_optional

        mock_session = AsyncMock()
        user = await get_current_user_optional(
            request=None, credentials=None, session=mock_session
        )
        assert user is None

    @pytest.mark.asyncio
    async def test_get_current_user_optional_valid(self, test_user):
        from fastapi.security import HTTPAuthorizationCredentials

        from pyrate.auth.dependencies import get_current_user_optional

        mock_session = AsyncMock()
        mock_session.get.return_value = test_user

        token = jwt_handler.create_access_token({"sub": str(test_user.guid)})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with patch("pyrate.auth.dependencies._enforce_user_policy", new_callable=AsyncMock):
            user = await get_current_user_optional(
                request=None, credentials=creds, session=mock_session
            )
        assert user is not None
        assert user.guid == test_user.guid

    @pytest.mark.asyncio
    async def test_get_current_user_optional_invalid_token(self):
        from fastapi.security import HTTPAuthorizationCredentials

        from pyrate.auth.dependencies import get_current_user_optional

        mock_session = AsyncMock()
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage")
        user = await get_current_user_optional(
            request=None, credentials=creds, session=mock_session
        )
        assert user is None

    @pytest.mark.asyncio
    async def test_get_current_user_optional_exception(self):
        """Unexpected auth resolver errors propagate instead of downgrading to anonymous."""
        from fastapi.security import HTTPAuthorizationCredentials

        from pyrate.auth.dependencies import get_current_user_optional

        mock_session = AsyncMock()
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")
        with patch(
            "pyrate.auth.dependencies._resolve_user_from_token",
            side_effect=Exception("boom"),
        ):
            with pytest.raises(Exception, match="boom"):
                await get_current_user_optional(
                    request=None, credentials=creds, session=mock_session
                )

    @pytest.mark.asyncio
    async def test_get_current_user_no_credentials(self):
        from fastapi import HTTPException

        from pyrate.auth.dependencies import get_current_user

        mock_session = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=None, credentials=None, session=mock_session
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self):
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from pyrate.auth.dependencies import get_current_user

        mock_session = AsyncMock()
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=None, credentials=creds, session=mock_session
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_valid(self, test_user):
        from fastapi.security import HTTPAuthorizationCredentials

        from pyrate.auth.dependencies import get_current_user

        mock_session = AsyncMock()
        mock_session.get.return_value = test_user

        token = jwt_handler.create_access_token({"sub": str(test_user.guid)})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with patch("pyrate.auth.dependencies._enforce_user_policy", new_callable=AsyncMock):
            user = await get_current_user(
                request=None, credentials=creds, session=mock_session
            )
        assert user.guid == test_user.guid

    @pytest.mark.asyncio
    async def test_enforce_user_policy_blocks_inactive_schedule(self, test_user):
        from fastapi import HTTPException

        from pyrate.auth.dependencies import _enforce_user_policy

        permissions = MagicMock()
        permissions.access_schedule_active = False
        permissions.remote_access_enabled = True

        mock_session = AsyncMock()
        with patch(
            "pyrate.auth.dependencies.PermissionService"
        ) as permission_service:
            permission_service.return_value.resolve_user_permissions = AsyncMock(
                return_value=permissions
            )
            with pytest.raises(HTTPException) as exc_info:
                await _enforce_user_policy(test_user, mock_session, request=None)

        assert exc_info.value.status_code == 403
        assert "not allowed at this time" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_enforce_user_policy_blocks_remote_request(self, test_user):
        from fastapi import HTTPException

        from pyrate.auth.dependencies import _enforce_user_policy

        permissions = MagicMock()
        permissions.access_schedule_active = True
        permissions.remote_access_enabled = False
        request = MagicMock()
        request.client.host = "8.8.8.8"

        mock_session = AsyncMock()
        with patch(
            "pyrate.auth.dependencies.PermissionService"
        ) as permission_service:
            permission_service.return_value.resolve_user_permissions = AsyncMock(
                return_value=permissions
            )
            with pytest.raises(HTTPException) as exc_info:
                await _enforce_user_policy(test_user, mock_session, request=request)

        assert exc_info.value.status_code == 403
        assert "Remote access" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_enforce_user_policy_allows_local_request(self, test_user):
        from pyrate.auth.dependencies import _enforce_user_policy

        permissions = MagicMock()
        permissions.access_schedule_active = True
        permissions.remote_access_enabled = False
        request = MagicMock()
        request.client.host = "127.0.0.1"

        mock_session = AsyncMock()
        with patch(
            "pyrate.auth.dependencies.PermissionService"
        ) as permission_service:
            permission_service.return_value.resolve_user_permissions = AsyncMock(
                return_value=permissions
            )
            await _enforce_user_policy(test_user, mock_session, request=request)

    @pytest.mark.asyncio
    async def test_get_current_superuser_not_superuser(self, test_user):
        from fastapi import HTTPException

        from pyrate.auth.dependencies import get_current_superuser

        with pytest.raises(HTTPException) as exc_info:
            await get_current_superuser(current_user=test_user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_current_superuser_is_superuser(self, test_superuser):
        from pyrate.auth.dependencies import get_current_superuser

        result = await get_current_superuser(current_user=test_superuser)
        assert result.is_superuser is True

    def test_require_oidc_enabled_not_configured(self):
        from fastapi import HTTPException

        from pyrate.auth.dependencies import require_oidc_enabled

        with patch("pyrate.auth.dependencies.oidc_client") as mock_oidc:
            mock_oidc.is_enabled.return_value = False
            with pytest.raises(HTTPException) as exc_info:
                require_oidc_enabled()
            assert exc_info.value.status_code == 501

    def test_require_oidc_enabled_configured(self):
        from pyrate.auth.dependencies import require_oidc_enabled

        with patch("pyrate.auth.dependencies.oidc_client") as mock_oidc:
            mock_oidc.is_enabled.return_value = True
            # Should not raise
            require_oidc_enabled()

    @pytest.mark.asyncio
    async def test_verify_refresh_token_no_creds(self):
        from fastapi import HTTPException

        from pyrate.auth.dependencies import verify_refresh_token

        mock_session = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await verify_refresh_token(
                request=None, credentials=None, session=mock_session
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_refresh_token_invalid(self):
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from pyrate.auth.dependencies import verify_refresh_token

        mock_session = AsyncMock()
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad")
        with pytest.raises(HTTPException) as exc_info:
            await verify_refresh_token(
                request=None, credentials=creds, session=mock_session
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_refresh_token_valid(self, test_user):
        from fastapi.security import HTTPAuthorizationCredentials

        from pyrate.auth.dependencies import verify_refresh_token

        mock_session = AsyncMock()
        mock_session.get.return_value = test_user

        token = jwt_handler.create_refresh_token({"sub": str(test_user.guid)})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with patch("pyrate.auth.dependencies._enforce_user_policy", new_callable=AsyncMock):
            user, jti = await verify_refresh_token(
                request=None, credentials=creds, session=mock_session
            )
        assert user.guid == test_user.guid
        assert jti is not None

    @pytest.mark.asyncio
    async def test_verify_refresh_token_access_token_rejected(self, test_user):
        """An access token should be rejected when a refresh token is expected."""
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from pyrate.auth.dependencies import verify_refresh_token

        mock_session = AsyncMock()
        token = jwt_handler.create_access_token({"sub": str(test_user.guid)})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(HTTPException) as exc_info:
            await verify_refresh_token(
                request=None, credentials=creds, session=mock_session
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_refresh_token_no_jti(self, test_user):
        """A refresh token without jti should be rejected."""
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from pyrate.auth.dependencies import verify_refresh_token

        mock_session = AsyncMock()
        mock_session.get.return_value = test_user

        # Manually craft a refresh token with no jti
        from jose import jwt as jose_jwt

        payload = {
            "sub": str(test_user.guid),
            "type": "refresh",
            "exp": datetime.now(UTC) + timedelta(days=1),
            "iat": datetime.now(UTC),
            # no jti
        }
        token = jose_jwt.encode(payload, jwt_handler.secret_key, algorithm="HS256")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with (
            patch("pyrate.auth.dependencies._enforce_user_policy", new_callable=AsyncMock),
            pytest.raises(HTTPException) as exc_info,
        ):
            await verify_refresh_token(
                request=None, credentials=creds, session=mock_session
            )
        assert exc_info.value.status_code == 401
        assert "Invalid token payload" in exc_info.value.detail


# ===================================================================
# auth/oidc_client.py
# ===================================================================


class TestOIDCClient:
    """Tests for OIDCClient methods."""

    def _make_client(self, **overrides):
        """Create an OIDCClient with mocked config."""
        from pyrate.auth.oidc_client import OIDCClient

        defaults = dict(
            enabled=True,
            client_id="test-client-id",
            client_secret="test-client-secret",
            server_metadata_url="https://idp.example.com/.well-known/openid-configuration",
            issuer="https://idp.example.com",
            authorization_endpoint="https://idp.example.com/auth",
            token_endpoint="https://idp.example.com/token",
            userinfo_endpoint="https://idp.example.com/userinfo",
            jwks_uri="https://idp.example.com/certs",
            end_session_endpoint="https://idp.example.com/logout",
            redirect_uri="http://localhost:8000/auth/callback",
            post_logout_redirect_uri="http://localhost:8000",
        )
        defaults.update(overrides)
        config = OIDCConfig(**defaults)
        client = OIDCClient.__new__(OIDCClient)
        client.config = config
        client.client_id = config.client_id
        client.client_secret = config.client_secret
        client.redirect_uri = config.redirect_uri
        client.scopes = " ".join(config.scopes)
        client._metadata = None
        return client

    def test_is_enabled_true(self):
        client = self._make_client()
        assert client.is_enabled()  # truthy (returns last and-ed value)

    def test_is_enabled_false_no_client_id(self):
        client = self._make_client(client_id=None)
        assert not client.is_enabled()

    def test_is_enabled_false_disabled(self):
        client = self._make_client(enabled=False)
        assert not client.is_enabled()

    def test_is_enabled_false_no_secret(self):
        client = self._make_client(client_secret=None)
        assert not client.is_enabled()

    def test_is_enabled_no_metadata_url_but_has_issuer(self):
        client = self._make_client(server_metadata_url=None, issuer="https://idp.example.com")
        assert client.is_enabled()

    def test_is_enabled_no_metadata_url_no_issuer(self):
        client = self._make_client(server_metadata_url=None, issuer=None)
        assert not client.is_enabled()

    @pytest.mark.asyncio
    async def test_get_provider_metadata_cached(self):
        client = self._make_client()
        client._metadata = {"issuer": "cached"}
        result = await client.get_provider_metadata()
        assert result["issuer"] == "cached"

    @pytest.mark.asyncio
    async def test_get_provider_metadata_manual_fallback(self):
        client = self._make_client(server_metadata_url=None)
        result = await client.get_provider_metadata()
        assert result["issuer"] == "https://idp.example.com"
        assert result["authorization_endpoint"] == "https://idp.example.com/auth"

    @pytest.mark.asyncio
    async def test_get_provider_metadata_from_url(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/certs",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("pyrate.auth.oidc_client.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_response
            mock_httpx.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await client.get_provider_metadata()

        assert result["issuer"] == "https://idp.example.com"

    @pytest.mark.asyncio
    async def test_get_authorization_url(self):
        client = self._make_client()
        client._metadata = {
            "authorization_endpoint": "https://idp.example.com/auth",
        }
        url = await client.get_authorization_url(state="test-state")
        assert "https://idp.example.com/auth?" in url
        assert "client_id=test-client-id" in url
        assert "state=test-state" in url
        assert "response_type=code" in url

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens(self):
        client = self._make_client()
        client._metadata = {
            "token_endpoint": "https://idp.example.com/token",
        }
        mock_token_response = {"access_token": "at", "id_token": "idt"}

        with patch("pyrate.auth.oidc_client.AsyncOAuth2Client") as MockOAuth:
            mock_oauth_instance = AsyncMock()
            mock_oauth_instance.fetch_token.return_value = mock_token_response
            MockOAuth.return_value = mock_oauth_instance

            result = await client.exchange_code_for_tokens("auth-code", "state")

        assert result["access_token"] == "at"

    @pytest.mark.asyncio
    async def test_get_userinfo(self):
        client = self._make_client()
        client._metadata = {
            "userinfo_endpoint": "https://idp.example.com/userinfo",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = {"sub": "user-123", "email": "u@e.com"}
        mock_response.raise_for_status = MagicMock()

        with patch("pyrate.auth.oidc_client.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_response
            mock_httpx.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await client.get_userinfo("access-token")

        assert result["sub"] == "user-123"

    @pytest.mark.asyncio
    async def test_verify_id_token_fetches_jwks(self):
        """Test that verify_id_token fetches JWKS from the provider."""
        client = self._make_client()
        client._metadata = {
            "jwks_uri": "https://idp.example.com/certs",
            "issuer": "https://idp.example.com",
        }
        mock_jwks_response = MagicMock()
        mock_jwks_response.json.return_value = {"keys": []}
        mock_jwks_response.raise_for_status = MagicMock()

        with patch("pyrate.auth.oidc_client.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_jwks_response
            mock_httpx.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

            # CodeIDToken.parse will fail with empty keys, that's expected
            with pytest.raises(Exception):
                await client.verify_id_token("some-id-token")

            # But JWKS endpoint should have been called
            mock_client_instance.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_logout_url_with_hint(self):
        client = self._make_client()
        client._metadata = {
            "end_session_endpoint": "https://idp.example.com/logout",
        }
        url = await client.get_logout_url(id_token_hint="token-hint")
        assert "https://idp.example.com/logout?" in url
        assert "id_token_hint=token-hint" in url

    @pytest.mark.asyncio
    async def test_get_logout_url_without_endpoint(self):
        client = self._make_client()
        # Must have at least one key so _metadata is truthy and cached
        client._metadata = {"issuer": "https://idp.example.com"}
        url = await client.get_logout_url()
        assert url == "http://localhost:8000"

    @pytest.mark.asyncio
    async def test_get_logout_url_without_hint(self):
        client = self._make_client()
        client._metadata = {
            "end_session_endpoint": "https://idp.example.com/logout",
        }
        url = await client.get_logout_url()
        assert "id_token_hint" not in url

    def test_map_claims_to_user_data(self):
        client = self._make_client()
        claims = {
            "sub": "oidc-sub-123",
            "email": "user@example.com",
            "given_name": "John",
            "family_name": "Doe",
            "preferred_username": "johnd",
            "groups": ["admin", "users"],
        }
        result = client.map_claims_to_user_data(claims)
        assert result["oidc_sub"] == "oidc-sub-123"
        assert result["email"] == "user@example.com"
        assert result["first_name"] == "John"
        assert result["last_name"] == "Doe"
        # groups should be JSON encoded
        assert result["groups"] == json.dumps(["admin", "users"])

    def test_map_claims_missing_claims(self):
        client = self._make_client()
        claims = {"sub": "oidc-sub-123"}
        result = client.map_claims_to_user_data(claims)
        assert result == {"oidc_sub": "oidc-sub-123"}

    def test_map_claims_groups_as_dict(self):
        client = self._make_client()
        claims = {"groups": {"role": "admin"}}
        result = client.map_claims_to_user_data(claims)
        assert result["groups"] == json.dumps({"role": "admin"})

    def test_map_claims_groups_as_string(self):
        client = self._make_client()
        claims = {"groups": "admin"}
        result = client.map_claims_to_user_data(claims)
        # string groups should NOT be json encoded (not list or dict)
        assert result["groups"] == "admin"


# ===================================================================
# database.py
# ===================================================================
