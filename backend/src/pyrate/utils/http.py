"""Shared HTTP client helpers.

Every outbound HTTP client should set an explicit timeout so a hung upstream
can't pin a request worker indefinitely. This module centralises the default
so indexers, downloaders and metadata plugins don't each have to remember.
"""

import httpx

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
