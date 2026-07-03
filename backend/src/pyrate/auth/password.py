"""Password hashing and verification service.

Separated from JWT handling to follow the Single Responsibility Principle.
"""

import logging
import re

from passlib.context import CryptContext

logger = logging.getLogger(__name__)


_COMPLEXITY_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)")


def validate_password_strength(password: str) -> None:
    """Raise ``ValueError("weak_password")`` if ``password`` doesn't meet the
    configured length/complexity policy.

    Callers at the service layer should invoke this even when the API layer
    already validated, so direct-to-service callers (install flow, admin
    tooling) can't sneak a weak password in.
    """
    from ..config import settings as _settings

    if not password:
        logger.info("Password policy rejection: empty")
        raise ValueError("weak_password")
    if len(password) < _settings.oidc.min_password_length:
        logger.info(
            "Password policy rejection: length %d < min %d",
            len(password), _settings.oidc.min_password_length,
        )
        raise ValueError("weak_password")
    if _settings.oidc.require_password_complexity and not _COMPLEXITY_RE.match(password):
        logger.info("Password policy rejection: missing required complexity")
        raise ValueError("weak_password")


class PasswordService:
    """Handles password hashing and verification."""

    # Pinned explicitly so the work factor stays predictable across passlib
    # upgrades; OWASP recommends ≥600k for PBKDF2-SHA256 as of 2023.
    _PBKDF2_ROUNDS = 600_000

    def __init__(self):
        try:
            self.pwd_context = CryptContext(
                schemes=["pbkdf2_sha256"],
                deprecated="auto",
                pbkdf2_sha256__rounds=self._PBKDF2_ROUNDS,
            )
        except Exception as e:
            logger.warning(
                "Password context initialization failed: %s, using basic pbkdf2_sha256",
                e,
            )
            self.pwd_context = CryptContext(
                schemes=["pbkdf2_sha256"],
                pbkdf2_sha256__rounds=self._PBKDF2_ROUNDS,
            )

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        return self.pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        """Create a password hash."""
        return self.pwd_context.hash(password)


# Global instance
password_service = PasswordService()
