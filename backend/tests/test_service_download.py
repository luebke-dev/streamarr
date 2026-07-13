"""Tests for DownloadService – covers uncovered lines (151-156, 473-580)."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.services.download import DownloadService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_download(**overrides):
    defaults = dict(
        guid=uuid.uuid4(),
        external_id="ext-123",
        title="Test Movie",
        type="movie",
        status="queued",
        progress=0.0,
        downloader_id=uuid.uuid4(),
        media_release_link_guid=str(uuid.uuid4()),
    )
    defaults.update(overrides)
    d = MagicMock()
    for k, v in defaults.items():
        setattr(d, k, v)
    return d


def _make_downloader(**overrides):
    defaults = dict(
        guid=uuid.uuid4(),
        type="sabnzbd",
    )
    defaults.update(overrides)
    d = MagicMock()
    for k, v in defaults.items():
        setattr(d, k, v)
    return d


# ---------------------------------------------------------------------------
# extract_external_id_from_response (lines 151-156)
# ---------------------------------------------------------------------------


class TestExtractExternalId:
    @pytest.mark.asyncio
    async def test_extract_deluge_id(self, db_session: AsyncSession):
        """Deluge response extracts torrent_hash."""
        svc = DownloadService(db_session)
        downloader = _make_downloader(type="deluge")
        result = await svc.extract_external_id_from_response(
            downloader, {"torrent_hash": "abc123"}
        )
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_extract_deluge_no_hash(self, db_session: AsyncSession):
        """Deluge response without hash returns None."""
        svc = DownloadService(db_session)
        downloader = _make_downloader(type="deluge")
        result = await svc.extract_external_id_from_response(
            downloader, {}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_spotdl_id(self, db_session: AsyncSession):
        """Spotdl response extracts job_id."""
        svc = DownloadService(db_session)
        downloader = _make_downloader(type="spotdl")
        result = await svc.extract_external_id_from_response(
            downloader, {"job_id": "job-456"}
        )
        assert result == "job-456"

    @pytest.mark.asyncio
    async def test_extract_spotdl_no_job_id(self, db_session: AsyncSession):
        """Spotdl response without job_id returns None."""
        svc = DownloadService(db_session)
        downloader = _make_downloader(type="spotdl")
        result = await svc.extract_external_id_from_response(
            downloader, {}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_sabnzbd_id(self, db_session: AsyncSession):
        """SABnzbd response extracts first nzo_id."""
        svc = DownloadService(db_session)
        downloader = _make_downloader(type="sabnzbd")
        result = await svc.extract_external_id_from_response(
            downloader, {"nzo_ids": ["SABnzbd_nzo_123"]}
        )
        assert result == "SABnzbd_nzo_123"

    @pytest.mark.asyncio
    async def test_extract_sabnzbd_empty_nzo_ids(self, db_session: AsyncSession):
        """SABnzbd response with empty nzo_ids returns None."""
        svc = DownloadService(db_session)
        downloader = _make_downloader(type="sabnzbd")
        result = await svc.extract_external_id_from_response(
            downloader, {"nzo_ids": []}
        )
        assert result is None


# ---------------------------------------------------------------------------
# handle_completed_download (lines 473-580)
# ---------------------------------------------------------------------------


class TestHandleCompletedDownload:
    @pytest.mark.asyncio
    async def test_download_not_found(self, db_session: AsyncSession):
        """Returns error when download not found."""
        svc = DownloadService(db_session)
        with patch.object(svc, "get_by_external_id", return_value=None):
            result = await svc.handle_completed_download("ext-123", "/downloads/test")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_downloader_not_found(self, db_session: AsyncSession):
        """Returns error when downloader not found."""
        svc = DownloadService(db_session)
        download = _make_download()

        with patch.object(svc, "get_by_external_id", return_value=download):
            with patch.object(db_session, "get", return_value=None):
                result = await svc.handle_completed_download("ext-123", "/downloads/test")
        assert result["success"] is False
        assert "downloader" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_path_does_not_exist(self, db_session: AsyncSession):
        """Returns error and blacklists when path doesn't exist."""
        svc = DownloadService(db_session)
        download = _make_download()
        downloader = _make_downloader()

        with patch.object(svc, "get_by_external_id", return_value=download), \
             patch.object(db_session, "get", return_value=downloader), \
             patch.object(svc, "get_downloader_client", return_value=MagicMock()), \
             patch.object(svc, "mark_as_failed", new_callable=AsyncMock), \
             patch.object(svc, "blacklist_download", new_callable=AsyncMock), \
             patch.object(svc, "get_media_item_guid_for_download", new_callable=AsyncMock, return_value=uuid.uuid4()), \
             patch("streamarr.services.download.Path") as MockPath:
            MockPath.return_value.exists.return_value = False
            result = await svc.handle_completed_download("ext-123", "/nonexistent/path")

        assert result["success"] is False
        assert result["blacklisted"] is True

    @pytest.mark.asyncio
    async def test_no_valid_media_files(self, db_session: AsyncSession):
        """Returns error when no valid media files found."""
        svc = DownloadService(db_session)
        download = _make_download()
        downloader = _make_downloader()

        mock_release = MagicMock()
        mock_release.release_metadata = {}

        mock_media_item = MagicMock()
        mock_media_item.guid = uuid.uuid4()
        mock_media_item.media_type = "MOVIES"
        mock_media_item.external_ids = []
        mock_release.media_item = mock_media_item

        mock_release_link = MagicMock()
        mock_release_link.release = mock_release
        download.media_release_link = mock_release_link

        mock_folder = MagicMock()
        mock_folder.exists.return_value = True
        mock_folder.is_file.return_value = False
        mock_folder.rglob.return_value = []

        async def mock_refresh(obj, attribute_names=None):
            pass

        with patch.object(svc, "get_by_external_id", return_value=download), \
             patch.object(db_session, "get", return_value=downloader), \
             patch.object(svc, "get_downloader_client", return_value=MagicMock()), \
             patch.object(db_session, "refresh", side_effect=mock_refresh), \
             patch.object(svc, "mark_as_failed", new_callable=AsyncMock), \
             patch.object(svc, "blacklist_download", new_callable=AsyncMock), \
             patch("streamarr.services.download.Path", return_value=mock_folder):
            result = await svc.handle_completed_download("ext-123", "/downloads/test")

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_successful_import(self, db_session: AsyncSession):
        """Successful import marks as imported and fires hooks."""
        svc = DownloadService(db_session)
        download = _make_download()
        downloader = _make_downloader()

        mock_release = MagicMock()
        mock_release.release_metadata = {}

        mock_media_item = MagicMock()
        mock_media_item.guid = uuid.uuid4()
        mock_media_item.media_type = "MOVIES"
        mock_media_item.external_ids = []
        mock_release.media_item = mock_media_item

        mock_release_link = MagicMock()
        mock_release_link.release = mock_release
        download.media_release_link = mock_release_link

        mock_file = MagicMock(spec=Path)
        mock_file.is_file.return_value = True
        mock_file.suffix = ".mkv"
        mock_file.name = "movie.mkv"

        mock_folder = MagicMock()
        mock_folder.exists.return_value = True
        mock_folder.is_file.return_value = False
        mock_folder.iterdir.return_value = [mock_file]

        mock_plugin = MagicMock()
        mock_plugin.handle_completed_download = AsyncMock(return_value={
            "success": True,
            "files_imported": 1,
        })

        mock_client = MagicMock()
        mock_client.remove = AsyncMock()

        async def mock_refresh(obj, attribute_names=None):
            pass

        def mock_path(value):
            if value == "/downloads/test":
                return mock_folder
            return Path(value)

        with patch.object(svc, "get_by_external_id", return_value=download), \
             patch.object(db_session, "get", return_value=downloader), \
             patch.object(svc, "get_downloader_client", return_value=mock_client), \
             patch.object(db_session, "refresh", side_effect=mock_refresh), \
             patch.object(svc, "mark_as_imported", new_callable=AsyncMock), \
             patch.object(svc, "is_valid_media_file", return_value=True), \
             patch("streamarr.services.download.Path", side_effect=mock_path), \
             patch("streamarr.services.download.get_plugin_instance", return_value=mock_plugin):
            result = await svc.handle_completed_download("ext-123", "/downloads/test")

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_import_failure_blacklists(self, db_session: AsyncSession):
        """Failed import blacklists the release."""
        svc = DownloadService(db_session)
        download = _make_download()
        downloader = _make_downloader()

        mock_release = MagicMock()
        mock_release.release_metadata = {}

        mock_media_item = MagicMock()
        mock_media_item.guid = uuid.uuid4()
        mock_media_item.media_type = "MOVIES"
        mock_media_item.external_ids = []
        mock_release.media_item = mock_media_item

        mock_release_link = MagicMock()
        mock_release_link.release = mock_release
        download.media_release_link = mock_release_link

        mock_file = MagicMock(spec=Path)
        mock_file.is_file.return_value = True
        mock_file.suffix = ".mkv"
        mock_file.name = "movie.mkv"

        mock_folder = MagicMock()
        mock_folder.exists.return_value = True
        mock_folder.is_file.return_value = False
        mock_folder.rglob.return_value = [mock_file]

        mock_plugin = MagicMock()
        mock_plugin.handle_completed_download = AsyncMock(return_value={
            "success": False,
            "error": "Import failed: bad file",
        })

        async def mock_refresh(obj, attribute_names=None):
            pass

        with patch.object(svc, "get_by_external_id", return_value=download), \
             patch.object(db_session, "get", return_value=downloader), \
             patch.object(svc, "get_downloader_client", return_value=MagicMock()), \
             patch.object(db_session, "refresh", side_effect=mock_refresh), \
             patch.object(svc, "mark_as_failed", new_callable=AsyncMock), \
             patch.object(svc, "blacklist_download", new_callable=AsyncMock), \
             patch.object(svc, "get_media_item_guid_for_download", new_callable=AsyncMock, return_value=uuid.uuid4()), \
             patch.object(svc, "is_valid_media_file", return_value=True), \
             patch("streamarr.services.download.Path", return_value=mock_folder), \
             patch("streamarr.services.download.get_plugin_instance", return_value=mock_plugin):
            result = await svc.handle_completed_download("ext-123", "/downloads/test")

        assert result["success"] is False
        assert result["blacklisted"] is True


