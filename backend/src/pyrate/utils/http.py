"""Shared HTTP client helpers.

Every outbound HTTP client should set an explicit timeout so a hung upstream
can't pin a request worker indefinitely. This module centralises the default
so indexers, downloaders and metadata plugins don't each have to remember.

It also provides a lightweight *resilience* layer for calls to internal
downstream services (Downloader, Lightrays): retry with exponential backoff on
transient transport failures, plus a simple per-host circuit breaker so a
service that is down doesn't get hammered on every request.

The circuit-breaker state is **in-memory and process-local**: it is not shared
across worker processes or replicas, so each process trips its own breaker
independently. This is a deliberate trade-off to avoid pulling in a heavier
dependency (Redis-backed breaker, ``pybreaker``, ``tenacity``); for guarding
short-lived blips against a handful of internal hosts it is entirely adequate.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

# (connect, read, write, pool) in seconds. Generous read timeout because
# indexer queries can take a while on slow sites; short connect so a dead
# host fails fast.
_DEFAULT_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=30.0,
    write=10.0,
    pool=10.0,
)


def make_async_client(
    *,
    timeout: httpx.Timeout | float | None = None,
    **kwargs,
) -> httpx.AsyncClient:
    """Return a configured :class:`httpx.AsyncClient` with a sane timeout.

    Additional ``**kwargs`` are forwarded to ``AsyncClient`` unchanged.
    """
    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
    return httpx.AsyncClient(timeout=effective_timeout, **kwargs)


# ── Resilience: retry + backoff + per-host circuit breaker ─────────────────


class CircuitOpenError(RuntimeError):
    """Raised when a target's circuit breaker is open and rejecting calls fast.

    Signals "this host is currently considered down" so the caller can fail
    quickly instead of waiting on a connect timeout it's very likely to lose.
    """


# Transient httpx failures worth retrying: the request either never completed
# or the connection dropped. A 5xx *response* is handled separately by
# :func:`request_with_resilience`.
TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)

# Idempotency-safe subset: the connection was never established (or never
# obtained from the pool), so the server cannot have processed the request and
# a retry cannot duplicate a side effect. Use this for non-idempotent POSTs
# (e.g. Lightrays *launch*) so retries never spawn duplicate sessions.
CONNECT_ONLY_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)

_DEFAULT_MAX_RETRIES = 2  # total attempts = max_retries + 1
_DEFAULT_BACKOFF_BASE = 0.5
_DEFAULT_BACKOFF_MAX = 8.0
_DEFAULT_BREAKER_FAIL_MAX = 5
_DEFAULT_BREAKER_COOLDOWN = 30.0


class _HostCircuit:
    """Minimal three-state breaker for a single target host.

    CLOSED  -> calls pass through; consecutive failures are counted.
    OPEN    -> once ``fail_max`` failures accrue, calls are rejected fast for
               ``cooldown`` seconds.
    HALF-OPEN -> after the cooldown a single probe is allowed through; success
               closes the breaker, another failure re-opens it for a fresh
               cooldown window.
    """

    __slots__ = ("fail_max", "cooldown", "failures", "opened_at")

    def __init__(self, fail_max: int, cooldown: float):
        self.fail_max = fail_max
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at: float | None = None

    def raise_if_open(self, key: str) -> None:
        if self.opened_at is None:
            return
        if (time.monotonic() - self.opened_at) < self.cooldown:
            raise CircuitOpenError(
                f"circuit open for {key!r}; failing fast until cooldown elapses"
            )
        # Cooldown elapsed: leave state as-is and let one probe through
        # (half-open). record_success / record_failure will resolve it.

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.fail_max:
            # (Re)open the breaker and start a fresh cooldown window.
            self.opened_at = time.monotonic()


# Process-local breaker registry (see module docstring for the trade-off).
_circuits: dict[str, _HostCircuit] = {}


def _get_circuit(key: str, fail_max: int, cooldown: float) -> _HostCircuit:
    circuit = _circuits.get(key)
    if circuit is None:
        circuit = _HostCircuit(fail_max, cooldown)
        _circuits[key] = circuit
    return circuit


def reset_circuit_breakers() -> None:
    """Drop all breaker state. Intended for tests / manual recovery."""
    _circuits.clear()


def host_key(url: str) -> str:
    """Return a stable per-host breaker key for ``url``."""
    try:
        return httpx.URL(url).host or url
    except Exception:
        return url


def _backoff_delay(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with full jitter (50–100% of the computed delay)."""
    delay = min(cap, base * (2**attempt))
    return delay * (0.5 + random.random() / 2)


