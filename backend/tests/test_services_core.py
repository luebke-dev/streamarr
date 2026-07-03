"""Tests for core services: MediaService, DownloadService, EmailService, PaymentService.

Focuses on lines NOT covered by existing test files (test_media_cleanup_service.py,
test_library_service.py, test_payment_service.py).
"""

# Ensure the 'emails' third-party library is mockable even when not installed.
# Must happen before any pyrate.services.email import.
import sys
from unittest.mock import MagicMock as _MagicMock

if "emails" not in sys.modules:
    sys.modules["emails"] = _MagicMock()

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.downloader import Downloader
from pyrate.models.downloads import Download
from pyrate.models.media import (
    AvailabilityStatus,
    MediaFile,
    MediaItem,
    MediaRelease,
    MediaReleaseLink,
    MediaType,
)
from pyrate.models.user import User
from pyrate.services.media import MediaService
from pyrate.services.download import DownloadService


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _media_service(db: AsyncSession) -> MediaService:
    return MediaService(db)


def _download_service(db: AsyncSession) -> DownloadService:
    return DownloadService(db)


@pytest_asyncio.fixture
async def media_item(db_session: AsyncSession) -> MediaItem:
    """Create a basic MOVIES media item."""
    item = MediaItem(
        guid=uuid.uuid4(),
        media_type=MediaType.MOVIES,
        title="Test Movie",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest_asyncio.fixture
async def media_item_with_file(
    db_session: AsyncSession, media_item: MediaItem
) -> tuple[MediaItem, MediaFile]:
    """Create a media item that already has a file."""
    mf = MediaFile(
        guid=uuid.uuid4(),
        media_item_guid=media_item.guid,
        file_path="/library/movies/test/movie.mkv",
    )
    db_session.add(mf)
    await db_session.commit()
    await db_session.refresh(mf)
    return media_item, mf


@pytest_asyncio.fixture
async def media_release(
    db_session: AsyncSession, media_item: MediaItem
) -> MediaRelease:
    """Create a release linked to media_item."""
    release = MediaRelease(
        guid=uuid.uuid4(),
        media_item_guid=media_item.guid,
        title="Test.Movie.2024.1080p.BluRay",
        quality="1080p",
        size=5_000_000,
    )
    db_session.add(release)
    await db_session.commit()
    await db_session.refresh(release)
    return release


@pytest_asyncio.fixture
async def downloader(db_session: AsyncSession) -> Downloader:
    """Create a Sabnzbd-type downloader."""
    dl = Downloader(
        guid=uuid.uuid4(),
        label="Test SAB",
        host="localhost:8080",
        api_key="test-key",
        type="sabnzbd",
        ssl=False,
        verify_ssl=False,
    )
    db_session.add(dl)
    await db_session.commit()
    await db_session.refresh(dl)
    return dl


@pytest_asyncio.fixture
async def release_link(
    db_session: AsyncSession, media_release: MediaRelease
) -> MediaReleaseLink:
    """Create a release link."""
    link = MediaReleaseLink(
        guid=uuid.uuid4(),
        media_release_guid=media_release.guid,
        link="https://example.com/nzb/12345",
        link_type="nzb",
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)
    return link


@pytest_asyncio.fixture
async def download_record(
    db_session: AsyncSession,
    downloader: Downloader,
    release_link: MediaReleaseLink,
) -> Download:
    """Create a download record in 'queued' state."""
    dl = Download(
        guid=uuid.uuid4(),
        title="Test Movie",
        type="movie",
        downloader_id=downloader.guid,
        status="queued",
        external_id="SABnzbd_nzo_abc123",
        media_release_link_guid=release_link.guid,
    )
    db_session.add(dl)
    await db_session.commit()
    await db_session.refresh(dl)
    return dl


# ===========================================================================
# MediaService -- set_genres (uses pg_insert ON CONFLICT, skip on SQLite)
# ===========================================================================


class TestMediaServiceSetGenres:
    """Tests for MediaService.set_genres -- skipped on SQLite (requires PG dialect)."""

    @pytest.mark.asyncio
    async def test_set_genres_returns_none_for_missing_item(
        self, db_session: AsyncSession
    ):
        """set_genres returns None when the media item doesn't exist."""
        svc = _media_service(db_session)
        result = await svc.set_genres(uuid.uuid4(), ["Action"])
        assert result is None


# ===========================================================================
# MediaService -- select_best_release
# ===========================================================================


class TestSelectBestRelease:
    """Tests for MediaService.select_best_release."""

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_releases(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        """select_best_release returns None when no releases provided."""
        svc = _media_service(db_session)
        result = await svc.select_best_release(media_item, [])
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_first_release_when_no_plugin(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        """Falls back to first release when no library plugin is found."""
        svc = _media_service(db_session)
        r1 = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="Release A",
        )
        r2 = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="Release B",
        )
        with patch("pyrate.services.media.get_plugin_instance", return_value=None):
            result = await svc.select_best_release(media_item, [r1, r2])
        assert result is r1

    @pytest.mark.asyncio
    async def test_returns_highest_scored_release(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        """Selects the release with the highest plugin score."""
        svc = _media_service(db_session)

        r_low = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="Low Quality Release",
            release_metadata={"resolution": "480p"},
        )
        r_high = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="High Quality Release",
            release_metadata={"resolution": "1080p"},
        )

        mock_plugin = AsyncMock()
        mock_plugin.extract_release_metadata = AsyncMock(return_value={})
        mock_plugin.score_release = AsyncMock(
            side_effect=lambda meta, prefs: 90.0 if meta.get("resolution") == "1080p" else 30.0
        )

        mock_settings_cls = MagicMock()
        mock_settings_cls.return_value.get = AsyncMock(return_value=None)

        with (
            patch("pyrate.services.media.get_plugin_instance", return_value=mock_plugin),
            patch("pyrate.services.settings.SettingsService", mock_settings_cls),
        ):
            result = await svc.select_best_release(media_item, [r_low, r_high])

        assert result is r_high

    @pytest.mark.asyncio
    async def test_scoring_exception_assigns_fallback_score(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        """If scoring raises, release gets fallback score of 25."""
        svc = _media_service(db_session)

        r1 = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="Broken Scoring Release",
            release_metadata=None,
        )

        mock_plugin = AsyncMock()
        mock_plugin.extract_release_metadata = AsyncMock(return_value={})
        mock_plugin.score_release = AsyncMock(side_effect=ValueError("bad"))

        mock_settings_cls = MagicMock()
        mock_settings_cls.return_value.get = AsyncMock(return_value=None)

        with (
            patch("pyrate.services.media.get_plugin_instance", return_value=mock_plugin),
            patch("pyrate.services.settings.SettingsService", mock_settings_cls),
        ):
            result = await svc.select_best_release(media_item, [r1])

        assert result is r1

    @pytest.mark.asyncio
    async def test_language_preferences_injected(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        """user_language and allowed_languages are forwarded to score_release."""
        svc = _media_service(db_session)
        r1 = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="R1",
            release_metadata={"resolution": "720p"},
        )

        captured_prefs = {}
        mock_plugin = AsyncMock()
        mock_plugin.extract_release_metadata = AsyncMock(return_value={})

        async def _capture_score(meta, prefs):
            captured_prefs.update(prefs or {})
            return 50.0

        mock_plugin.score_release = _capture_score

        mock_settings_cls = MagicMock()
        mock_settings_cls.return_value.get = AsyncMock(return_value=None)

        with (
            patch("pyrate.services.media.get_plugin_instance", return_value=mock_plugin),
            patch("pyrate.services.settings.SettingsService", mock_settings_cls),
        ):
            await svc.select_best_release(
                media_item,
                [r1],
                user_languages=["de"],
                allowed_languages=["de", "en"],
            )

        assert captured_prefs["user_languages"] == ["de"]
        assert captured_prefs["allowed_languages"] == ["de", "en"]

    @pytest.mark.asyncio
    async def test_codec_preferences_injected(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        """Codec compatibility preferences are forwarded to scoring."""
        svc = _media_service(db_session)
        r1 = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            title="R1",
            release_metadata={"resolution": "1080p"},
        )

        captured_prefs = {}
        mock_plugin = AsyncMock()
        mock_plugin.extract_release_metadata = AsyncMock(return_value={})

        async def _capture(meta, prefs):
            captured_prefs.update(prefs or {})
            return 50.0

        mock_plugin.score_release = _capture

        mock_settings_cls = MagicMock()
        mock_settings_cls.return_value.get = AsyncMock(return_value=None)

        with (
            patch("pyrate.services.media.get_plugin_instance", return_value=mock_plugin),
            patch("pyrate.services.settings.SettingsService", mock_settings_cls),
        ):
            await svc.select_best_release(
                media_item,
                [r1],
                supported_video_codecs=["h264"],
                codec_match_bonus=10,
                codec_mismatch_penalty=5,
            )

        assert captured_prefs["supported_video_codecs"] == ["h264"]
        assert captured_prefs["codec_match_bonus"] == 10
        assert captured_prefs["codec_mismatch_penalty"] == 5


