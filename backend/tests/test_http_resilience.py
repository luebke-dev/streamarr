"""Tests for the HTTP resilience wrapper (retry + backoff + circuit breaker)."""

import httpx
import pytest

from pyrate.utils.http import (
    CircuitOpenError,
    call_with_resilience,
    request_with_resilience,
    reset_circuit_breakers,
)


@pytest.fixture(autouse=True)
def _clean_breakers():
    reset_circuit_breakers()
    yield
    reset_circuit_breakers()


class TestCallWithResilience:
    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectError("boom")
            return "ok"

        result = await call_with_resilience(
            flaky, breaker_key="host-a", backoff_base=0.0
        )
        assert result == "ok"
        assert calls["n"] == 3

    @pytest.mark.asyncio
    async def test_reraises_after_exhausting_retries(self):
        calls = {"n": 0}

        async def always_fail():
            calls["n"] += 1
            raise httpx.ConnectTimeout("nope")

        with pytest.raises(httpx.ConnectTimeout):
            await call_with_resilience(
                always_fail, breaker_key="host-b", max_retries=2, backoff_base=0.0
            )
        # initial attempt + 2 retries
        assert calls["n"] == 3

    @pytest.mark.asyncio
    async def test_non_transient_error_not_retried(self):
        calls = {"n": 0}

        async def bad():
            calls["n"] += 1
            raise ValueError("not transient")

        with pytest.raises(ValueError):
            await call_with_resilience(bad, breaker_key="host-c", backoff_base=0.0)
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_circuit_opens_and_fails_fast(self):
        async def always_fail():
            raise httpx.ConnectError("down")

        # Trip the breaker: fail_max=2 with no retries -> 1 failure per call.
        for _ in range(2):
            with pytest.raises(httpx.ConnectError):
                await call_with_resilience(
                    always_fail,
                    breaker_key="host-d",
                    max_retries=0,
                    breaker_fail_max=2,
                    backoff_base=0.0,
                )

        # Circuit is now open: the next call should fail fast without invoking
        # the function at all.
        invoked = {"n": 0}

        async def probe():
            invoked["n"] += 1
            return "should-not-run"

        with pytest.raises(CircuitOpenError):
            await call_with_resilience(
                probe, breaker_key="host-d", breaker_fail_max=2, backoff_base=0.0
            )
        assert invoked["n"] == 0

    @pytest.mark.asyncio
    async def test_circuit_half_open_recovers_on_success(self):
        # Open the breaker with a zero cooldown so the next call is a half-open
        # probe that is allowed through.
        async def fail():
            raise httpx.ConnectError("down")

        for _ in range(2):
            with pytest.raises(httpx.ConnectError):
                await call_with_resilience(
                    fail,
                    breaker_key="host-e",
                    max_retries=0,
                    breaker_fail_max=2,
                    breaker_cooldown=0.0,
                    backoff_base=0.0,
                )

        async def ok():
            return "recovered"

        result = await call_with_resilience(
            ok,
            breaker_key="host-e",
            breaker_fail_max=2,
            breaker_cooldown=0.0,
            backoff_base=0.0,
        )
        assert result == "recovered"


class TestRequestWithResilience:
    @pytest.mark.asyncio
    async def test_retries_on_5xx_then_succeeds(self):
        responses = [
            httpx.Response(503, request=httpx.Request("GET", "http://svc/")),
            httpx.Response(200, request=httpx.Request("GET", "http://svc/")),
        ]
        calls = {"n": 0}

        async def send():
            resp = responses[calls["n"]]
            calls["n"] += 1
            return resp

        resp = await request_with_resilience(
            send, breaker_key="svc-a", backoff_base=0.0
        )
        assert resp.status_code == 200
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_returns_last_5xx_after_exhausting_retries(self):
        async def send():
            return httpx.Response(500, request=httpx.Request("GET", "http://svc/"))

        resp = await request_with_resilience(
            send, breaker_key="svc-b", max_retries=1, backoff_base=0.0
        )
        # Response is still returned so callers can raise_for_status().
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_success_passes_through(self):
        async def send():
            return httpx.Response(200, request=httpx.Request("GET", "http://svc/"))

        resp = await request_with_resilience(send, breaker_key="svc-c")
        assert resp.status_code == 200