# ---------------------------------------------------------------------------
# is_valid_media_file
# ---------------------------------------------------------------------------


class TestIsValidMediaFile:
    def test_valid_video_file(self, db_session: AsyncSession, tmp_path: Path):
        """Valid .mkv file is accepted."""
        svc = DownloadService(db_session)
        f = tmp_path / "movie.mkv"
        f.write_bytes(b"data")
        assert svc.is_valid_video_file(f) is True

    def test_sample_file_rejected(self, db_session: AsyncSession, tmp_path: Path):
        """Files with 'sample' in name are rejected."""
        svc = DownloadService(db_session)
        f = tmp_path / "sample-movie.mkv"
        f.write_bytes(b"data")
        assert svc.is_valid_video_file(f) is False

    def test_wrong_extension_rejected(self, db_session: AsyncSession, tmp_path: Path):
        """Non-video extensions are rejected."""
        svc = DownloadService(db_session)
        f = tmp_path / "readme.txt"
        f.write_bytes(b"data")
        assert svc.is_valid_video_file(f) is False

    def test_directory_rejected(self, db_session: AsyncSession, tmp_path: Path):
        """Directories are rejected."""
        svc = DownloadService(db_session)
        d = tmp_path / "subdir"
        d.mkdir()
        assert svc.is_valid_video_file(d) is False

    def test_valid_audio_file(self, db_session: AsyncSession, tmp_path: Path):
        """Valid .mp3 file is accepted."""
        svc = DownloadService(db_session)
        f = tmp_path / "track.mp3"
        f.write_bytes(b"data")
        assert svc.is_valid_audio_file(f) is True

    def test_is_valid_media_file_music(self, db_session: AsyncSession, tmp_path: Path):
        """Music type uses audio validation."""
        svc = DownloadService(db_session)
        f = tmp_path / "track.flac"
        f.write_bytes(b"data")
        with patch("streamarr.services.download.get_library_type_for_media_item_type", return_value="MUSIC"):
            assert svc.is_valid_media_file(f, "SONGS") is True

    def test_is_valid_media_file_video(self, db_session: AsyncSession, tmp_path: Path):
        """Non-music type uses video validation."""
        svc = DownloadService(db_session)
        f = tmp_path / "movie.mkv"
        f.write_bytes(b"data")
        with patch("streamarr.services.download.get_library_type_for_media_item_type", return_value="MOVIES"):
            assert svc.is_valid_media_file(f, "MOVIES") is True