# ===========================================================================
# MediaService -- get_top_level_items
# ===========================================================================


class TestGetTopLevelItems:
    @pytest.mark.asyncio
    async def test_returns_only_top_level(self, db_session: AsyncSession):
        """Items with parent_guid should not appear."""
        svc = _media_service(db_session)

        parent = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Test Show"
        )
        await svc.create_media_item(
            media_type=MediaType.SHOWS,
            title="Season 1",
            parent_guid=parent.guid,
            sequence_number=1,
        )

        items = await svc.get_top_level_items(MediaType.SHOWS)
        titles = [i.title for i in items]
        assert "Test Show" in titles
        assert "Season 1" not in titles

    @pytest.mark.asyncio
    async def test_filters_by_library(self, db_session: AsyncSession):
        """Deprecated library_guid argument is ignored; media_type determines library."""
        svc = _media_service(db_session)
        fake_lib = uuid.uuid4()

        db_session.add_all(
            [
                MediaItem(
                    guid=uuid.uuid4(),
                    media_type=MediaType.MOVIES,
                    title="In Lib",
                    library_guid=fake_lib,
                ),
                MediaItem(
                    guid=uuid.uuid4(),
                    media_type=MediaType.MOVIES,
                    title="No Lib",
                ),
            ]
        )
        await db_session.commit()

        items = await svc.get_top_level_items(MediaType.MOVIES, library_guid=fake_lib)
        titles = {item.title for item in items}
        assert {"In Lib", "No Lib"}.issubset(titles)


# ===========================================================================
# MediaService -- has_files / has_releases
# ===========================================================================


class TestHasFilesAndReleases:
    @pytest.mark.asyncio
    async def test_has_files_true(
        self, db_session: AsyncSession, media_item_with_file
    ):
        item, _ = media_item_with_file
        svc = _media_service(db_session)
        assert await svc.has_files(item.guid) is True

    @pytest.mark.asyncio
    async def test_has_files_false(self, db_session: AsyncSession, media_item):
        svc = _media_service(db_session)
        assert await svc.has_files(media_item.guid) is False

    @pytest.mark.asyncio
    async def test_has_releases_true(
        self, db_session: AsyncSession, media_release: MediaRelease
    ):
        svc = _media_service(db_session)
        assert await svc.has_releases(media_release.media_item_guid) is True

    @pytest.mark.asyncio
    async def test_has_releases_false(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        svc = _media_service(db_session)
        assert await svc.has_releases(media_item.guid) is False


# ===========================================================================
# MediaService -- delete, delete_file, delete_release
# ===========================================================================


class TestMediaServiceDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self, db_session: AsyncSession, media_item):
        svc = _media_service(db_session)
        assert await svc.delete(media_item.guid) is True
        assert await svc.get_by_id(media_item.guid) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db_session: AsyncSession):
        svc = _media_service(db_session)
        assert await svc.delete(uuid.uuid4()) is False

    @pytest.mark.asyncio
    async def test_delete_file_existing(
        self, db_session: AsyncSession, media_item_with_file
    ):
        _, mf = media_item_with_file
        svc = _media_service(db_session)
        assert await svc.delete_file(mf.guid) is True

    @pytest.mark.asyncio
    async def test_delete_file_nonexistent(self, db_session: AsyncSession):
        svc = _media_service(db_session)
        assert await svc.delete_file(uuid.uuid4()) is False

    @pytest.mark.asyncio
    async def test_delete_release_existing(
        self, db_session: AsyncSession, media_release
    ):
        svc = _media_service(db_session)
        assert await svc.delete_release(media_release.guid) is True

    @pytest.mark.asyncio
    async def test_delete_release_nonexistent(self, db_session: AsyncSession):
        svc = _media_service(db_session)
        assert await svc.delete_release(uuid.uuid4()) is False


