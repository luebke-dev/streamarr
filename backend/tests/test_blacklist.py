"""Tests for release blacklisting on download/import failure."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.downloader import Downloader
from pyrate.models.downloads import Download
from pyrate.models.media import (
    MediaItem,
    MediaRelease,
    MediaReleaseLink,
    MediaType,
)
from pyrate.services.download import DownloadService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def download_service(db_session: AsyncSession) -> DownloadService:
    return DownloadService(db_session)


@pytest_asyncio.fixture
async def test_downloader(db_session: AsyncSession) -> Downloader:
    downloader = Downloader(
        guid=uuid.uuid4(),
        label="Test SABnzbd",
        type="sabnzbd",
        host="http://localhost:8080",
        api_key="test-api-key",
    )
    db_session.add(downloader)
    await db_session.commit()
    await db_session.refresh(downloader)
    return downloader


@pytest_asyncio.fixture
async def media_item(db_session: AsyncSession) -> MediaItem:
    item = MediaItem(
        guid=uuid.uuid4(),
        title="Test Movie (2024)",
        media_type=MediaType.MOVIES,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest_asyncio.fixture
async def release_with_link(
    db_session: AsyncSession, media_item: MediaItem
) -> tuple[MediaRelease, MediaReleaseLink]:
    release = MediaRelease(
        guid=uuid.uuid4(),
        media_item_guid=media_item.guid,
        title="Test.Movie.2024.1080p.BluRay.x264-GRP",
        size=8_000_000_000,
    )
    db_session.add(release)
    await db_session.flush()

    link = MediaReleaseLink(
        guid=uuid.uuid4(),
        media_release_guid=release.guid,
        link="https://indexer.example/nzb/12345",
        link_type="nzb",
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(release)
    await db_session.refresh(link)
    return release, link


@pytest_asyncio.fixture
async def test_download(
    db_session: AsyncSession,
    test_downloader: Downloader,
    release_with_link: tuple[MediaRelease, MediaReleaseLink],
) -> Download:
    _release, link = release_with_link
    download = Download(
        guid=uuid.uuid4(),
        title="Test Movie (2024)",
        type="movie",
        downloader_id=test_downloader.guid,
        status="Completed",
        external_id="nzo_blacklist_test",
        media_release_link_guid=link.guid,
    )
    db_session.add(download)
    await db_session.commit()
    await db_session.refresh(download)
    return download


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBlacklistDownload:
    """Tests for DownloadService.blacklist_download."""

    @pytest.mark.asyncio
    async def test_blacklist_sets_reason(
        self,
        download_service: DownloadService,
        test_download: Download,
        release_with_link: tuple[MediaRelease, MediaReleaseLink],
        db_session: AsyncSession,
    ):
        """Blacklisting a download sets blacklisted_reason on the release."""
        release, _ = release_with_link
        assert release.blacklisted_reason is None

        result = await download_service.blacklist_download(
            test_download, "No valid video files found"
        )
        assert result is True

        await db_session.refresh(release)
        assert release.blacklisted_reason == "No valid video files found"

    @pytest.mark.asyncio
    async def test_blacklist_idempotent(
        self,
        download_service: DownloadService,
        test_download: Download,
        release_with_link: tuple[MediaRelease, MediaReleaseLink],
        db_session: AsyncSession,
    ):
        """Calling blacklist_download twice does not error."""
        release, _ = release_with_link

        await download_service.blacklist_download(test_download, "reason 1")
        result = await download_service.blacklist_download(test_download, "reason 2")
        assert result is True

        await db_session.refresh(release)
        # The first reason sticks — idempotent
        assert release.blacklisted_reason == "reason 1"

    @pytest.mark.asyncio
    async def test_blacklist_no_release_link(
        self,
        download_service: DownloadService,
        test_downloader: Downloader,
        db_session: AsyncSession,
    ):
        """Blacklisting a download without a release link returns False."""
        orphan = Download(
            guid=uuid.uuid4(),
            title="Orphan Download",
            type="movie",
            downloader_id=test_downloader.guid,
            status="Failed",
            external_id="nzo_orphan",
            media_release_link_guid=None,
        )
        db_session.add(orphan)
        await db_session.commit()

        result = await download_service.blacklist_download(orphan, "some reason")
        assert result is False

    @pytest.mark.asyncio
    async def test_blacklist_default_reason(
        self,
        download_service: DownloadService,
        test_download: Download,
        release_with_link: tuple[MediaRelease, MediaReleaseLink],
        db_session: AsyncSession,
    ):
        """Blacklisting without an explicit reason uses a default string."""
        release, _ = release_with_link

        await download_service.blacklist_download(test_download)

        await db_session.refresh(release)
        assert release.blacklisted_reason == "Unknown failure"


class TestGetMediaItemGuidForDownload:
    """Tests for DownloadService.get_media_item_guid_for_download."""

    @pytest.mark.asyncio
    async def test_resolves_guid(
        self,
        download_service: DownloadService,
        test_download: Download,
        media_item: MediaItem,
    ):
        guid = await download_service.get_media_item_guid_for_download(test_download)
        assert guid == media_item.guid

    @pytest.mark.asyncio
    async def test_returns_none_without_link(
        self,
        download_service: DownloadService,
        test_downloader: Downloader,
        db_session: AsyncSession,
    ):
        orphan = Download(
            guid=uuid.uuid4(),
            title="Orphan",
            type="movie",
            downloader_id=test_downloader.guid,
            status="Failed",
            external_id="nzo_orphan2",
        )
        db_session.add(orphan)
        await db_session.commit()

        guid = await download_service.get_media_item_guid_for_download(orphan)
        assert guid is None


class TestBlacklistedReleaseFiltering:
    """Ensure blacklisted releases can be filtered out with a simple query."""

    @pytest.mark.asyncio
    async def test_blacklisted_releases_filtered(
        self,
        db_session: AsyncSession,
        media_item: MediaItem,
    ):
        """Releases with a blacklisted_reason should be excluded from queries."""
        good = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="Good.Release.2024.1080p",
            size=5_000_000_000,
        )
        bad = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="Bad.Release.2024.1080p",
            size=5_000_000_000,
            blacklisted_reason="No valid video files found",
        )
        db_session.add_all([good, bad])
        await db_session.commit()

        result = await db_session.execute(
            select(MediaRelease).where(
                MediaRelease.media_item_guid == media_item.guid,
                MediaRelease.blacklisted_reason.is_(None),
            )
        )
        available = result.scalars().all()

        assert len(available) == 1
        assert available[0].guid == good.guid
