"""Tests for the favorites quality-profile / monitoring / RSS / upgrade feature.

Covers the high-value new logic across S1 (quality), S2 (monitoring),
S3 (RSS / upgrade eligibility) and the cross-subsystem adapter.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest_asyncio

from pyrate.libraries.quality import (
    QualityKind,
    parse_quality,
    qualities_for_media_type,
)
from pyrate.models.media import MediaFile, MediaItem, MediaRelease, MediaType
from pyrate.schemas.scoring import QualityProfile
from pyrate.services.quality_profile import QualityProfileService, default_profile

# --------------------------------------------------------------------- #
# S1 — quality ladder (pure)
# --------------------------------------------------------------------- #

def test_parse_quality_video_ordering():
    bluray2160 = parse_quality(
        {"resolution": "2160p", "source": "bluray"}, media_type="MOVIES"
    )
    remux2160 = parse_quality(
        {"resolution": "2160p", "source": "bluray", "is_remux": True},
        media_type="MOVIES",
    )
    webdl1080 = parse_quality(
        {"resolution": "1080p", "source": "web-dl"}, media_type="MOVIES"
    )
    hdtv720 = parse_quality(
        {"resolution": "720p", "source": "hdtv"}, media_type="SHOWS"
    )
    assert remux2160.rank > bluray2160.rank > webdl1080.rank > hdtv720.rank
    assert remux2160.kind is QualityKind.VIDEO


def test_parse_quality_revision_and_fallback():
    repack = parse_quality(
        {"resolution": "1080p", "source": "bluray", "is_repack": True},
        media_type="MOVIES",
    )
    assert repack.revision == 1
    unknown = parse_quality({}, media_type="MUSIC", title="???")
    assert unknown.id == "unknown" and unknown.rank == 0


def test_parse_quality_audio_and_book():
    flac = parse_quality({"format": "flac"}, media_type="MUSIC")
    mp3 = parse_quality({}, media_type="MUSIC", title="Artist - Album MP3 320")
    assert flac.rank > mp3.rank
    retail = parse_quality(
        {"format": "epub", "is_retail": True}, media_type="BOOKS"
    )
    pdf = parse_quality({"format": "pdf"}, media_type="BOOKS")
    assert retail.rank > pdf.rank


def test_qualities_for_media_type_books_no_dup_unknown():
    ids = [d.id for d in qualities_for_media_type("BOOKS")]
    assert ids.count("unknown") == 1
    assert "m4b-audiobook" in ids


def test_default_profile_shape():
    p = default_profile("MOVIES")
    assert isinstance(p, QualityProfile)
    assert p.cutoff == "webdl-1080p"
    assert p.upgrade_allowed is True
    assert any(i.id == "remux-2160p" for i in p.items)


# --------------------------------------------------------------------- #
# S1 — cutoff / upgrade decisions (DB)
# --------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def movie(db_session):
    mi = MediaItem(guid=uuid.uuid4(), media_type=MediaType.MOVIES, title="Test Movie")
    db_session.add(mi)
    await db_session.commit()
    return mi


async def test_cutoff_met_no_file_is_false(db_session, movie):
    svc = QualityProfileService(db_session)
    assert await svc.cutoff_met(movie) is False


async def test_is_upgrade_wanted_truth_table(db_session, movie):
    svc = QualityProfileService(db_session)
    # Current file = HDTV 720p — below the default cutoff (webdl-1080p),
    # so an upgrade is still wanted.
    mf = MediaFile(
        guid=uuid.uuid4(),
        media_item_guid=movie.guid,
        file_path="/library/test.mkv",
        quality="hdtv-720p",
        quality_rank=parse_quality(
            {"resolution": "720p", "source": "hdtv"}, media_type="MOVIES"
        ).rank,
    )
    db_session.add(mf)
    # A clearly-better candidate.
    better = MediaRelease(
        guid=uuid.uuid4(),
        media_item_guid=movie.guid,
        title="Test.Movie.2024.2160p.BluRay.REMUX-GRP",
        release_metadata={"resolution": "2160p", "source": "bluray", "is_remux": True},
    )
    worse = MediaRelease(
        guid=uuid.uuid4(),
        media_item_guid=movie.guid,
        title="Test.Movie.2024.720p.HDTV-GRP",
        release_metadata={"resolution": "720p", "source": "hdtv"},
    )
    db_session.add_all([better, worse])
    await db_session.commit()

    assert await svc.is_upgrade_wanted(movie, better, current_file=mf) is True
    assert await svc.is_upgrade_wanted(movie, worse, current_file=mf) is False


async def test_link_media_file_to_release_persists(db_session, movie):
    svc = QualityProfileService(db_session)
    rel = MediaRelease(
        guid=uuid.uuid4(),
        media_item_guid=movie.guid,
        title="Test.Movie.2024.1080p.WEB-DL-GRP",
        release_metadata={"resolution": "1080p", "source": "web-dl"},
        score=42,
    )
    mf = MediaFile(
        guid=uuid.uuid4(), media_item_guid=movie.guid, file_path="/library/x.mkv"
    )
    db_session.add_all([rel, mf])
    await db_session.commit()
    await svc.link_media_file_to_release(mf, rel, MediaType.MOVIES)
    assert mf.source_release_guid == rel.guid
    assert mf.quality == "webdl-1080p"
    assert mf.quality_score == 42.0


# --------------------------------------------------------------------- #
# S2 — monitoring + protected lineage (DB)
# --------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def show_tree(db_session):
    show = MediaItem(guid=uuid.uuid4(), media_type=MediaType.SHOWS, title="Show", monitored=True, monitored_source="favorite")
    db_session.add(show)
    await db_session.flush()
    season = MediaItem(guid=uuid.uuid4(), media_type=MediaType.SHOWS, title="S1", parent_guid=show.guid, monitored=True, monitored_source="favorite")
    db_session.add(season)
    await db_session.flush()
    eps = [
        MediaItem(
            guid=uuid.uuid4(), media_type=MediaType.SHOWS, title=f"E{n}",
            parent_guid=season.guid, sequence_number=n,
            monitored=True, monitored_source="favorite",
        )
        for n in (1, 2, 3)
    ]
    db_session.add_all(eps)
    await db_session.commit()
    return show, season, eps


async def test_monitoring_iter_leaves(db_session, show_tree):
    from pyrate.services.monitoring import MonitoringService

    show, _season, _eps = show_tree
    svc = MonitoringService(db_session)
    leaves = [mi async for mi in svc.iter_monitored_leaves()]
    leaf_titles = {mi.title for mi in leaves}
    assert leaf_titles == {"E1", "E2", "E3"}  # show/season are not leaves
    roots = [mi async for mi in svc.iter_monitored_roots()]
    assert [r.title for r in roots] == [show.title]


async def test_monitoring_missing_leaves(db_session, show_tree):
    from pyrate.services.monitoring import MonitoringService

    show, season, eps = show_tree
    db_session.add(
        MediaFile(guid=uuid.uuid4(), media_item_guid=eps[0].guid, file_path="/e1.mkv")
    )
    await db_session.commit()
    svc = MonitoringService(db_session)
    missing = [mi async for mi in svc.iter_missing_monitored_leaves()]
    assert {mi.title for mi in missing} == {"E2", "E3"}  # E1 has a file


async def test_backfill_worker_helpers(db_session, show_tree):
    from pyrate.workers.favorites_monitor_worker import (
        _collect_subtree,
        _leaf_guids,
        _missing_leaves,
    )

    show, season, eps = show_tree
    rows = await _collect_subtree(db_session, str(show.guid))
    assert len(rows) == 5  # show + season + 3 eps
    leaves = _leaf_guids(rows)
    assert len(leaves) == 3
    missing = await _missing_leaves(db_session, leaves)
    assert len(missing) == 3  # none have files


async def test_protected_lineage_monitored(db_session, show_tree):
    from pyrate.services.storage_cleanup import StorageCleanupService

    show, season, eps = show_tree
    unmon = MediaItem(guid=uuid.uuid4(), media_type=MediaType.MOVIES, title="Free")
    db_session.add(unmon)
    await db_session.commit()
    svc = StorageCleanupService(db_session)
    prot = await svc._collect_protected_lineage(
        {eps[0].guid, unmon.guid}, include_favorites=False
    )
    assert eps[0].guid in prot  # monitored (via lineage) — always protected
    assert unmon.guid not in prot


# --------------------------------------------------------------------- #
# S3 — adapter + eligibility + RSS parse
# --------------------------------------------------------------------- #

async def test_upgrade_interfaces_available(db_session):
    from pyrate.services import upgrade_interfaces as ui

    assert ui.available() == {"quality": True, "monitoring": True}
    leaves = await ui.iter_monitored_leaves(db_session, limit=5)
    assert isinstance(leaves, list)


async def test_auto_download_is_eligible_upgrade_bypasses_file(db_session, movie):
    from pyrate.services.auto_download import AutoDownloadService

    db_session.add(
        MediaFile(guid=uuid.uuid4(), media_item_guid=movie.guid, file_path="/f.mkv")
    )
    await db_session.commit()
    svc = AutoDownloadService(db_session)
    # Non-upgrade: a file exists -> not eligible.
    assert await svc._is_eligible(movie, upgrade=False) is False
    # Upgrade: existing file is expected -> eligible (cap not reached).
    assert await svc._is_eligible(movie, upgrade=True) is True


async def test_newznab_fetch_recent_parses_and_limits():
    from pyrate.indexers.newznab import Newznab

    nz = Newznab(base_url="http://x", api_key="k", id="ix1")
    payload = {
        "channel": {
            "item": [
                {"title": f"Rel {i}", "guid": f"g{i}", "pubDate": "2026-05-16"}
                for i in range(5)
            ]
        }
    }
    with patch.object(nz, "_request", AsyncMock(return_value=payload)):
        items = await nz.fetch_recent(limit=3)
    assert len(items) == 3
    assert items[0]["indexer_id"] == "ix1"
    assert all("publish_date" in it for it in items)
    await nz.close()


async def test_newznab_fetch_recent_error_returns_empty():
    from pyrate.indexers.base import IndexerError
    from pyrate.indexers.newznab import Newznab

    nz = Newznab(base_url="http://x", api_key="k", id="ix1")
    with patch.object(nz, "_request", AsyncMock(side_effect=IndexerError("boom"))):
        assert await nz.fetch_recent() == []
    await nz.close()


async def test_rss_sync_disabled_skips(db_session):
    """Master switch defaults OFF → run_once is a no-op."""
    from pyrate.services.rss_sync import RssSyncService

    res = await RssSyncService(db_session).run_once()
    assert res.skipped_disabled is True