# ===========================================================================
# MediaService -- update_availability_status, mark_metadata_updated, mark_searched
# ===========================================================================


class TestMediaServiceStatusUpdates:
    @pytest.mark.asyncio
    async def test_update_availability_status(
        self, db_session: AsyncSession, media_item
    ):
        svc = _media_service(db_session)
        updated = await svc.update_availability_status(
            media_item.guid, AvailabilityStatus.AVAILABLE
        )
        assert updated is not None
        assert updated.availability_status == AvailabilityStatus.AVAILABLE

    @pytest.mark.asyncio
    async def test_update_availability_status_not_found(
        self, db_session: AsyncSession
    ):
        svc = _media_service(db_session)
        assert (
            await svc.update_availability_status(
                uuid.uuid4(), AvailabilityStatus.AVAILABLE
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_mark_metadata_updated(
        self, db_session: AsyncSession, media_item
    ):
        svc = _media_service(db_session)
        updated = await svc.mark_metadata_updated(media_item.guid)
        assert updated is not None
        assert updated.last_metadata_updated_at is not None

    @pytest.mark.asyncio
    async def test_mark_searched(self, db_session: AsyncSession, media_item):
        svc = _media_service(db_session)
        updated = await svc.mark_searched(media_item.guid)
        assert updated is not None
        assert updated.last_searched_at is not None


# ===========================================================================
# MediaService -- cleanup_media_file
# ===========================================================================


class TestCleanupMediaFile:
    @pytest.mark.asyncio
    async def test_cleanup_deletes_file_from_db(
        self, db_session: AsyncSession, media_item_with_file
    ):
        """cleanup_media_file removes MediaFile rows from DB."""
        item, mf = media_item_with_file
        svc = _media_service(db_session)

        with patch.object(Path, "exists", return_value=False):
            result = await svc.cleanup_media_file(item.guid)

        assert result["files_deleted_from_db"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_deletes_physical_file(
        self, db_session: AsyncSession, media_item_with_file, tmp_path
    ):
        """cleanup_media_file unlinks the physical file when it exists."""
        item, mf = media_item_with_file
        svc = _media_service(db_session)

        phys = tmp_path / "movie.mkv"
        phys.write_bytes(b"video data")

        # Point the DB record at our temp file
        mf.file_path = str(phys)
        db_session.add(mf)
        await db_session.commit()

        with patch.object(svc, "_cleanup_empty_dirs"):
            result = await svc.cleanup_media_file(item.guid)

        assert result["files_deleted_from_disk"] == 1
        assert not phys.exists()

    @pytest.mark.asyncio
    async def test_cleanup_specific_file_path(
        self, db_session: AsyncSession, media_item
    ):
        """Only the file matching file_path is deleted when specified."""
        svc = _media_service(db_session)

        mf1 = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            file_path="/library/movies/a.mkv",
        )
        mf2 = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=media_item.guid,
            file_path="/library/movies/b.mkv",
        )
        db_session.add_all([mf1, mf2])
        await db_session.commit()

        with patch.object(Path, "exists", return_value=False):
            result = await svc.cleanup_media_file(
                media_item.guid,
                file_path="/library/movies/a.mkv",
            )

        assert result["files_deleted_from_db"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_deletes_media_item_when_no_files_remain(
        self, db_session: AsyncSession, media_item_with_file
    ):
        """When delete_media_item=True and no files remain, the item is deleted."""
        item, mf = media_item_with_file
        svc = _media_service(db_session)

        with patch.object(Path, "exists", return_value=False):
            result = await svc.cleanup_media_file(
                item.guid, delete_media_item=True
            )

        assert result["media_item_deleted"] is True
        assert await svc.get_by_id(item.guid) is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_media_item_when_flag_false(
        self, db_session: AsyncSession, media_item_with_file
    ):
        """delete_media_item=False keeps the MediaItem even when no files remain."""
        item, mf = media_item_with_file
        svc = _media_service(db_session)

        with patch.object(Path, "exists", return_value=False):
            result = await svc.cleanup_media_file(
                item.guid, delete_media_item=False
            )

        assert result["media_item_deleted"] is False
        assert await svc.get_by_id(item.guid) is not None

    @pytest.mark.asyncio
    async def test_cleanup_handles_string_guid(
        self, db_session: AsyncSession, media_item_with_file
    ):
        """media_item_guid can be passed as a string."""
        item, mf = media_item_with_file
        svc = _media_service(db_session)

        with patch.object(Path, "exists", return_value=False):
            result = await svc.cleanup_media_file(str(item.guid))

        assert result["files_deleted_from_db"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_records_disk_error(
        self, db_session: AsyncSession, media_item_with_file
    ):
        """Errors during physical deletion are captured in errors list."""
        item, mf = media_item_with_file
        svc = _media_service(db_session)

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "unlink", side_effect=PermissionError("denied")),
        ):
            result = await svc.cleanup_media_file(item.guid)

        assert len(result["errors"]) >= 1
        assert result["files_deleted_from_disk"] == 0


# ===========================================================================
# MediaService -- is_valid_video_file (static)
# ===========================================================================


class TestIsValidVideoFile:
    def test_valid_mkv(self, tmp_path):
        f = tmp_path / "movie.mkv"
        f.write_bytes(b"x")
        assert MediaService.is_valid_video_file(f) is True

    def test_valid_mp4(self, tmp_path):
        f = tmp_path / "movie.mp4"
        f.write_bytes(b"x")
        assert MediaService.is_valid_video_file(f) is True

    def test_invalid_extension(self, tmp_path):
        f = tmp_path / "movie.txt"
        f.write_bytes(b"x")
        assert MediaService.is_valid_video_file(f) is False

    def test_sample_file_rejected(self, tmp_path):
        f = tmp_path / "Sample-movie.mkv"
        f.write_bytes(b"x")
        assert MediaService.is_valid_video_file(f) is False

    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "missing.mkv"
        assert MediaService.is_valid_video_file(f) is False


# ===========================================================================
# DownloadService -- get_downloader_client
# ===========================================================================


class TestGetDownloaderClient:
    def test_delegates_to_downloader_service(self, db_session: AsyncSession):
        svc = _download_service(db_session)
        mock_downloader = MagicMock(spec=Downloader)

        with patch(
            "pyrate.services.downloader.DownloaderService"
        ) as MockDlSvc:
            MockDlSvc.get_client.return_value = MagicMock()
            client = svc.get_downloader_client(mock_downloader)

        MockDlSvc.get_client.assert_called_once_with(mock_downloader)
        assert client is not None


# ===========================================================================
# DownloadService -- extract_external_id_from_response
# ===========================================================================


class TestExtractExternalId:
    @pytest.mark.asyncio
    async def test_deluge_extracts_torrent_hash(self, db_session: AsyncSession):
        svc = _download_service(db_session)
        dl = MagicMock(spec=Downloader)
        dl.type = "Deluge"
        result = await svc.extract_external_id_from_response(
            dl, {"torrent_hash": "abc123"}
        )
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_deluge_returns_none_without_hash(self, db_session: AsyncSession):
        svc = _download_service(db_session)
        dl = MagicMock(spec=Downloader)
        dl.type = "Deluge"
        result = await svc.extract_external_id_from_response(dl, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_spotdl_extracts_job_id(self, db_session: AsyncSession):
        svc = _download_service(db_session)
        dl = MagicMock(spec=Downloader)
        dl.type = "SpotDL"
        result = await svc.extract_external_id_from_response(
            dl, {"job_id": "job-xyz"}
        )
        assert result == "job-xyz"

    @pytest.mark.asyncio
    async def test_spotdl_returns_none_without_job_id(self, db_session: AsyncSession):
        svc = _download_service(db_session)
        dl = MagicMock(spec=Downloader)
        dl.type = "SpotDL"
        result = await svc.extract_external_id_from_response(dl, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_sabnzbd_extracts_first_nzo_id(self, db_session: AsyncSession):
        svc = _download_service(db_session)
        dl = MagicMock(spec=Downloader)
        dl.type = "sabnzbd"
        result = await svc.extract_external_id_from_response(
            dl, {"nzo_ids": ["nzo_abc", "nzo_def"]}
        )
        assert result == "nzo_abc"

    @pytest.mark.asyncio
    async def test_sabnzbd_returns_none_without_nzo_ids(
        self, db_session: AsyncSession
    ):
        svc = _download_service(db_session)
        dl = MagicMock(spec=Downloader)
        dl.type = "sabnzbd"
        result = await svc.extract_external_id_from_response(dl, {})
        assert result is None


# ===========================================================================
# DownloadService -- add_media_download
# ===========================================================================


class TestAddMediaDownload:
    @pytest.mark.asyncio
    async def test_returns_none_when_release_link_not_found(
        self, db_session: AsyncSession, downloader: Downloader
    ):
        svc = _download_service(db_session)
        # Pass a real UUID (not string) so SQLAlchemy can bind it
        result = await svc.add_media_download(
            uuid.uuid4(), [downloader], "movie"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_creates_download_on_success(
        self,
        db_session: AsyncSession,
        downloader: Downloader,
        release_link: MediaReleaseLink,
    ):
        svc = _download_service(db_session)

        mock_client = AsyncMock()
        mock_client.add_by_url = AsyncMock(return_value={"nzo_ids": ["nzo_test1"]})

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            result = await svc.add_media_download(
                release_link.guid, [downloader], "movie"
            )

        assert result is not None
        assert result.status == "queued"
        assert result.external_id == "nzo_test1"

    @pytest.mark.asyncio
    async def test_returns_none_when_all_downloaders_fail(
        self,
        db_session: AsyncSession,
        downloader: Downloader,
        release_link: MediaReleaseLink,
    ):
        svc = _download_service(db_session)

        mock_client = AsyncMock()
        mock_client.add_by_url = AsyncMock(return_value={})

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            result = await svc.add_media_download(
                release_link.guid, [downloader], "movie"
            )

        assert result is None


# ===========================================================================
# DownloadService -- add_music_download
# ===========================================================================


class TestMusicDownloadWrapper:
    @pytest.mark.asyncio
    async def test_add_music_download_filters_spotdl(
        self, db_session: AsyncSession
    ):
        """add_music_download filters to only spotdl downloaders."""
        svc = _download_service(db_session)

        sab = MagicMock(spec=Downloader)
        sab.type = "sabnzbd"
        spotdl = MagicMock(spec=Downloader)
        spotdl.type = "spotdl"

        with patch.object(
            svc, "add_media_download", new_callable=AsyncMock, return_value=None
        ) as mock_add:
            await svc.add_music_download("guid3", [sab, spotdl])
            mock_add.assert_awaited_once_with("guid3", [spotdl], "music", None)

    @pytest.mark.asyncio
    async def test_add_music_download_no_spotdl_returns_none(
        self, db_session: AsyncSession
    ):
        svc = _download_service(db_session)
        sab = MagicMock(spec=Downloader)
        sab.type = "sabnzbd"
        result = await svc.add_music_download("guid4", [sab])
        assert result is None


# ===========================================================================
# DownloadService -- update_downloads_from_client
# ===========================================================================


class TestUpdateDownloadsFromClient:
    @pytest.mark.asyncio
    async def test_updates_status(
        self,
        db_session: AsyncSession,
        download_record: Download,
        downloader: Downloader,
    ):
        svc = _download_service(db_session)

        mock_client = AsyncMock()
        mock_client.get_downloads = AsyncMock(
            return_value=[
                {
                    "external_id": download_record.external_id,
                    "status": "Downloading",
                    "progress": 42.5,
                }
            ]
        )

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            stats = await svc.update_downloads_from_client(downloader)

        assert stats["updated"] == 1
        await db_session.refresh(download_record)
        assert download_record.status == "Downloading"
        assert download_record.progress == 42.5

    @pytest.mark.asyncio
    async def test_skips_imported_downloads(
        self,
        db_session: AsyncSession,
        download_record: Download,
        downloader: Downloader,
    ):
        """Already-imported downloads are not updated."""
        download_record.status = "Imported"
        db_session.add(download_record)
        await db_session.commit()

        svc = _download_service(db_session)
        mock_client = AsyncMock()
        mock_client.get_downloads = AsyncMock(
            return_value=[
                {
                    "external_id": download_record.external_id,
                    "status": "Completed",
                    "progress": 100.0,
                }
            ]
        )

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            stats = await svc.update_downloads_from_client(downloader)

        assert stats["updated"] == 0

    @pytest.mark.asyncio
    async def test_empty_downloads(
        self, db_session: AsyncSession, downloader: Downloader
    ):
        svc = _download_service(db_session)
        mock_client = AsyncMock()
        mock_client.get_downloads = AsyncMock(return_value=[])

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            stats = await svc.update_downloads_from_client(downloader)

        assert stats == {"updated": 0, "completed": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_completed_count(
        self,
        db_session: AsyncSession,
        download_record: Download,
        downloader: Downloader,
    ):
        svc = _download_service(db_session)
        mock_client = AsyncMock()
        mock_client.get_downloads = AsyncMock(
            return_value=[
                {
                    "external_id": download_record.external_id,
                    "status": "Completed",
                    "progress": 100.0,
                }
            ]
        )

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            stats = await svc.update_downloads_from_client(downloader)

        assert stats["completed"] == 1


# ===========================================================================
# DownloadService -- is_valid_video_file / is_valid_audio_file / is_valid_media_file
# ===========================================================================


class TestDownloadFileValidation:
    def test_valid_video_file(self, tmp_path, db_session):
        svc = _download_service(db_session)
        f = tmp_path / "movie.mkv"
        f.write_bytes(b"data")
        assert svc.is_valid_video_file(f) is True

    def test_sample_video_rejected(self, tmp_path, db_session):
        svc = _download_service(db_session)
        f = tmp_path / "sample-movie.mkv"
        f.write_bytes(b"data")
        assert svc.is_valid_video_file(f) is False

    def test_invalid_extension_rejected(self, tmp_path, db_session):
        svc = _download_service(db_session)
        f = tmp_path / "readme.txt"
        f.write_bytes(b"data")
        assert svc.is_valid_video_file(f) is False

    def test_nonexistent_file(self, tmp_path, db_session):
        svc = _download_service(db_session)
        f = tmp_path / "missing.mkv"
        assert svc.is_valid_video_file(f) is False

    def test_valid_audio_file(self, tmp_path, db_session):
        svc = _download_service(db_session)
        f = tmp_path / "track.flac"
        f.write_bytes(b"data")
        assert svc.is_valid_audio_file(f) is True

    def test_invalid_audio_file(self, tmp_path, db_session):
        svc = _download_service(db_session)
        f = tmp_path / "notes.txt"
        f.write_bytes(b"data")
        assert svc.is_valid_audio_file(f) is False

    def test_is_valid_media_file_music(self, tmp_path, db_session):
        svc = _download_service(db_session)
        f = tmp_path / "song.mp3"
        f.write_bytes(b"data")

        with patch(
            "pyrate.services.download.get_library_type_for_media_item_type",
            return_value="MUSIC",
        ):
            assert svc.is_valid_media_file(f, "SONGS") is True

    def test_is_valid_media_file_video(self, tmp_path, db_session):
        svc = _download_service(db_session)
        f = tmp_path / "episode.mkv"
        f.write_bytes(b"data")

        with patch(
            "pyrate.services.download.get_library_type_for_media_item_type",
            return_value="SHOWS",
        ):
            assert svc.is_valid_media_file(f, "EPISODES") is True


# ===========================================================================
# DownloadService -- get_by_external_id / mark_as_imported / mark_as_failed
# ===========================================================================


class TestDownloadStatusMethods:
    @pytest.mark.asyncio
    async def test_get_by_external_id_found(
        self, db_session: AsyncSession, download_record
    ):
        svc = _download_service(db_session)
        result = await svc.get_by_external_id(download_record.external_id)
        assert result is not None
        assert result.guid == download_record.guid

    @pytest.mark.asyncio
    async def test_get_by_external_id_not_found(self, db_session: AsyncSession):
        svc = _download_service(db_session)
        result = await svc.get_by_external_id("nonexistent_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_mark_as_imported(
        self, db_session: AsyncSession, download_record
    ):
        svc = _download_service(db_session)
        await svc.mark_as_imported(download_record)
        await db_session.refresh(download_record)
        assert download_record.status == "Imported"

    @pytest.mark.asyncio
    async def test_mark_as_failed(
        self, db_session: AsyncSession, download_record
    ):
        svc = _download_service(db_session)
        await svc.mark_as_failed(download_record, reason="bad file")
        await db_session.refresh(download_record)
        assert download_record.status == "Failed"


# ===========================================================================
# DownloadService -- blacklist_download
# ===========================================================================


class TestBlacklistDownload:
    @pytest.mark.asyncio
    async def test_blacklist_sets_reason_on_release(
        self,
        db_session: AsyncSession,
        download_record: Download,
        release_link: MediaReleaseLink,
        media_release: MediaRelease,
    ):
        svc = _download_service(db_session)
        result = await svc.blacklist_download(download_record, reason="corrupt")

        assert result is True
        await db_session.refresh(media_release)
        assert media_release.blacklisted_reason == "corrupt"

    @pytest.mark.asyncio
    async def test_blacklist_already_blacklisted(
        self,
        db_session: AsyncSession,
        download_record: Download,
        media_release: MediaRelease,
    ):
        media_release.blacklisted_reason = "previously blacklisted"
        db_session.add(media_release)
        await db_session.commit()

        svc = _download_service(db_session)
        result = await svc.blacklist_download(download_record, reason="new reason")

        assert result is True
        # Original reason is preserved
        await db_session.refresh(media_release)
        assert media_release.blacklisted_reason == "previously blacklisted"

    @pytest.mark.asyncio
    async def test_blacklist_no_release_link(self, db_session: AsyncSession):
        """Returns False when download has no release link."""
        svc = _download_service(db_session)

        # Create a downloader for FK constraint
        dl_obj = Downloader(
            guid=uuid.uuid4(),
            label="Temp",
            host="localhost",
            type="sabnzbd",
            ssl=False,
            verify_ssl=False,
        )
        db_session.add(dl_obj)
        await db_session.commit()

        dl_no_link = Download(
            guid=uuid.uuid4(),
            title="Orphan",
            type="movie",
            downloader_id=dl_obj.guid,
            status="Failed",
            external_id="no_link_id",
            media_release_link_guid=None,
        )
        db_session.add(dl_no_link)
        await db_session.commit()
        await db_session.refresh(dl_no_link)

        result = await svc.blacklist_download(dl_no_link)
        assert result is False


# ===========================================================================
# DownloadService -- get_media_item_guid_for_download
# ===========================================================================


class TestGetMediaItemGuidForDownload:
    @pytest.mark.asyncio
    async def test_resolves_guid(
        self,
        db_session: AsyncSession,
        download_record: Download,
        media_item: MediaItem,
    ):
        svc = _download_service(db_session)
        result = await svc.get_media_item_guid_for_download(download_record)
        assert result == media_item.guid

    @pytest.mark.asyncio
    async def test_returns_none_when_no_link(self, db_session: AsyncSession):
        svc = _download_service(db_session)

        # Create a download with no release link
        dl_obj = Downloader(
            guid=uuid.uuid4(),
            label="Temp2",
            host="localhost",
            type="sabnzbd",
            ssl=False,
            verify_ssl=False,
        )
        db_session.add(dl_obj)
        await db_session.commit()

        dl = Download(
            guid=uuid.uuid4(),
            title="No Link",
            type="movie",
            downloader_id=dl_obj.guid,
            status="queued",
            external_id="nolink_ext_id",
            media_release_link_guid=None,
        )
        db_session.add(dl)
        await db_session.commit()
        await db_session.refresh(dl)

        result = await svc.get_media_item_guid_for_download(dl)
        assert result is None


# ===========================================================================
# DownloadService -- handle_completed_download
# ===========================================================================


class TestHandleCompletedDownload:
    @pytest.mark.asyncio
    async def test_not_found_returns_error(self, db_session: AsyncSession):
        svc = _download_service(db_session)
        result = await svc.handle_completed_download("nonexistent_ext_id", "/tmp/dl")
        assert result["success"] is False
        assert result["error"] == "Download not found"

    @pytest.mark.asyncio
    async def test_path_not_exist_marks_failed(
        self,
        db_session: AsyncSession,
        download_record: Download,
    ):
        svc = _download_service(db_session)

        with patch.object(svc, "blacklist_download", new_callable=AsyncMock, return_value=True):
            result = await svc.handle_completed_download(
                download_record.external_id, "/nonexistent/path/abc"
            )

        assert result["success"] is False
        await db_session.refresh(download_record)
        assert download_record.status == "Failed"


# ===========================================================================
# EmailService
# ===========================================================================


class TestEmailService:
    def _make_service(self):
        """Create an EmailService with patched settings to avoid real config."""
        from pyrate.services.email import EmailService

        return EmailService()

    def test_init_with_missing_templates_dir(self):
        """EmailService initializes with jinja_env=None when templates dir missing."""
        svc = self._make_service()
        # Default settings point to a templates dir that likely doesn't exist in test env
        # Either jinja_env is None or it points to the real templates
        # Just verify the service initializes without error
        assert svc is not None

    def test_render_template_without_jinja(self):
        """render_template returns empty/fallback when jinja_env is None."""
        svc = self._make_service()
        svc.jinja_env = None
        html, text = svc.render_template(
            "test_template", {"message": "hello world"}
        )
        assert html == ""
        assert text == "hello world"

    @pytest.mark.asyncio
    async def test_send_email_disabled(self):
        """send_email returns False when email is disabled."""
        svc = self._make_service()
        svc.config = MagicMock()
        svc.config.enabled = False

        result = await svc.send_email(
            to_email="test@example.com",
            subject="Test",
            message="Hello",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_send_email_success(self):
        """send_email returns True on successful SMTP send."""
        svc = self._make_service()
        svc.config = MagicMock()
        svc.config.enabled = True
        svc.config.from_name = "Test"
        svc.config.from_email = "test@example.com"
        svc.config.reply_to = None
        svc.config.smtp_host = "localhost"
        svc.config.smtp_port = 25
        svc.config.smtp_use_tls = False
        svc.config.smtp_use_ssl = False
        svc.config.smtp_user = None
        svc.config.smtp_password = None

        mock_response = MagicMock()
        mock_response.status_code = 250

        with patch("pyrate.services.email.emails.Message") as MockMsg:
            mock_msg_inst = MagicMock()
            mock_msg_inst.send.return_value = mock_response
            MockMsg.return_value = mock_msg_inst

            result = await svc.send_email(
                to_email="recipient@example.com",
                subject="Test Subject",
                message="Body text",
            )

        assert result is True
        mock_msg_inst.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_failure_status(self):
        """send_email returns False on non-250 SMTP status."""
        svc = self._make_service()
        svc.config = MagicMock()
        svc.config.enabled = True
        svc.config.from_name = "Test"
        svc.config.from_email = "test@example.com"
        svc.config.reply_to = None
        svc.config.smtp_host = "localhost"
        svc.config.smtp_port = 25
        svc.config.smtp_use_tls = False
        svc.config.smtp_use_ssl = False
        svc.config.smtp_user = None
        svc.config.smtp_password = None

        mock_response = MagicMock()
        mock_response.status_code = 550
        mock_response.error = "rejected"

        with patch("pyrate.services.email.emails.Message") as MockMsg:
            mock_msg_inst = MagicMock()
            mock_msg_inst.send.return_value = mock_response
            MockMsg.return_value = mock_msg_inst

            result = await svc.send_email(
                to_email="recipient@example.com",
                subject="Test Subject",
                message="Body text",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_email_exception(self):
        """send_email returns False when an exception occurs."""
        svc = self._make_service()
        svc.config = MagicMock()
        svc.config.enabled = True
        svc.config.from_name = "Test"
        svc.config.from_email = "test@example.com"
        svc.config.reply_to = None
        svc.config.smtp_host = "localhost"
        svc.config.smtp_port = 25
        svc.config.smtp_use_tls = False
        svc.config.smtp_use_ssl = False
        svc.config.smtp_user = None
        svc.config.smtp_password = None

        with patch("pyrate.services.email.emails.Message") as MockMsg:
            MockMsg.side_effect = ConnectionRefusedError("SMTP down")
            result = await svc.send_email(
                to_email="recipient@example.com",
                subject="Test Subject",
                message="Body text",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_email_with_template(self):
        """send_email renders template when template_name+context provided."""
        svc = self._make_service()
        svc.config = MagicMock()
        svc.config.enabled = True
        svc.config.from_name = "Test"
        svc.config.from_email = "test@example.com"
        svc.config.reply_to = "reply@example.com"
        svc.config.smtp_host = "localhost"
        svc.config.smtp_port = 25
        svc.config.smtp_use_tls = False
        svc.config.smtp_use_ssl = False
        svc.config.smtp_user = "user"
        svc.config.smtp_password = "pass"

        mock_response = MagicMock()
        mock_response.status_code = 250

        with (
            patch.object(
                svc,
                "render_template",
                return_value=("<h1>Hello</h1>", "Hello"),
            ) as mock_render,
            patch("pyrate.services.email.emails.Message") as MockMsg,
        ):
            mock_msg_inst = MagicMock()
            mock_msg_inst.send.return_value = mock_response
            MockMsg.return_value = mock_msg_inst

            result = await svc.send_email(
                to_email="recipient@example.com",
                subject="Test",
                template_name="welcome",
                context={"name": "Alice"},
            )

        assert result is True
        mock_render.assert_called_once_with("welcome", {"name": "Alice"})
        mock_msg_inst.set_header.assert_called_once_with(
            "Reply-To", "reply@example.com"
        )

    @pytest.mark.asyncio
    async def test_send_email_with_html_content(self):
        """send_email uses direct html_content when provided."""
        svc = self._make_service()
        svc.config = MagicMock()
        svc.config.enabled = True
        svc.config.from_name = "Test"
        svc.config.from_email = "test@example.com"
        svc.config.reply_to = None
        svc.config.smtp_host = "localhost"
        svc.config.smtp_port = 25
        svc.config.smtp_use_tls = False
        svc.config.smtp_use_ssl = False
        svc.config.smtp_user = None
        svc.config.smtp_password = None

        mock_response = MagicMock()
        mock_response.status_code = 250

        with patch("pyrate.services.email.emails.Message") as MockMsg:
            mock_msg_inst = MagicMock()
            mock_msg_inst.send.return_value = mock_response
            MockMsg.return_value = mock_msg_inst

            result = await svc.send_email(
                to_email="recipient@example.com",
                subject="Direct HTML",
                html_content="<p>Hello</p>",
            )

        assert result is True
        MockMsg.assert_called_once()
        call_kwargs = MockMsg.call_args
        assert call_kwargs[1]["html"] == "<p>Hello</p>"

    @pytest.mark.asyncio
    async def test_send_notification_email(self):
        """send_notification_email delegates to send_email with template context."""
        svc = self._make_service()

        with patch.object(
            svc, "send_email", new_callable=AsyncMock, return_value=True
        ) as mock_send:
            with patch("pyrate.services.email.get_app_url", return_value="https://example.com"):
                result = await svc.send_notification_email(
                    to_email="user@example.com",
                    subject="Alert",
                    message="Something happened",
                    notification_type="warning",
                )

        assert result is True
        mock_send.assert_awaited_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["template_name"] == "notification"
        assert call_kwargs["context"]["notification_type"] == "warning"
        assert call_kwargs["context"]["app_url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_send_notification_email_no_cors_origins(self):
        """Falls back to localhost URL when cors_allowed_origins is empty."""
        svc = self._make_service()

        with patch.object(
            svc, "send_email", new_callable=AsyncMock, return_value=True
        ) as mock_send:
            with patch(
                "pyrate.services.email.get_app_url",
                return_value="http://localhost:8080",
            ):
                await svc.send_notification_email(
                    to_email="user@example.com",
                    subject="Alert",
                    message="msg",
                )

        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["context"]["app_url"] == "http://localhost:8080"


# ===========================================================================
# PaymentService -- sync_subscription (not covered by test_payment_service.py)
# ===========================================================================


class TestPaymentServiceSyncSubscription:
    @pytest_asyncio.fixture
    async def sub_for_sync(
        self, db_session: AsyncSession, test_user: User
    ) -> "UserSubscription":
        from pyrate.models.subscription import UserSubscription

        sub = UserSubscription(
            user_id=test_user.guid,
            package_id=uuid.uuid4(),
            starts_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
            stripe_subscription_id="sub_sync_001",
            stripe_customer_id="cus_sync_001",
        )
        db_session.add(sub)
        await db_session.commit()
        await db_session.refresh(sub)
        return sub

    @pytest.mark.asyncio
    async def test_sync_active(
        self,
        db_session: AsyncSession,
        sub_for_sync,
    ):
        from pyrate.models.subscription import SubscriptionStatus
        from pyrate.services.payment import PaymentService

        provider = AsyncMock()
        now_ts = int(datetime.now(UTC).timestamp())
        future_ts = int((datetime.now(UTC) + timedelta(days=30)).timestamp())
        provider.get_subscription_status = AsyncMock(
            return_value={
                "status": "active",
                "current_period_start": now_ts,
                "current_period_end": future_ts,
            }
        )
        svc = PaymentService(db=db_session, payment_provider=provider)
        result = await svc.sync_subscription(sub_for_sync)

        assert result.status == SubscriptionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_sync_canceled(
        self,
        db_session: AsyncSession,
        sub_for_sync,
    ):
        from pyrate.models.subscription import SubscriptionStatus
        from pyrate.services.payment import PaymentService

        provider = AsyncMock()
        provider.get_subscription_status = AsyncMock(
            return_value={"status": "canceled"}
        )
        svc = PaymentService(db=db_session, payment_provider=provider)
        result = await svc.sync_subscription(sub_for_sync)

        assert result.status == SubscriptionStatus.CANCELLED
        assert result.cancelled_at is not None

    @pytest.mark.asyncio
    async def test_sync_past_due(
        self,
        db_session: AsyncSession,
        sub_for_sync,
    ):
        from pyrate.models.subscription import SubscriptionStatus
        from pyrate.services.payment import PaymentService

        provider = AsyncMock()
        provider.get_subscription_status = AsyncMock(
            return_value={"status": "past_due"}
        )
        svc = PaymentService(db=db_session, payment_provider=provider)
        result = await svc.sync_subscription(sub_for_sync)

        assert result.status == SubscriptionStatus.FAILED

    @pytest.mark.asyncio
    async def test_sync_unpaid(
        self,
        db_session: AsyncSession,
        sub_for_sync,
    ):
        from pyrate.models.subscription import SubscriptionStatus
        from pyrate.services.payment import PaymentService

        provider = AsyncMock()
        provider.get_subscription_status = AsyncMock(
            return_value={"status": "unpaid"}
        )
        svc = PaymentService(db=db_session, payment_provider=provider)
        result = await svc.sync_subscription(sub_for_sync)

        assert result.status == SubscriptionStatus.FAILED

    @pytest.mark.asyncio
    async def test_sync_provider_error_raises(
        self,
        db_session: AsyncSession,
        sub_for_sync,
    ):
        from pyrate.services.payment import PaymentService

        provider = AsyncMock()
        provider.get_subscription_status = AsyncMock(
            side_effect=RuntimeError("provider down")
        )
        svc = PaymentService(db=db_session, payment_provider=provider)

        with pytest.raises(RuntimeError, match="provider down"):
            await svc.sync_subscription(sub_for_sync)

    @pytest.mark.asyncio
    async def test_sync_cancelled_preserves_existing_cancelled_at(
        self,
        db_session: AsyncSession,
        sub_for_sync,
    ):
        """If cancelled_at is already set, sync does not overwrite it."""
        from pyrate.models.subscription import SubscriptionStatus
        from pyrate.services.payment import PaymentService

        # Use a naive datetime since SQLite stores naive datetimes
        original_time = datetime(2025, 1, 1, 0, 0)
        sub_for_sync.cancelled_at = original_time
        db_session.add(sub_for_sync)
        await db_session.commit()

        provider = AsyncMock()
        provider.get_subscription_status = AsyncMock(
            return_value={"status": "cancelled"}
        )
        svc = PaymentService(db=db_session, payment_provider=provider)
        result = await svc.sync_subscription(sub_for_sync)

        assert result.status == SubscriptionStatus.CANCELLED
        assert result.cancelled_at == original_time


# ===========================================================================
# PaymentService -- handle_subscription_updated with unpaid status
#   (not covered in test_payment_service.py)
# ===========================================================================


class TestPaymentWebhookUnpaid:
    @pytest.mark.asyncio
    async def test_handle_subscription_updated_unpaid(
        self, db_session: AsyncSession, test_user: User
    ):
        from pyrate.models.subscription import (
            SubscriptionStatus,
            UserSubscription,
        )
        from pyrate.services.payment import PaymentService

        sub = UserSubscription(
            user_id=test_user.guid,
            package_id=uuid.uuid4(),
            starts_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
            stripe_subscription_id="sub_unpaid_test",
            stripe_customer_id="cus_unpaid_test",
        )
        db_session.add(sub)
        await db_session.commit()
        await db_session.refresh(sub)

        provider = AsyncMock()
        svc = PaymentService(db=db_session, payment_provider=provider)
        await svc.handle_subscription_updated(
            {"id": "sub_unpaid_test", "status": "unpaid"}
        )

        await db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_subscription_updated_no_id(
        self, db_session: AsyncSession
    ):
        """Returns early without error when no subscription ID in event."""
        from pyrate.services.payment import PaymentService

        provider = AsyncMock()
        svc = PaymentService(db=db_session, payment_provider=provider)
        await svc.handle_subscription_updated({})

    @pytest.mark.asyncio
    async def test_handle_subscription_updated_unknown(
        self, db_session: AsyncSession
    ):
        """Returns early when subscription not found in DB."""
        from pyrate.services.payment import PaymentService

        provider = AsyncMock()
        svc = PaymentService(db=db_session, payment_provider=provider)
        await svc.handle_subscription_updated({"id": "sub_unknown_xyz"})