async def call_with_resilience[T](
    func: Callable[[], Awaitable[T]],
    *,
    breaker_key: str,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    backoff_base: float = _DEFAULT_BACKOFF_BASE,
    backoff_max: float = _DEFAULT_BACKOFF_MAX,
    retry_exceptions: tuple[type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    breaker_fail_max: int = _DEFAULT_BREAKER_FAIL_MAX,
    breaker_cooldown: float = _DEFAULT_BREAKER_COOLDOWN,
) -> T:
    """Run ``func`` with retry + backoff and a per-host circuit breaker.

    ``func`` is a zero-arg callable returning an awaitable (e.g.
    ``lambda: client.get_downloads()``). Only exceptions in
    ``retry_exceptions`` are retried; anything else propagates immediately.
    Repeated transient failures trip the ``breaker_key`` breaker, after which
    calls fail fast with :class:`CircuitOpenError` until the cooldown elapses.
    """
    circuit = _get_circuit(breaker_key, breaker_fail_max, breaker_cooldown)
    attempt = 0
    while True:
        circuit.raise_if_open(breaker_key)
        try:
            result = await func()
        except retry_exceptions as exc:
            circuit.record_failure()
            if attempt >= max_retries:
                logger.warning(
                    "resilience: %s exhausted after %d retr%s: %s",
                    breaker_key,
                    attempt,
                    "y" if attempt == 1 else "ies",
                    exc,
                )
                raise
            delay = _backoff_delay(attempt, backoff_base, backoff_max)
            logger.info(
                "resilience: retrying %s (attempt %d) in %.2fs after %s",
                breaker_key,
                attempt + 1,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
            attempt += 1
        else:
            circuit.record_success()
            return result


async def request_with_resilience(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    breaker_key: str,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    backoff_base: float = _DEFAULT_BACKOFF_BASE,
    backoff_max: float = _DEFAULT_BACKOFF_MAX,
    retry_exceptions: tuple[type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    retry_on_server_error: bool = True,
    breaker_fail_max: int = _DEFAULT_BREAKER_FAIL_MAX,
    breaker_cooldown: float = _DEFAULT_BREAKER_COOLDOWN,
) -> httpx.Response:
    """Like :func:`call_with_resilience` but for httpx requests.

    ``send`` is a zero-arg callable returning an awaitable ``httpx.Response``
    (e.g. ``lambda: client.post(url, json=...)``). In addition to retrying
    transient transport exceptions, a ``5xx`` response is treated as a
    transient failure (retried and counted against the breaker). The response
    is still returned to the caller after retries are exhausted so existing
    ``raise_for_status()`` handling is preserved.
    """
    circuit = _get_circuit(breaker_key, breaker_fail_max, breaker_cooldown)
    attempt = 0
    while True:
        circuit.raise_if_open(breaker_key)
        try:
            resp = await send()
        except retry_exceptions as exc:
            circuit.record_failure()
            if attempt >= max_retries:
                logger.warning(
                    "resilience: %s exhausted after %d retries: %s",
                    breaker_key,
                    attempt,
                    exc,
                )
                raise
            delay = _backoff_delay(attempt, backoff_base, backoff_max)
            logger.info(
                "resilience: retrying %s (attempt %d) in %.2fs after %s",
                breaker_key,
                attempt + 1,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue

        if retry_on_server_error and resp.status_code >= 500:
            circuit.record_failure()
            if attempt >= max_retries:
                logger.warning(
                    "resilience: %s returned %d after %d retries",
                    breaker_key,
                    resp.status_code,
                    attempt,
                )
                return resp
            delay = _backoff_delay(attempt, backoff_base, backoff_max)
            logger.info(
                "resilience: retrying %s (attempt %d) in %.2fs after HTTP %d",
                breaker_key,
                attempt + 1,
                delay,
                resp.status_code,
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue

        circuit.record_success()
        return resp
