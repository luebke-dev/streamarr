"""Redis-backed rate limiter for abuse-sensitive endpoints.

Uses a fixed-window counter per (key, window_seconds). Keys survive a worker
restart and are shared across backend replicas because they live in Redis.
"""

from __future__ import annotations

import logging
import asyncio
from typing import Callable

import redis.asyncio as aioredis
from redis.exceptions import RedisError
from fastapi import HTTPException, Request, status

from pyrate.config import settings

logger = logging.getLogger(__name__)

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
                logger.debug("Failed to close stale rate-limit Redis client", exc_info=True)
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        _redis_loop = current_loop
    return _redis


def _default_key(request: Request) -> str:
    """Per-client identifier. Prefers X-Forwarded-For's left-most value so the
    limiter works behind nginx; falls back to the TCP peer.

    **Deployment invariant**: this is only safe when the reverse proxy is
    trusted and the backend is never reachable directly (e.g. nginx is the
    only inbound path). If a client can hit the backend port directly, they
    can spoof ``X-Forwarded-For`` to bypass the limit. The current
    docker-compose setup enforces this: backend-python is not port-mapped.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def rate_limit(
    *,
    max_calls: int,
    window_seconds: int,
    scope: str,
    key_fn: Callable[[Request], str] | None = None,
):
    """Return a FastAPI dependency that enforces a per-client rate limit.

    Args:
        max_calls: allowed calls within ``window_seconds``.
        window_seconds: fixed-window length in seconds.
        scope: logical name used as a Redis-key prefix so different endpoints
            don't share counters.
        key_fn: resolves the per-client key (defaults to IP-based).
    """

    resolver = key_fn or _default_key

    async def dependency(request: Request) -> None:
        redis = await _get_redis()
        client_key = resolver(request)
        redis_key = f"pyrate:ratelimit:{scope}:{client_key}"

        try:
            count = await redis.incr(redis_key)
            if count == 1:
                await redis.expire(redis_key, window_seconds)
        except RedisError as e:
            logger.warning("Rate limiter unavailable for scope %s: %s", scope, e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiter unavailable",
            ) from e

        if count > max_calls:
            retry_after = await redis.ttl(redis_key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for {scope}",
                headers={"Retry-After": str(max(retry_after, 1))},
            )

    return dependency
