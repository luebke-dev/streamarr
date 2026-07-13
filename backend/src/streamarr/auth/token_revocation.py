"""Server-side refresh-token revocation and single-use rotation.

Refresh tokens are otherwise stateless 7-day bearer credentials with no way to
revoke a leaked one before its natural expiry. This module adds a small
Redis-backed control plane:

* **Rotation / reuse detection** — each refresh token may be redeemed at
  ``/auth/refresh`` exactly once. The redeemed ``jti`` is recorded; presenting
  it again is rejected as a replay.
* **Bulk revocation** — logout and password reset stamp a per-user
  ``revoke_before`` cutoff; any refresh token issued at/or before that instant
  can no longer be redeemed. This lets a user terminate outstanding refresh
  tokens they can't individually name.

Access tokens remain valid until their short (~30 min) expiry — instant access
revocation would require a per-request store lookup and is out of scope here.

Redis is already a hard dependency (rate limiting), so the read path fails
*closed*: if Redis is unavailable a refresh cannot be validated and is refused
rather than silently bypassing revocation. The write paths are best-effort.
"""

from __future__ import annotations

import asyncio
import logging
import time

import redis.asyncio as aioredis
from redis.exceptions import RedisError
from fastapi import HTTPException, status

from ..config import settings

logger = logging.getLogger(__name__)

# Refresh tokens live 7 days (jwt_handler.refresh_token_expire_days); revocation
# records only need to outlive the token they concern.
_REFRESH_TTL_SECONDS = 7 * 24 * 60 * 60

_ROTATED_PREFIX = "streamarr:auth:rt_rotated:"
_REVOKE_BEFORE_PREFIX = "streamarr:auth:revoke_before:"

_redis: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis, _redis_loop
    current_loop = asyncio.get_running_loop()
    if _redis is None or _redis_loop is not current_loop:
        if _redis is not None:
            try:
                await _redis.aclose()
            except Exception:
                logger.debug("Failed to close stale revocation Redis client", exc_info=True)
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        _redis_loop = current_loop
    return _redis


async def assert_refresh_usable(user_guid, jti: str | None, iat: int | None) -> None:
    """Reject a refresh token that has been rotated or bulk-revoked.

    Raises 401 when the token was already redeemed or predates the user's
    revocation cutoff, and 503 when the revocation store can't be consulted
    (fail-closed — we never silently skip the check).
    """
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    redis = await _get_redis()
    try:
        rotated = await redis.get(f"{_ROTATED_PREFIX}{jti}")
        revoke_before = await redis.get(f"{_REVOKE_BEFORE_PREFIX}{user_guid}")
    except RedisError as e:
        logger.warning("Refresh revocation store unavailable: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication store unavailable",
        ) from e

    if rotated:
        logger.warning("Refresh token reuse detected for user=%s jti=%s", user_guid, jti)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if revoke_before is not None and iat is not None:
        try:
            cutoff = float(revoke_before)
        except (TypeError, ValueError):
            cutoff = 0.0
        if float(iat) < cutoff:
            logger.info("Refresh token revoked by cutoff for user=%s", user_guid)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )


async def mark_refresh_rotated(jti: str | None) -> None:
    """Record a refresh ``jti`` as spent so a replay is rejected. Best-effort."""
    if not jti:
        return
    try:
        redis = await _get_redis()
        await redis.set(f"{_ROTATED_PREFIX}{jti}", "1", ex=_REFRESH_TTL_SECONDS)
    except RedisError as e:
        logger.warning("Failed to record rotated refresh jti: %s", e)


async def revoke_user_refresh_tokens(user_guid) -> None:
    """Revoke every refresh token issued to a user up to now. Best-effort.

    Used by logout and password reset. Tokens issued afterwards (e.g. the pair
    minted by a subsequent login) are unaffected.
    """
    try:
        redis = await _get_redis()
        await redis.set(
            f"{_REVOKE_BEFORE_PREFIX}{user_guid}",
            str(int(time.time())),
            ex=_REFRESH_TTL_SECONDS,
        )
    except RedisError as e:
        logger.warning("Failed to revoke refresh tokens for user=%s: %s", user_guid, e)
