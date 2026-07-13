"""Redis-based rate limiter for permission enforcement."""

import asyncio
import logging
import time
import uuid

import redis.asyncio as redis

logger = logging.getLogger(__name__)

from streamarr.config import settings

# Singleton Redis connection for rate limiting
_redis_client: redis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


async def get_redis() -> redis.Redis:
    global _redis_client, _redis_loop
    current_loop = asyncio.get_running_loop()
    if _redis_client is not None and _redis_loop is not current_loop:
        redis_client = _redis_client
        redis_loop = _redis_loop
        _redis_client = None
        _redis_loop = None
        if redis_loop is None or not redis_loop.is_closed():
            try:
                await redis_client.aclose()
            except RuntimeError as exc:
                logger.debug("Redis rate-limiter close skipped: %s", exc)
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        _redis_loop = current_loop
    return _redis_client


# Public name for the shared loop-aware Redis client. Several modules had been
# importing the historically-private ``_get_redis``; keep it as an alias so the
# cross-module contract is now an intentional public API, not a reached-into
# underscore. Prefer ``get_redis`` in new code.
_get_redis = get_redis


async def check_and_record(
    user_id: uuid.UUID,
    action: str,
    limit: int | None,
    period_minutes: int,
) -> bool:
    """
    Atomically check rate limit and record the action if allowed.

    Returns True if the action was allowed and recorded, False if rate limit exceeded.
    """
    if limit is None:
        return True

    r = await _get_redis()
    key = f"streamarr:ratelimit:{user_id}:{action}"
    now = time.time()
    window_start = now - (period_minutes * 60)

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    results = await pipe.execute()

    current_count = results[1]
    if current_count >= limit:
        logger.warning("Rate limit exceeded: user_id=%s action=%s count=%d limit=%d period=%dm", user_id, action, current_count, limit, period_minutes)
        return False

    pipe = r.pipeline()
    pipe.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
    pipe.expire(key, int(period_minutes * 60) + 60)
    await pipe.execute()

    return True
