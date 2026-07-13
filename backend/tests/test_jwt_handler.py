"""Tests for JWT token handler."""

import time
from datetime import timedelta

import pytest

from streamarr.auth.jwt_handler import JWTHandler


@pytest.fixture
def jwt() -> JWTHandler:
    """Create a JWTHandler instance."""
    handler = JWTHandler()
    # Use a deterministic secret for testing
    handler.secret_key = "test-secret-key-for-unit-tests"
    return handler


class TestAccessToken:
    """Tests for access token creation and verification."""

    def test_create_access_token(self, jwt: JWTHandler):
        """Test creating an access token."""
        token = jwt.create_access_token({"sub": "user-123"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_access_token_contains_subject(self, jwt: JWTHandler):
        """Test that access token contains the subject claim."""
        token = jwt.create_access_token({"sub": "user-123"})
        payload = jwt.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"

    def test_access_token_type(self, jwt: JWTHandler):
        """Test that access token has type 'access'."""
        token = jwt.create_access_token({"sub": "user-123"})
        payload = jwt.verify_token(token)
        assert payload["type"] == "access"

    def test_access_token_has_expiry(self, jwt: JWTHandler):
        """Test that access token has an expiry claim."""
        token = jwt.create_access_token({"sub": "user-123"})
        payload = jwt.verify_token(token)
        assert "exp" in payload

    def test_access_token_has_issued_at(self, jwt: JWTHandler):
        """Test that access token has an issued-at claim."""
        token = jwt.create_access_token({"sub": "user-123"})
        payload = jwt.verify_token(token)
        assert "iat" in payload

    def test_access_token_custom_expiry(self, jwt: JWTHandler):
        """Test creating an access token with custom expiry."""
        token = jwt.create_access_token(
            {"sub": "user-123"}, expires_delta=timedelta(hours=1)
        )
        payload = jwt.verify_token(token)
        # Check expiry is roughly 1 hour from now
        diff = payload["exp"] - payload["iat"]
        assert 3500 < diff < 3700

    def test_access_token_preserves_extra_data(self, jwt: JWTHandler):
        """Test that extra data in the payload is preserved."""
        token = jwt.create_access_token(
            {"sub": "user-123", "role": "admin", "email": "admin@test.com"}
        )
        payload = jwt.verify_token(token)
        assert payload["role"] == "admin"
        assert payload["email"] == "admin@test.com"


class TestRefreshToken:
    """Tests for refresh token creation and verification."""

    def test_create_refresh_token(self, jwt: JWTHandler):
        """Test creating a refresh token."""
        token = jwt.create_refresh_token({"sub": "user-123"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_refresh_token_type(self, jwt: JWTHandler):
        """Test that refresh token has type 'refresh'."""
        token = jwt.create_refresh_token({"sub": "user-123"})
        payload = jwt.verify_token(token)
        assert payload["type"] == "refresh"

    def test_refresh_token_has_jti(self, jwt: JWTHandler):
        """Test that refresh token has a JWT ID for invalidation."""
        token = jwt.create_refresh_token({"sub": "user-123"})
        payload = jwt.verify_token(token)
        assert "jti" in payload
        assert len(payload["jti"]) > 0

    def test_refresh_token_unique_jti(self, jwt: JWTHandler):
        """Test that each refresh token has a unique JWT ID."""
        token1 = jwt.create_refresh_token({"sub": "user-123"})
        token2 = jwt.create_refresh_token({"sub": "user-123"})
        payload1 = jwt.verify_token(token1)
        payload2 = jwt.verify_token(token2)
        assert payload1["jti"] != payload2["jti"]

    def test_refresh_token_longer_expiry(self, jwt: JWTHandler):
        """Test that refresh token has longer expiry than access token."""
        access = jwt.create_access_token({"sub": "user-123"})
        refresh = jwt.create_refresh_token({"sub": "user-123"})
        access_payload = jwt.verify_token(access)
        refresh_payload = jwt.verify_token(refresh)

        access_ttl = access_payload["exp"] - access_payload["iat"]
        refresh_ttl = refresh_payload["exp"] - refresh_payload["iat"]
        assert refresh_ttl > access_ttl


class TestInviteToken:
    """Tests for invite token creation and verification."""

    def test_create_invite_token(self, jwt: JWTHandler):
        """Test creating an invite token."""
        token = jwt.create_invite_token(
            {"created_by_user_id": "admin-id"}, expires_delta=timedelta(days=7)
        )
        assert isinstance(token, str)

    def test_invite_token_type(self, jwt: JWTHandler):
        """Test that invite token has type 'invite'."""
        token = jwt.create_invite_token(
            {"created_by_user_id": "admin-id"}, expires_delta=timedelta(days=7)
        )
        payload = jwt.verify_token(token)
        assert payload["type"] == "invite"

    def test_invite_token_has_jti(self, jwt: JWTHandler):
        """Test that invite token has a JWT ID."""
        token = jwt.create_invite_token(
            {"created_by_user_id": "admin-id"}, expires_delta=timedelta(days=7)
        )
        payload = jwt.verify_token(token)
        assert "jti" in payload

    def test_verify_invite_token(self, jwt: JWTHandler):
        """Test verify_invite_token returns payload for valid invite."""
        token = jwt.create_invite_token(
            {"created_by_user_id": "admin-id"}, expires_delta=timedelta(days=7)
        )
        payload = jwt.verify_invite_token(token)
        assert payload is not None
        assert payload["created_by_user_id"] == "admin-id"

    def test_verify_invite_token_rejects_access(self, jwt: JWTHandler):
        """Test that verify_invite_token rejects non-invite tokens."""
        access = jwt.create_access_token({"sub": "user-123"})
        result = jwt.verify_invite_token(access)
        assert result is None

    def test_extract_invite_data(self, jwt: JWTHandler):
        """Test extracting invite data from a token."""
        token = jwt.create_invite_token(
            {"created_by_user_id": "admin-id"}, expires_delta=timedelta(days=7)
        )
        data = jwt.extract_invite_data(token)
        assert data is not None
        assert data["created_by_user_id"] == "admin-id"
        assert "jti" in data
        assert "exp" in data
        assert "iat" in data

    def test_extract_invite_data_rejects_access(self, jwt: JWTHandler):
        """Test that extract_invite_data rejects non-invite tokens."""
        access = jwt.create_access_token({"sub": "user-123"})
        data = jwt.extract_invite_data(access)
        assert data is None


class TestEmailVerifyToken:
    """Tests for email verification token creation and verification."""

    def test_create_email_verify_token(self, jwt: JWTHandler):
        """Test creating an email verification token."""
        token = jwt.create_email_verify_token(user_id="user-123", email="test@example.com")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_email_verify_token_type(self, jwt: JWTHandler):
        """Test that email verify token has type 'email_verify'."""
        token = jwt.create_email_verify_token(user_id="user-123", email="test@example.com")
        payload = jwt.verify_token(token)
        assert payload["type"] == "email_verify"

    def test_email_verify_token_contains_email(self, jwt: JWTHandler):
        """Test that email verify token contains the email claim."""
        token = jwt.create_email_verify_token(user_id="user-123", email="test@example.com")
        payload = jwt.verify_token(token)
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"

    def test_email_verify_token_has_jti(self, jwt: JWTHandler):
        """Test that email verify token has a JWT ID."""
        token = jwt.create_email_verify_token(user_id="user-123", email="test@example.com")
        payload = jwt.verify_token(token)
        assert "jti" in payload

    def test_verify_email_verify_token(self, jwt: JWTHandler):
        """Test verify_email_verify_token returns payload for valid token."""
        token = jwt.create_email_verify_token(user_id="user-123", email="test@example.com")
        payload = jwt.verify_email_verify_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"

    def test_verify_email_verify_token_rejects_access(self, jwt: JWTHandler):
        """Test that verify_email_verify_token rejects non-email_verify tokens."""
        access = jwt.create_access_token({"sub": "user-123"})
        result = jwt.verify_email_verify_token(access)
        assert result is None

    def test_verify_email_verify_token_rejects_password_reset(self, jwt: JWTHandler):
        """Test that verify_email_verify_token rejects password_reset tokens."""
        token = jwt.create_password_reset_token(user_id="user-123", email="test@example.com")
        result = jwt.verify_email_verify_token(token)
        assert result is None


class TestPasswordResetToken:
    """Tests for password reset token creation and verification."""

    def test_create_password_reset_token(self, jwt: JWTHandler):
        """Test creating a password reset token."""
        token = jwt.create_password_reset_token(user_id="user-123", email="test@example.com")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_password_reset_token_type(self, jwt: JWTHandler):
        """Test that password reset token has type 'password_reset'."""
        token = jwt.create_password_reset_token(user_id="user-123", email="test@example.com")
        payload = jwt.verify_token(token)
        assert payload["type"] == "password_reset"

    def test_password_reset_token_contains_claims(self, jwt: JWTHandler):
        """Test that password reset token contains sub and email claims."""
        token = jwt.create_password_reset_token(user_id="user-123", email="test@example.com")
        payload = jwt.verify_token(token)
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"

    def test_password_reset_token_has_jti(self, jwt: JWTHandler):
        """Test that password reset token has a JWT ID."""
        token = jwt.create_password_reset_token(user_id="user-123", email="test@example.com")
        payload = jwt.verify_token(token)
        assert "jti" in payload

    def test_password_reset_token_unique_jti(self, jwt: JWTHandler):
        """Test that each password reset token has a unique JWT ID."""
        token1 = jwt.create_password_reset_token(user_id="user-123", email="test@example.com")
        token2 = jwt.create_password_reset_token(user_id="user-123", email="test@example.com")
        payload1 = jwt.verify_token(token1)
        payload2 = jwt.verify_token(token2)
        assert payload1["jti"] != payload2["jti"]

    def test_password_reset_token_expiry(self, jwt: JWTHandler):
        """Test that password reset token has roughly 1 hour expiry."""
        token = jwt.create_password_reset_token(user_id="user-123", email="test@example.com")
        payload = jwt.verify_token(token)
        diff = payload["exp"] - payload["iat"]
        assert 3500 < diff < 3700  # ~1 hour

    def test_verify_password_reset_token(self, jwt: JWTHandler):
        """Test verify_password_reset_token returns payload for valid token."""
        token = jwt.create_password_reset_token(user_id="user-123", email="test@example.com")
        payload = jwt.verify_password_reset_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"

    def test_verify_password_reset_token_rejects_access(self, jwt: JWTHandler):
        """Test that verify_password_reset_token rejects non-password_reset tokens."""
        access = jwt.create_access_token({"sub": "user-123"})
        result = jwt.verify_password_reset_token(access)
        assert result is None

    def test_verify_password_reset_token_rejects_email_verify(self, jwt: JWTHandler):
        """Test that verify_password_reset_token rejects email_verify tokens."""
        token = jwt.create_email_verify_token(user_id="user-123", email="test@example.com")
        result = jwt.verify_password_reset_token(token)
        assert result is None

    def test_verify_password_reset_token_rejects_refresh(self, jwt: JWTHandler):
        """Test that verify_password_reset_token rejects refresh tokens."""
        token = jwt.create_refresh_token({"sub": "user-123"})
        result = jwt.verify_password_reset_token(token)
        assert result is None


class TestTokenVerification:
    """Tests for token verification."""

    def test_verify_valid_token(self, jwt: JWTHandler):
        """Test verifying a valid token."""
        token = jwt.create_access_token({"sub": "user-123"})
        payload = jwt.verify_token(token)
        assert payload is not None

    def test_verify_invalid_token(self, jwt: JWTHandler):
        """Test verifying an invalid token returns None."""
        result = jwt.verify_token("invalid.token.string")
        assert result is None

    def test_verify_empty_token(self, jwt: JWTHandler):
        """Test verifying an empty token returns None."""
        result = jwt.verify_token("")
        assert result is None

    def test_verify_tampered_token(self, jwt: JWTHandler):
        """Test that a tampered token is rejected."""
        token = jwt.create_access_token({"sub": "user-123"})
        # Tamper with the token
        tampered = token[:-5] + "XXXXX"
        result = jwt.verify_token(tampered)
        assert result is None

    def test_verify_wrong_secret(self, jwt: JWTHandler):
        """Test that a token signed with a different secret is rejected."""
        token = jwt.create_access_token({"sub": "user-123"})
        jwt.secret_key = "different-secret-key"
        result = jwt.verify_token(token)
        assert result is None

    def test_expired_token(self, jwt: JWTHandler):
        """Test that an expired token is rejected."""
        token = jwt.create_access_token(
            {"sub": "user-123"}, expires_delta=timedelta(seconds=-1)
        )
        result = jwt.verify_token(token)
        assert result is None


class TestExtractUserId:
    """Tests for user ID extraction."""

    def test_extract_user_id(self, jwt: JWTHandler):
        """Test extracting user ID from a token."""
        token = jwt.create_access_token({"sub": "user-123"})
        user_id = jwt.extract_user_id(token)
        assert user_id == "user-123"

    def test_extract_user_id_invalid_token(self, jwt: JWTHandler):
        """Test extracting user ID from an invalid token returns None."""
        result = jwt.extract_user_id("invalid-token")
        assert result is None

    def test_extract_user_id_no_sub(self, jwt: JWTHandler):
        """Test extracting user ID when 'sub' claim is missing."""
        token = jwt.create_access_token({"role": "admin"})
        user_id = jwt.extract_user_id(token)
        assert user_id is None


class TestTokenExpiry:
    """Tests for token expiry checking."""

    def test_is_token_expired_valid(self, jwt: JWTHandler):
        """Test that a valid token is not expired."""
        token = jwt.create_access_token({"sub": "user-123"})
        assert jwt.is_token_expired(token) is False

    def test_is_token_expired_invalid(self, jwt: JWTHandler):
        """Test that an invalid token reports as expired."""
        assert jwt.is_token_expired("invalid-token") is True

    def test_is_token_expired_past(self, jwt: JWTHandler):
        """Test that an expired token reports as expired."""
        token = jwt.create_access_token(
            {"sub": "user-123"}, expires_delta=timedelta(seconds=-1)
        )
        # Expired tokens can't be decoded at all by jose, so is_token_expired returns True
        assert jwt.is_token_expired(token) is True


class TestPasswordHashing:
    """Tests for password hashing and verification."""

    def test_hash_password(self, jwt: JWTHandler):
        """Test creating a password hash."""
        hashed = jwt.get_password_hash("mypassword123")
        assert hashed != "mypassword123"
        assert len(hashed) > 0

    def test_verify_correct_password(self, jwt: JWTHandler):
        """Test verifying a correct password."""
        hashed = jwt.get_password_hash("mypassword123")
        assert jwt.verify_password("mypassword123", hashed) is True

    def test_verify_wrong_password(self, jwt: JWTHandler):
        """Test verifying a wrong password."""
        hashed = jwt.get_password_hash("mypassword123")
        assert jwt.verify_password("wrongpassword", hashed) is False

    def test_different_passwords_different_hashes(self, jwt: JWTHandler):
        """Test that different passwords produce different hashes."""
        hash1 = jwt.get_password_hash("password1")
        hash2 = jwt.get_password_hash("password2")
        assert hash1 != hash2

    def test_same_password_different_hashes(self, jwt: JWTHandler):
        """Test that same password produces different hashes (salt)."""
        hash1 = jwt.get_password_hash("mypassword")
        hash2 = jwt.get_password_hash("mypassword")
        assert hash1 != hash2  # Different salts
        # But both verify correctly
        assert jwt.verify_password("mypassword", hash1) is True
        assert jwt.verify_password("mypassword", hash2) is True

    def test_long_password_prehash(self, jwt: JWTHandler):
        """Test that very long passwords are handled via SHA-256 pre-hash."""
        long_password = "a" * 100  # > 72 bytes
        hashed = jwt.get_password_hash(long_password)
        assert jwt.verify_password(long_password, hashed) is True

    def test_unicode_password(self, jwt: JWTHandler):
        """Test hashing and verifying unicode passwords."""
        unicode_pw = "Pässwörd123!€"
        hashed = jwt.get_password_hash(unicode_pw)
        assert jwt.verify_password(unicode_pw, hashed) is True

    def test_empty_password(self, jwt: JWTHandler):
        """Test hashing and verifying an empty password."""
        hashed = jwt.get_password_hash("")
        assert jwt.verify_password("", hashed) is True
        assert jwt.verify_password("notempty", hashed) is False
