"""Regression tests for the artwork cache proxy hot path.

Covers the three ways the poster path used to be slow:
  * cache *hits* were throttled by a rate limit shared by every user (the key
    was derived from the nginx container's IP, not the real client IP),
  * the overlay fallback redirected to the provider CDN, bypassing the cache,
  * renders were queued on every miss even when no template was enabled.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.api.v1._media_artwork import (
    _ARTWORK_PROXY_HOSTS,
    artwork_cache_url,
)
from streamarr.models.media import AvailabilityStatus, MediaItem, MediaType
from streamarr.models.overlay import (
    OverlayMediaScope,
    OverlayTarget,
    OverlayTemplate,
)

_TMDB_URL = "https://image.tmdb.org/t/p/w500/abc123.jpg"


@pytest.fixture(autouse=True)
def _clear_overlay_probe_cache():
    from streamarr.api.v1.overlays import invalidate_overlay_template_probe

    invalidate_overlay_template_probe()
    yield
    invalidate_overlay_template_probe()


async def _create_item(db: AsyncSession, **overrides) -> MediaItem:
    now = datetime.now(UTC)
    defaults = {
        "guid": uuid.uuid4(),
        "title": "Cached Poster",
        "media_type": MediaType.MOVIES,
        "library_guid": None,
        "parent_guid": None,
        "poster_path": "/abc123.jpg",
        "availability_status": AvailabilityStatus.UNKNOWN,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    if not hasattr(MediaItem, "library_guid"):
        defaults.pop("library_guid", None)
    item = MediaItem(**defaults)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


def _cache_file(cache_dir, source_url: str, payload: bytes = b"cached-bytes"):
    """Pre-populate the on-disk artwork cache for the given URL (no transforms)."""
    from streamarr.api.v1._media_artwork import _artwork_cache_key

    key = _artwork_cache_key(source_url, {})
    path = cache_dir / f"{key}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class TestArtworkProxyRateLimit:
    async def test_cache_hit_is_served_without_consuming_rate_limit(
        self, client: AsyncClient, monkeypatch, tmp_path
    ):
        cache_dir = tmp_path / "artwork"
        monkeypatch.setenv("STREAMARR_ARTWORK_CACHE_ENABLED", "true")
        monkeypatch.setenv("STREAMARR_ARTWORK_CACHE_DIR", str(cache_dir))
        _cache_file(cache_dir, _TMDB_URL, b"poster-bytes")

        calls: list[tuple] = []

        async def _deny(*args, **kwargs):
            calls.append((args, kwargs))
            return False

        monkeypatch.setattr("streamarr.api.v1.media.check_and_record", _deny)

        resp = await client.get("/api/media/images/proxy", params={"url": _TMDB_URL})

        assert resp.status_code == 200
        assert resp.content == b"poster-bytes"
        assert resp.headers["x-streamarr-artwork-cache"] == "hit"
        assert calls == [], "cache hits must not be throttled"

    async def test_rate_limit_key_uses_real_client_ip(
        self, client: AsyncClient, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("STREAMARR_ARTWORK_CACHE_ENABLED", "false")
        monkeypatch.setenv("STREAMARR_ARTWORK_CACHE_DIR", str(tmp_path / "artwork"))

        seen_keys: list[uuid.UUID] = []

        async def _allow(key, *_args, **_kwargs):
            seen_keys.append(key)
            return True

        monkeypatch.setattr("streamarr.api.v1.media.check_and_record", _allow)

        async def _fake_fetch(_url: str):
            return b"fetched-bytes", "image/jpeg"

        monkeypatch.setattr("streamarr.api.v1.media._fetch_remote_image", _fake_fetch)

        resp = await client.get(
            "/api/media/images/proxy",
            params={"url": _TMDB_URL},
            headers={"X-Forwarded-For": "203.0.113.9"},
        )

        assert resp.status_code == 200
        assert seen_keys == [uuid.uuid5(uuid.NAMESPACE_URL, "artwork-proxy:203.0.113.9")]

    async def test_denied_upstream_fetch_returns_429(
        self, client: AsyncClient, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("STREAMARR_ARTWORK_CACHE_ENABLED", "false")
        monkeypatch.setenv("STREAMARR_ARTWORK_CACHE_DIR", str(tmp_path / "artwork"))

        async def _deny(*_args, **_kwargs):
            return False

        monkeypatch.setattr("streamarr.api.v1.media.check_and_record", _deny)

        resp = await client.get("/api/media/images/proxy", params={"url": _TMDB_URL})

        assert resp.status_code == 429


class TestOverlayFallback:
    async def test_fallback_redirects_through_the_artwork_cache(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user,
        user_headers,
        monkeypatch,
    ):
        item = await _create_item(db_session)
        queued: list[tuple] = []

        class _FakeTask:
            async def kiq(self, *args, **kwargs):
                queued.append((args, kwargs))

        monkeypatch.setattr("streamarr.worker.render_overlay_for_item", _FakeTask())

        resp = await client.get(
            f"/api/overlays/serve/{item.guid}", headers=user_headers
        )

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith("/api/media/images/proxy?url=")
        assert "image.tmdb.org" in location
        # No template is enabled in this test, so nothing renderable exists.
        assert queued == []
        assert resp.headers["x-overlay-render-queued"] == "false"
        assert "max-age=600" in resp.headers["cache-control"]

    async def test_render_is_queued_and_redirect_short_lived_when_template_enabled(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser,
        admin_headers,
        monkeypatch,
    ):
        item = await _create_item(db_session)
        db_session.add(
            OverlayTemplate(
                guid=uuid.uuid4(),
                name="Enabled",
                enabled=True,
                target=OverlayTarget.POSTER,
                media_scope=OverlayMediaScope.MOVIE,
                version=1,
            )
        )
        await db_session.commit()

        queued: list[tuple] = []

        class _FakeTask:
            async def kiq(self, *args, **kwargs):
                queued.append((args, kwargs))

        monkeypatch.setattr("streamarr.worker.render_overlay_for_item", _FakeTask())

        resp = await client.get(
            f"/api/overlays/serve/{item.guid}", headers=admin_headers
        )

        assert resp.status_code == 302
        assert queued == [((str(item.guid), "POSTER"), {})]
        assert resp.headers["x-overlay-render-queued"] == "true"
        assert "max-age=15" in resp.headers["cache-control"]


class TestArtworkCacheUrl:
    def test_allowlisted_host_is_routed_through_the_local_proxy(self):
        url = artwork_cache_url(_TMDB_URL)
        assert url.startswith("/api/media/images/proxy?url=")
        # Fully URL-encoded, so the query never leaks a second "?" or "&".
        assert "%3A%2F%2F" in url
        assert "?" not in url.split("?", 1)[1]

    def test_non_allowlisted_and_relative_sources_are_passed_through(self):
        assert artwork_cache_url("https://example.org/a.jpg") == (
            "https://example.org/a.jpg"
        )
        assert artwork_cache_url("/local/poster.jpg") == "/local/poster.jpg"

    def test_allowlist_is_the_same_set_the_proxy_enforces(self):
        assert "image.tmdb.org" in _ARTWORK_PROXY_HOSTS


class TestArtworkCacheKeyStability:
    def test_key_is_stable_for_same_url_and_transforms(self):
        from streamarr.api.v1._media_artwork import _artwork_cache_key

        first = _artwork_cache_key(_TMDB_URL, {"width": 300})
        second = _artwork_cache_key(_TMDB_URL, {"width": 300})
        assert first == second
        expected = hashlib.sha256(
            json.dumps(
                {"url": _TMDB_URL, "transform": {"width": 300}},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        assert first == expected
