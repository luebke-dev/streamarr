"""JWT Token Handler for authentication."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from ..config import settings
from .password import password_service

logger = logging.getLogger(__name__)


class JWTHandler:
    """Handler for JWT token creation and validation."""

    def __init__(self):
        self.secret_key = settings.secret_key
        self.algorithm = "HS256"
        self.access_token_expire_minutes = 30
        self.refresh_token_expire_days = 7

    def create_access_token(
        self, data: dict[str, Any], expires_delta: timedelta | None = None
    ) -> str:
        """Create an access token."""
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.now(UTC) + expires_delta
        else:
            expire = datetime.now(UTC) + timedelta(
                minutes=self.access_token_expire_minutes
            )

        to_encode.update({"exp": expire, "iat": datetime.now(UTC), "type": "access"})

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def create_refresh_token(self, data: dict[str, Any]) -> str:
        """Create a refresh token."""
        to_encode = data.copy()
        expire = datetime.now(UTC) + timedelta(days=self.refresh_token_expire_days)

        to_encode.update(
            {
                "exp": expire,
                "iat": datetime.now(UTC),
                "type": "refresh",
                "jti": str(uuid.uuid4()),
            }
        )

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def create_invite_token(
        self, data: dict[str, Any], expires_delta: timedelta
    ) -> str:
        """Create an invite token."""
        to_encode = data.copy()
        expire = datetime.now(UTC) + expires_delta

        to_encode.update(
            {
                "exp": expire,
                "iat": datetime.now(UTC),
                "type": "invite",
                "jti": str(uuid.uuid4()),
            }
        )

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def verify_token(self, token: str) -> dict[str, Any] | None:
        """Verify a JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except JWTError:
            return None

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash. Delegates to PasswordService."""
        return password_service.verify_password(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        """Create a password hash. Delegates to PasswordService."""
        return password_service.get_password_hash(password)

    def extract_user_id(self, token: str) -> str | None:
        """Extract user ID from a token."""
        payload = self.verify_token(token)
        if payload:
            return payload.get("sub")
        return None

    def create_email_verify_token(self, user_id: str, email: str) -> str:
        """Create a token for email address verification (24h expiry)."""
        to_encode = {
            "sub": user_id,
            "email": email,
            "type": "email_verify",
            "jti": str(uuid.uuid4()),
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iat": datetime.now(UTC),
        }
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def verify_email_verify_token(self, token: str) -> dict[str, Any] | None:
        """Verify an email verification token. Returns payload or None."""
        payload = self.verify_token(token)
        if payload and payload.get("type") == "email_verify":
            return payload
        return None

    def create_password_reset_token(self, user_id: str, email: str) -> str:
        """Create a token for password reset (1h expiry)."""
        to_encode = {
            "sub": user_id,
            "email": email,
            "type": "password_reset",
            "jti": str(uuid.uuid4()),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        }
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    def verify_password_reset_token(self, token: str) -> dict[str, Any] | None:
        """Verify a password reset token. Returns payload or None."""
        payload = self.verify_token(token)
        if payload and payload.get("type") == "password_reset":
            return payload
        return None

    def verify_invite_token(self, token: str) -> dict[str, Any] | None:
        """Verify an invite token."""
        payload = self.verify_token(token)
        if payload and payload.get("type") == "invite":
            return payload
        return None

    def extract_invite_data(self, token: str) -> dict[str, Any] | None:
        """Extract invite data from a token."""
        payload = self.verify_invite_token(token)
        if payload:
            return {
                "created_by_user_id": payload.get("created_by_user_id"),
                "jti": payload.get("jti"),
                "exp": payload.get("exp"),
                "iat": payload.get("iat"),
            }
        return None

    def is_token_expired(self, token: str) -> bool:
        """Check if a token is expired."""
        payload = self.verify_token(token)
        if not payload:
            return True

        exp = payload.get("exp")
        if not exp:
            return True

        return datetime.now(UTC).timestamp() > exp


# Global instance
jwt_handler = JWTHandler()
