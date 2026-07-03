"""FastAPI dependencies for authentication."""

import logging
import hashlib
import hmac
import ipaddress
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session
from ..models.api_key import ApiKey
from ..models.user import User
from ..services.permission import PermissionService
from .jwt_handler import jwt_handler
from .oidc_client import oidc_client

logger = logging.getLogger(__name__)

# HTTP Bearer Token Schema
security = HTTPBearer(auto_error=False)


async def _resolve_user_from_token(
    token: str,
    expected_type: str,
    session: AsyncSession,
) -> tuple[User | None, dict | None]:
    """Verify a JWT token and load the associated user.

    Returns (user, payload) on success, (None, None) on failure.
    Raises HTTPException for specific error conditions.
    """
    payload = jwt_handler.verify_token(token)
    if not payload:
        return None, None

    if payload.get("type") != expected_type:
        return None, None

    user_id = payload.get("sub")
    if not user_id:
        return None, None

    user = await session.get(User, user_id)
    if not user or not user.is_active:
        return None, None

    return user, payload


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def _resolve_user_from_api_key(
    raw_key: str,
    session: AsyncSession,
) -> User | None:
    """Load the active user for an unrevoked API key."""
    if not raw_key.startswith("pmak_"):
        return None

    key_hash = _hash_api_key(raw_key)
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    )
    api_key = result.scalars().first()
    if not api_key or not hmac.compare_digest(api_key.key_hash, key_hash):
        return None

    user = await session.get(User, api_key.user_guid)
    if not user or not user.is_active:
        return None

    api_key.last_used_at = datetime.now(UTC)
    await session.commit()
    return user


def _is_remote_request(request: Request | None) -> bool:
    """Best-effort remote/local classifier for user remote-access policy."""
    if request is None or request.client is None or not request.client.host:
        return False
    host = request.client.host
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host not in {"localhost"}
    return not (address.is_loopback or address.is_private or address.is_link_local)


async def _enforce_user_policy(
    user: User,
    session: AsyncSession,
    request: Request | None,
) -> None:
    """Enforce schedule and remote-access policy for authenticated users."""
    if user.is_superuser:
        return

    permissions = await PermissionService(session).resolve_user_permissions(user.guid)
    if not permissions.access_schedule_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access is not allowed at this time",
        )
    if _is_remote_request(request) and not permissions.remote_access_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Remote access is not allowed for this user",
        )


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_db_session),
) -> User | None:
    """Optional authentication — returns None if no valid token is present.

    DB or transport errors propagate so a backend outage surfaces as 5xx
    instead of silently downgrading the caller to "anonymous". Only token /
    payload problems (which ``_resolve_user_from_token`` already returns as
    ``None``) are treated as "no user".
    """
    if not credentials:
        return None

    try:
        user, _ = await _resolve_user_from_token(
            credentials.credentials, "access", session
        )
        if user:
            await _enforce_user_policy(user, session, request)
            return user
        user = await _resolve_user_from_api_key(credentials.credentials, session)
        if user:
            await _enforce_user_policy(user, session, request)
        return user
    except SQLAlchemyError:
        # DB outage — make it loud.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Required authentication — raises 401 if no valid token is present."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user, _ = await _resolve_user_from_token(credentials.credentials, "access", session)
    if not user:
        user = await _resolve_user_from_api_key(credentials.credentials, session)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await _enforce_user_policy(user, session, request)
    return user


async def get_current_superuser(current_user: User = Depends(get_current_user)) -> User:
    """Superuser authentication — only for administrators."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    return current_user


def require_oidc_enabled():
    """Dependency that checks if OIDC is enabled."""
    if not oidc_client.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="OIDC authentication is not configured",
        )


async def verify_refresh_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_db_session),
) -> tuple[User, str]:
    """Verify a refresh token and return (User, JTI)."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user, payload = await _resolve_user_from_token(
        credentials.credentials, "refresh", session
    )

    if not user or not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await _enforce_user_policy(user, session, request)

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user, jti
