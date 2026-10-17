"""Tests for the pooled per-host outbound HTTP clients.

``safe_get`` pins the validated IP by rewriting the URL host, so httpx pools
connections by *IP*. Sharing one client across hosts could therefore hand a
connection authenticated for host A to host B; the cache is keyed by hostname
to keep pooling and pinning compatible.
"""

from __future__ import annotations

import asyncio

import pytest

from streamarr.utils.http import (
    close_pinned_async_clients,
    get_pinned_async_client,
    make_async_client,
)


@pytest.fixture(autouse=True)
async def _clean_pinned_clients():
    await close_pinned_async_clients()
    yield
    await close_pinned_async_clients()


class TestPinnedClients:
    async def test_same_host_reuses_one_client(self):
        first = await get_pinned_async_client("image.tmdb.org")
        second = await get_pinned_async_client("IMAGE.TMDB.ORG")

        assert first is second, "keep-alive pooling depends on client reuse"

    async def test_different_hosts_get_separate_pools(self):
        tmdb = await get_pinned_async_client("image.tmdb.org")
        igdb = await get_pinned_async_client("images.igdb.com")

        assert tmdb is not igdb

    async def test_eviction_closes_oldest_client(self, monkeypatch):
        import streamarr.utils.http as http_module

        monkeypatch.setattr(http_module, "_PINNED_CLIENT_LIMIT", 2)

        first = await get_pinned_async_client("a.example")
        await get_pinned_async_client("b.example")
        # Touching "a" makes "b" the eviction candidate (LRU, not FIFO).
        await get_pinned_async_client("a.example")
        await get_pinned_async_client("c.example")

        assert first.is_closed is False
        assert (
            await get_pinned_async_client("b.example")
        ).is_closed is False  # recreated, not the evicted instance

    async def test_close_releases_every_client(self):
        first = await get_pinned_async_client("image.tmdb.org")
        second = await get_pinned_async_client("images.igdb.com")

        await close_pinned_async_clients()

        assert first.is_closed and second.is_closed
        assert (await get_pinned_async_client("image.tmdb.org")) is not first

    async def test_client_is_rebound_to_a_new_event_loop(self):
        first = await get_pinned_async_client("image.tmdb.org")

        result: list[object] = []

        def _run_in_new_loop() -> None:
            async def _inner() -> None:
                result.append(await get_pinned_async_client("image.tmdb.org"))

            asyncio.run(_inner())

        await asyncio.to_thread(_run_in_new_loop)

        assert result and result[0] is not first

    async def test_make_async_client_keeps_its_default_timeout(self):
        client = make_async_client()
        try:
            assert client.timeout.read == 30.0
        finally:
            await client.aclose()
