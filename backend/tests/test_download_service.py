"""Tests for DownloadService (download management, DB operations and pure logic)."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.downloader import Downloader
from streamarr.models.downloads import Download
from streamarr.services.download import DownloadService


@pytest_asyncio.fixture
async def download_service(db_session: AsyncSession) -> DownloadService:
    """Create a DownloadService instance."""
    return DownloadService(db_session)


@pytest_asyncio.fixture
async def test_downloader(db_session: AsyncSession) -> Downloader:
    """Create a test downloader."""
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
async def test_download(
    db_session: AsyncSession, test_downloader: Downloader
) -> Download:
    """Create a test download record."""
    download = Download(
        guid=uuid.uuid4(),
        title="Test Movie (2024)",
        type="movie",
        downloader_id=test_downloader.guid,
        status="queued",
        external_id="nzo_test123",
        progress=0.0,
    )
    db_session.add(download)
    await db_session.commit()
    await db_session.refresh(download)
    return download


class TestGetByExternalId:
    """Tests for getting downloads by external ID."""

    @pytest.mark.asyncio
    async def test_get_by_external_id(
        self, download_service: DownloadService, test_download: Download
    ):
        """Test finding a download by its external ID."""
        result = await download_service.get_by_external_id("nzo_test123")

        assert result is not None
        assert result.external_id == "nzo_test123"
        assert result.title == "Test Movie (2024)"

    @pytest.mark.asyncio
    async def test_get_by_external_id_not_found(
        self, download_service: DownloadService
    ):
        """Test looking up a non-existent external ID."""
        result = await download_service.get_by_external_id("nonexistent")
        assert result is None


class TestMarkAsImported:
    """Tests for marking downloads as imported."""

    @pytest.mark.asyncio
    async def test_mark_as_imported(
        self, download_service: DownloadService, test_download: Download
    ):
        """Test marking a download as imported."""
        await download_service.mark_as_imported(test_download)

        result = await download_service.get_by_external_id(test_download.external_id)
        assert result.status == "Imported"


class TestMarkAsFailed:
    """Tests for marking downloads as failed."""

    @pytest.mark.asyncio
    async def test_mark_as_failed(
        self, download_service: DownloadService, test_download: Download
    ):
        """Test marking a download as failed."""
        await download_service.mark_as_failed(test_download, reason="Corrupt file")

        result = await download_service.get_by_external_id(test_download.external_id)
        assert result.status == "Failed"

    @pytest.mark.asyncio
    async def test_mark_as_failed_no_reason(
        self, download_service: DownloadService, test_download: Download
    ):
        """Test marking a download as failed without a reason."""
        await download_service.mark_as_failed(test_download)

        result = await download_service.get_by_external_id(test_download.external_id)
        assert result.status == "Failed"


class TestIsValidVideoFile:
    """Tests for video file validation."""

    def test_valid_mkv(self, download_service: DownloadService, tmp_path):
        """Test that .mkv files are valid."""
        file = tmp_path / "movie.mkv"
        file.write_bytes(b"\x00" * 100)
        assert download_service.is_valid_video_file(file) is True

    def test_valid_mp4(self, download_service: DownloadService, tmp_path):
        """Test that .mp4 files are valid."""
        file = tmp_path / "movie.mp4"
        file.write_bytes(b"\x00" * 100)
        assert download_service.is_valid_video_file(file) is True

    def test_valid_avi(self, download_service: DownloadService, tmp_path):
        """Test that .avi files are valid."""
        file = tmp_path / "movie.avi"
        file.write_bytes(b"\x00" * 100)
        assert download_service.is_valid_video_file(file) is True

    def test_invalid_extension(self, download_service: DownloadService, tmp_path):
        """Test that non-video extensions are rejected."""
        file = tmp_path / "readme.txt"
        file.write_bytes(b"\x00" * 100)
        assert download_service.is_valid_video_file(file) is False

    def test_sample_file_rejected(self, download_service: DownloadService, tmp_path):
        """Test that sample files are rejected."""
        file = tmp_path / "sample.mkv"
        file.write_bytes(b"\x00" * 100)
        assert download_service.is_valid_video_file(file) is False

    def test_sample_in_name_rejected(
        self, download_service: DownloadService, tmp_path
    ):
        """Test that files with 'sample' in the name are rejected."""
        file = tmp_path / "Movie.Sample.mkv"
        file.write_bytes(b"\x00" * 100)
        assert download_service.is_valid_video_file(file) is False

    def test_nonexistent_file(self, download_service: DownloadService, tmp_path):
        """Test that non-existent files are rejected."""
        file = tmp_path / "nonexistent.mkv"
        assert download_service.is_valid_video_file(file) is False

    def test_directory_rejected(self, download_service: DownloadService, tmp_path):
        """Test that directories are rejected."""
        dir_path = tmp_path / "movie_dir.mkv"
        dir_path.mkdir()
        assert download_service.is_valid_video_file(dir_path) is False

    def test_valid_mov(self, download_service: DownloadService, tmp_path):
        """Test that .mov files are valid."""
        file = tmp_path / "video.mov"
        file.write_bytes(b"\x00" * 100)
        assert download_service.is_valid_video_file(file) is True

    def test_valid_mpeg(self, download_service: DownloadService, tmp_path):
        """Test that .mpeg files are valid."""
        file = tmp_path / "video.mpeg"
        file.write_bytes(b"\x00" * 100)
        assert download_service.is_valid_video_file(file) is True

    def test_nfo_file_rejected(self, download_service: DownloadService, tmp_path):
        """Test that .nfo files are rejected."""
        file = tmp_path / "movie.nfo"
        file.write_bytes(b"\x00" * 100)
        assert download_service.is_valid_video_file(file) is False

    def test_srt_file_rejected(self, download_service: DownloadService, tmp_path):
        """Test that subtitle files are rejected."""
        file = tmp_path / "movie.srt"
        file.write_bytes(b"\x00" * 100)
        assert download_service.is_valid_video_file(file) is False


class TestExtractExternalId:
    """Tests for extracting external IDs from downloader responses."""

    @pytest.mark.asyncio
    async def test_extract_sabnzbd_id(
        self, download_service: DownloadService, test_downloader: Downloader
    ):
        """Test extracting external ID from SABnzbd response."""
        status = {"nzo_ids": ["nzo_abc123"]}
        result = await download_service.extract_external_id_from_response(
            test_downloader, status
        )
        assert result == "nzo_abc123"

    @pytest.mark.asyncio
    async def test_extract_sabnzbd_id_empty(
        self, download_service: DownloadService, test_downloader: Downloader
    ):
        """Test extracting when SABnzbd returns empty nzo_ids."""
        status = {"nzo_ids": []}
        result = await download_service.extract_external_id_from_response(
            test_downloader, status
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_deluge_id(
        self,
        download_service: DownloadService,
        db_session: AsyncSession,
    ):
        """Test extracting external ID from Deluge response."""
        deluge_downloader = Downloader(
            guid=uuid.uuid4(),
            label="Test Deluge",
            type="deluge",
            host="http://localhost:8112",
            api_key="deluge-key",
        )
        db_session.add(deluge_downloader)
        await db_session.commit()

        status = {"torrent_hash": "abc123def456"}
        result = await download_service.extract_external_id_from_response(
            deluge_downloader, status
        )
        assert result == "abc123def456"

    @pytest.mark.asyncio
    async def test_extract_deluge_id_missing(
        self,
        download_service: DownloadService,
        db_session: AsyncSession,
    ):
        """Test extracting when Deluge response has no hash."""
        deluge_downloader = Downloader(
            guid=uuid.uuid4(),
            label="Test Deluge",
            type="deluge",
            host="http://localhost:8112",
            api_key="deluge-key",
        )
        db_session.add(deluge_downloader)
        await db_session.commit()

        status = {}
        result = await download_service.extract_external_id_from_response(
            deluge_downloader, status
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_spotdl_id(
        self,
        download_service: DownloadService,
        db_session: AsyncSession,
    ):
        """Test extracting external ID from spotdl response."""
        spotdl_downloader = Downloader(
            guid=uuid.uuid4(),
            label="Test spotdl",
            type="spotdl",
            host="http://localhost:3000",
            api_key="",
        )
        db_session.add(spotdl_downloader)
        await db_session.commit()

        status = {"job_id": "f7e3a7a4-a814-4e3c-b9fb-845d02264bb4"}
        result = await download_service.extract_external_id_from_response(
            spotdl_downloader, status
        )
        assert result == "f7e3a7a4-a814-4e3c-b9fb-845d02264bb4"

    @pytest.mark.asyncio
    async def test_extract_spotdl_id_missing(
        self,
        download_service: DownloadService,
        db_session: AsyncSession,
    ):
        """Test extracting when spotdl response has no job_id."""
        spotdl_downloader = Downloader(
            guid=uuid.uuid4(),
            label="Test spotdl",
            type="spotdl",
            host="http://localhost:3000",
            api_key="",
        )
        db_session.add(spotdl_downloader)
        await db_session.commit()

        status = {}
        result = await download_service.extract_external_id_from_response(
            spotdl_downloader, status
        )
        assert result is None


class TestDownloadStatusTransitions:
    """Tests for download status transitions."""

    @pytest.mark.asyncio
    async def test_queued_to_imported(
        self, download_service: DownloadService, test_download: Download
    ):
        """Test transitioning a download from queued to imported."""
        assert test_download.status == "queued"
        await download_service.mark_as_imported(test_download)

        result = await download_service.get_by_external_id(test_download.external_id)
        assert result.status == "Imported"

    @pytest.mark.asyncio
    async def test_queued_to_failed(
        self, download_service: DownloadService, test_download: Download
    ):
        """Test transitioning from queued to failed."""
        assert test_download.status == "queued"
        await download_service.mark_as_failed(test_download, "Test failure")

        result = await download_service.get_by_external_id(test_download.external_id)
        assert result.status == "Failed"

    @pytest.mark.asyncio
    async def test_multiple_downloads_same_downloader(
        self,
        download_service: DownloadService,
        test_downloader: Downloader,
        db_session: AsyncSession,
    ):
        """Test managing multiple downloads from the same downloader."""
        downloads = []
        for i in range(3):
            d = Download(
                guid=uuid.uuid4(),
                title=f"Download {i}",
                type="movie",
                downloader_id=test_downloader.guid,
                status="queued",
                external_id=f"nzo_multi_{i}",
            )
            db_session.add(d)
            downloads.append(d)
        await db_session.commit()

        # Mark one as imported, one as failed
        await download_service.mark_as_imported(downloads[0])
        await download_service.mark_as_failed(downloads[1])

        r0 = await download_service.get_by_external_id("nzo_multi_0")
        r1 = await download_service.get_by_external_id("nzo_multi_1")
        r2 = await download_service.get_by_external_id("nzo_multi_2")

        assert r0.status == "Imported"
        assert r1.status == "Failed"
        assert r2.status == "queued"


# ---------------------------------------------------------------------------
# blacklist_download
# ---------------------------------------------------------------------------


class TestBlacklistDownload:
    """Tests for blacklisting releases associated with failed downloads."""

    @pytest_asyncio.fixture
    async def download_with_release(
        self, db_session: AsyncSession, test_downloader: Downloader
    ):
        """Create a download linked to a release via MediaReleaseLink."""
        from streamarr.models.media import MediaItem, MediaRelease, MediaReleaseLink, MediaType

        media_item = MediaItem(
            guid=uuid.uuid4(),
            title="Test Movie",
            media_type=MediaType.MOVIES,
        )
        db_session.add(media_item)
        await db_session.flush()

        release = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="Test.Movie.2024.1080p",
            score=50,
        )
        db_session.add(release)
        await db_session.flush()

        link = MediaReleaseLink(
            guid=uuid.uuid4(),
            media_release_guid=release.guid,
            link="https://example.com/nzb",
            link_type="nzb",
        )
        db_session.add(link)
        await db_session.flush()

        download = Download(
            guid=uuid.uuid4(),
            title="Test.Movie.2024.1080p",
            type="movie",
            downloader_id=test_downloader.guid,
            status="Failed",
            external_id="nzo_blacklist_test",
            media_release_link_guid=link.guid,
        )
        db_session.add(download)
        await db_session.commit()
        return download, release

    @pytest.mark.asyncio
    async def test_blacklist_sets_reason(
        self,
        download_service: DownloadService,
        download_with_release,
        db_session: AsyncSession,
    ):
        download, release = download_with_release
        result = await download_service.blacklist_download(download, "Corrupt archive")
        assert result is True

        await db_session.refresh(release)
        assert release.blacklisted_reason == "Corrupt archive"

    @pytest.mark.asyncio
    async def test_blacklist_default_reason(
        self,
        download_service: DownloadService,
        download_with_release,
        db_session: AsyncSession,
    ):
        download, release = download_with_release
        result = await download_service.blacklist_download(download)
        assert result is True

        await db_session.refresh(release)
        assert release.blacklisted_reason == "Unknown failure"

    @pytest.mark.asyncio
    async def test_blacklist_already_blacklisted(
        self,
        download_service: DownloadService,
        download_with_release,
        db_session: AsyncSession,
    ):
        download, release = download_with_release
        release.blacklisted_reason = "Already blacklisted"
        db_session.add(release)
        await db_session.commit()

        result = await download_service.blacklist_download(download, "New reason")
        assert result is True
        # Should not overwrite existing reason
        await db_session.refresh(release)
        assert release.blacklisted_reason == "Already blacklisted"

    @pytest.mark.asyncio
    async def test_blacklist_no_release_link(
        self,
        download_service: DownloadService,
        test_downloader: Downloader,
        db_session: AsyncSession,
    ):
        download = Download(
            guid=uuid.uuid4(),
            title="Orphan Download",
            type="movie",
            downloader_id=test_downloader.guid,
            status="Failed",
            external_id="nzo_orphan",
        )
        db_session.add(download)
        await db_session.commit()

        result = await download_service.blacklist_download(download)
        assert result is False


# ---------------------------------------------------------------------------
# get_media_item_guid_for_download
# ---------------------------------------------------------------------------


class TestGetMediaItemGuid:
    """Tests for resolving media_item_guid from a download."""

    @pytest.mark.asyncio
    async def test_resolves_guid(
        self,
        download_service: DownloadService,
        db_session: AsyncSession,
        test_downloader: Downloader,
    ):
        from streamarr.models.media import MediaItem, MediaRelease, MediaReleaseLink, MediaType

        media_item = MediaItem(
            guid=uuid.uuid4(),
            title="Test",
            media_type=MediaType.MOVIES,
        )
        db_session.add(media_item)
        await db_session.flush()

        release = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="Test.Release",
            score=0,
        )
        db_session.add(release)
        await db_session.flush()

        link = MediaReleaseLink(
            guid=uuid.uuid4(),
            media_release_guid=release.guid,
            link="http://x",
            link_type="nzb",
        )
        db_session.add(link)
        await db_session.flush()

        download = Download(
            guid=uuid.uuid4(),
            title="Test.Release",
            type="movie",
            downloader_id=test_downloader.guid,
            status="queued",
            external_id="nzo_resolve_test",
            media_release_link_guid=link.guid,
        )
        db_session.add(download)
        await db_session.commit()

        result = await download_service.get_media_item_guid_for_download(download)
        assert result == media_item.guid

    @pytest.mark.asyncio
    async def test_returns_none_without_link(
        self,
        download_service: DownloadService,
        test_download: Download,
    ):
        result = await download_service.get_media_item_guid_for_download(test_download)
        assert result is None


# ---------------------------------------------------------------------------
# handle_completed_download
# ---------------------------------------------------------------------------


class TestHandleCompletedDownload:
    """Tests for handle_completed_download – path validation edge cases."""

    @pytest.mark.asyncio
    async def test_download_not_found(self, download_service: DownloadService):
        result = await download_service.handle_completed_download(
            external_id="nonexistent", path="/some/path"
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_path_does_not_exist(
        self,
        download_service: DownloadService,
        test_download: Download,
    ):
        result = await download_service.handle_completed_download(
            external_id=test_download.external_id,
            path="/nonexistent/path",
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_no_video_files(
        self,
        download_service: DownloadService,
        test_download: Download,
        tmp_path: Path,
    ):
        # Create directory with only non-video files
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "movie.nfo").write_text("info")

        result = await download_service.handle_completed_download(
            external_id=test_download.external_id,
            path=str(tmp_path),
        )
        assert result["success"] is False
