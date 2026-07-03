"""Rate limiter behavior tests."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.requests import Request

from pyrate.api import rate_limit as rate_limit_module


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


class _BrokenRedis:
    async def incr(self, key):
        raise RedisConnectionError("redis down")


class _RedisCounter:
    def __init__(self, count: int, ttl: int = 42):
        self.count = count
        self.ttl_value = ttl
        self.expire_calls = []

    async def incr(self, key):
        return self.count

    async def expire(self, key, window_seconds):
        self.expire_calls.append((key, window_seconds))

    async def ttl(self, key):
        return self.ttl_value


async def test_rate_limiter_fails_closed_when_redis_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        rate_limit_module,
        "_get_redis",
        AsyncMock(return_value=_BrokenRedis()),
    )
    dependency = rate_limit_module.rate_limit(
        max_calls=1,
        window_seconds=60,
        scope="auth",
    )

    with pytest.raises(HTTPException) as exc:
        await dependency(_request())

    assert exc.value.status_code == 503


async def test_rate_limiter_rejects_calls_above_limit(monkeypatch):
    redis = _RedisCounter(count=2)
    monkeypatch.setattr(
        rate_limit_module,
        "_get_redis",
        AsyncMock(return_value=redis),
    )
    dependency = rate_limit_module.rate_limit(
        max_calls=1,
        window_seconds=60,
        scope="auth",
    )

    with pytest.raises(HTTPException) as exc:
        await dependency(_request())

    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "42"}


async def test_rate_limiter_sets_expiry_for_first_call(monkeypatch):
    redis = _RedisCounter(count=1)
    monkeypatch.setattr(
        rate_limit_module,
        "_get_redis",
        AsyncMock(return_value=redis),
    )
    dependency = rate_limit_module.rate_limit(
        max_calls=1,
        window_seconds=60,
        scope="auth",
    )

    await dependency(_request())

    assert redis.expire_calls == [("pyrate:ratelimit:auth:127.0.0.1", 60)]
