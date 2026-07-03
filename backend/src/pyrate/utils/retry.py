"""Shared retry helper for outbound HTTP calls to metadata providers.

Each metadata provider (TMDB, TVDB, IGDB, Spotify, MusicBrainz) used to
roll its own ``_request`` with retry/backoff/rate-limit handling. They had
drifted enough over time that one of them lost its 429 handling entirely.
This helper standardises the retry kernel — providers only have to supply
the per-attempt request closure (and optionally an auth-refresh callback
for OAuth-backed APIs).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)


async def http_with_retries(
    do_request: Callable[[], Awaitable[httpx.Response]],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    on_unauthorized: Callable[[], Awaitable[None]] | None = None,
    log_label: str = "http",
) -> httpx.Response | None:
    """Run ``do_request()`` with retries on transient failures.

    Behaviour:
    - 429 Too Many Requests: honour ``Retry-After`` header when present,
      otherwise exponential backoff (``base_delay * 2**attempt``).
    - 401 Unauthorized: when ``on_unauthorized`` is supplied, invoke it
      once to refresh credentials, then retry once. Subsequent 401s pass
      through to the caller.
    - Network / timeout errors: exponential backoff, retry up to
      ``max_retries`` total attempts.
    - Successful 2xx/3xx responses (or non-429/401 4xx/5xx) return
      immediately so the caller can decide what to do with the body.
    - Returns ``None`` only when all attempts exhausted on transient errors.
    """
    refreshed = False
    for attempt in range(max_retries):
        try:
            response = await do_request()
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning(
                "%s transient error (attempt %d/%d): %s",
                log_label, attempt + 1, max_retries, exc,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))
            continue

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else base_delay * (2 ** attempt)
            except ValueError:
                wait = base_delay * (2 ** attempt)
            logger.warning(
                "%s rate-limited, waiting %.1fs (attempt %d/%d)",
                log_label, wait, attempt + 1, max_retries,
            )
            await asyncio.sleep(wait)
            continue

        if response.status_code == 401 and on_unauthorized and not refreshed:
            refreshed = True
            try:
                await on_unauthorized()
            except Exception as exc:
                logger.error("%s auth refresh failed: %s", log_label, exc)
                return response
            continue

        return response

    logger.error("%s exhausted %d retries", log_label, max_retries)
    return None
