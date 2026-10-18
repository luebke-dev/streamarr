"""Tests for the bounded artwork-cache warmup."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import AvailabilityStatus, MediaItem, MediaType
from streamarr.services.artwork_warmup import (
    TMDB_IMAGE_BASE,
    artwork_urls_for_item,
    artwork_urls_for_items,
    warm_recent_artwork,
    warm_scanned_artwork,
    warmup_item_limit,
)


def _item(**overrides) -> MediaItem:
    now = datetime.now(UTC)
    defaults = {
        "guid": uuid.uuid4(),
        "title": "Warmup Candidate",
        "media_type": MediaType.MOVIES,
        "parent_guid": None,
        "poster_path": "/poster.jpg",
        "backdrop_path": "/backdrop.jpg",
        "availability_status": AvailabilityStatus.UNKNOWN,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return MediaItem(**defaults)


class TestArtworkUrlsForItem:
    def test_expands_exactly_the_variants_the_web_client_requests(self):
        urls = artwork_urls_for_item(_item())

        assert urls == [
            f"{TMDB_IMAGE_BASE}/w780/poster.jpg",
            f"{TMDB_IMAGE_BASE}/w500/poster.jpg",
            f"{TMDB_IMAGE_BASE}/w1280/backdrop.jpg",
        ]

    def test_keeps_absolute_provider_urls_untouched(self):
        urls = artwork_urls_for_item(
            _item(poster_path="https://images.igdb.com/igdb/image/upload/t_cover.jpg")
        )

        assert urls[0] == "https://images.igdb.com/igdb/image/upload/t_cover.jpg"
        # No TMDB re-expansion of an absolute URL.
        assert not any(u.startswith(TMDB_IMAGE_BASE) and "igdb" in u for u in urls)

    def test_skips_locally_stored_artwork(self):
        for local in ("/api/media/x/images/poster", "/images/poster.jpg", "/icons/i.png"):
            assert artwork_urls_for_item(_item(poster_path=local, backdrop_path=None)) == []

    def test_handles_missing_images(self):
        assert artwork_urls_for_item(_item(poster_path=None, backdrop_path=None)) == []

    def test_tolerates_a_protocol_relative_value(self):
        assert artwork_urls_for_item(
            _item(poster_path="//cdn.example/a.jpg", backdrop_path=None)
        ) == []

    def test_item_list_deduplicates_across_items(self):
        first = _item()
        second = _item()
        urls = artwork_urls_for_items([first, second])

        assert len(urls) == len(set(urls)) == 3


class TestWarmupItemLimit:
    def test_default_and_env_override(self, monkeypatch):
        monkeypatch.delenv("STREAMARR_ARTWORK_WARMUP_ITEMS", raising=False)
        assert warmup_item_limit() == 40

        monkeypatch.setenv("STREAMARR_ARTWORK_WARMUP_ITEMS", "7")
        assert warmup_item_limit() == 7

    def test_invalid_and_negative_values_fall_back(self, monkeypatch):
        monkeypatch.setenv("STREAMARR_ARTWORK_WARMUP_ITEMS", "nonsense")
        assert warmup_item_limit() == 40

        monkeypatch.setenv("STREAMARR_ARTWORK_WARMUP_ITEMS", "-3")
        assert warmup_item_limit() == 0


class TestWarmRecentArtwork:
    async def test_warms_newest_top_level_posters_only(
        self, db_session: AsyncSession, monkeypatch
    ):
        old = datetime.now(UTC) - timedelta(days=30)
        stale = _item(title="Old", created_at=old, updated_at=old)
        newest = _item(title="New")
        child = _item(
            title="Season",
            media_type=MediaType.SHOWS,
            parent_guid=uuid.uuid4(),
        )
        no_poster = _item(title="No poster", poster_path=None, backdrop_path=None)
        db_session.add_all([stale, newest, child, no_poster])
        await db_session.commit()

        captured: dict[str, object] = {}

        async def _fake_warm(urls, limit):
            captured["urls"] = urls
            captured["limit"] = limit
            return len(urls)

        monkeypatch.setattr("streamarr.api.v1.media.warm_artwork_cache_urls", _fake_warm)

        result = await warm_recent_artwork(db_session, limit_items=1)

        assert result == {"items": 1, "urls": 3, "warmed": 3}
        assert f"{TMDB_IMAGE_BASE}/w780/poster.jpg" in captured["urls"]
        assert captured["limit"] == 3

    async def test_zero_limit_does_nothing(self, db_session: AsyncSession, monkeypatch):
        called = False

        async def _fake_warm(_urls, _limit):  # pragma: no cover - must not run
            nonlocal called
            called = True
            return 0

        monkeypatch.setattr("streamarr.api.v1.media.warm_artwork_cache_urls", _fake_warm)

        assert await warm_recent_artwork(db_session, limit_items=0) == {
            "items": 0,
            "urls": 0,
            "warmed": 0,
        }
        assert called is False


class TestWarmScannedArtwork:
    async def test_only_warms_the_touched_items(
        self, db_session: AsyncSession, monkeypatch
    ):
        scanned = _item(title="Just scanned")
        untouched = _item(title="Untouched")
        db_session.add_all([scanned, untouched])
        await db_session.commit()

        captured: dict[str, object] = {}

        async def _fake_warm(urls, limit):
            captured["urls"] = urls
            captured["limit"] = limit
            return len(urls)

        monkeypatch.setattr("streamarr.api.v1.media.warm_artwork_cache_urls", _fake_warm)

        result = await warm_scanned_artwork(
            db_session, [str(scanned.guid), "not-a-uuid"], limit_items=5
        )

        assert result == {"items": 1, "urls": 3, "warmed": 3}
        # Budget follows the rows actually found (3 variants each), not the cap.
        assert captured["limit"] == 3

    async def test_no_guids_short_circuits(self, db_session: AsyncSession):
        assert await warm_scanned_artwork(db_session, []) == {
            "items": 0,
            "urls": 0,
            "warmed": 0,
        }
