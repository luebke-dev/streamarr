"""Additional tests for LibraryService – covers uncovered lines."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.library import Library
from streamarr.models.media import (
    AvailabilityStatus,
    MediaItem,
    MediaRelease,
    MediaType,
)
from streamarr.services.library import LibraryService


class MockPlugin:
    """Mock plugin for testing."""

    def __init__(self, library_type="MOVIES"):
        self.library_type = library_type

    async def get_default_path(self):
        return f"/library/{self.library_type.lower()}"

    async def validate_path(self, path):
        return True

    async def initialize_library(self, path):
        pass

    async def get_library_stats(self, path):
        return {"total_items": 42, "total_size": 1024000}

    async def scan_library(self, path):
        return [{"path": f"{path}/movie1.mp4", "size": 1000}]

    async def match_media(self, file_info):
        return {"title": "Test Movie", "external_id": "12345", "provider": "tmdb"}


# ---------------------------------------------------------------------------
# update_library with settings (line 171)
# ---------------------------------------------------------------------------


class TestUpdateLibrarySettings:
    @pytest.mark.asyncio
    async def test_update_library_settings_json(self, db_session: AsyncSession):
        """update_library serializes settings to JSON (line 171)."""
        service = LibraryService(db_session)

        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="Test",
                type="MOVIES",
                plugin_id="movies",
                path="/data/test",
            )

        updated = await service.update_library(
            library.guid,
            settings={"quality": "1080p", "language": "en"},
        )

        assert updated is not None
        assert '"quality"' in updated.settings
        assert '"1080p"' in updated.settings


# ---------------------------------------------------------------------------
# initialize_default_libraries (lines 219-243)
# ---------------------------------------------------------------------------


class TestInitializeDefaultLibraries:
    @pytest.mark.asyncio
    async def test_initialize_default_libraries_uses_plugins(self, db_session: AsyncSession):
        """initialize_default_libraries creates libraries from _plugins."""
        service = LibraryService(db_session)

        mock_plugin = MockPlugin("MOVIES")
        mock_plugin.get_name = lambda: "Movies"

        # The method iterates _plugin_classes and instantiates each plugin_class()
        service._plugin_classes = {"MOVIES": lambda: mock_plugin}

        with patch.object(service, "get_library_by_type", return_value=None), \
             patch.object(service, "create_library", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = MagicMock()
            created = await service.initialize_default_libraries()

        assert len(created) == 1

    @pytest.mark.asyncio
    async def test_initialize_default_libraries_skips_existing(self, db_session: AsyncSession):
        """initialize_default_libraries skips existing library types."""
        service = LibraryService(db_session)

        mock_plugin = MockPlugin("MOVIES")
        mock_plugin.get_name = lambda: "Movies"
        service._plugins = {"MOVIES": mock_plugin}

        with patch.object(service, "get_library_by_type", return_value=MagicMock(name="Existing")):
            created = await service.initialize_default_libraries()

        assert len(created) == 0

    @pytest.mark.asyncio
    async def test_initialize_default_libraries_handles_error(self, db_session: AsyncSession):
        """initialize_default_libraries catches exceptions per library type."""
        service = LibraryService(db_session)

        mock_plugin = MockPlugin("MOVIES")
        mock_plugin.get_name = lambda: "Movies"
        service._plugins = {"MOVIES": mock_plugin}

        with patch.object(service, "get_library_by_type", return_value=None), \
             patch.object(service, "create_library", side_effect=Exception("create error")):
            created = await service.initialize_default_libraries()

        assert len(created) == 0


# ---------------------------------------------------------------------------
# create_media_item with library_guid but not found (line 272)
# ---------------------------------------------------------------------------


class TestCreateMediaItemLibraryNotFound:
    @pytest.mark.asyncio
    async def test_create_media_item_library_not_found(self, db_session: AsyncSession):
        """create_media_item raises when library_guid is invalid."""
        service = LibraryService(db_session)
        with pytest.raises(ValueError, match="Library not found"):
            await service.create_media_item(
                title="Test",
                library_guid=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# get_library_stats with no plugin (line 365)
# ---------------------------------------------------------------------------


class TestLibraryStatsNoPlugin:
    @pytest.mark.asyncio
    async def test_get_library_stats_no_plugin(self, db_session: AsyncSession):
        """get_library_stats returns None when no plugin found."""
        service = LibraryService(db_session)

        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="Test",
                type="MOVIES",
                plugin_id="movies",
                path="/data/test",
            )

        with patch.object(service, "get_plugin", return_value=None):
            stats = await service.get_library_stats(library.guid)

        assert stats is None


# ---------------------------------------------------------------------------
# scan_library_for_media: no plugin (line 604)
# ---------------------------------------------------------------------------


class TestScanLibraryNoPlugin:
    @pytest.mark.asyncio
    async def test_scan_library_no_plugin(self, db_session: AsyncSession):
        """scan_library_for_media raises when no plugin found."""
        service = LibraryService(db_session)

        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="Test",
                type="MOVIES",
                plugin_id="movies",
                path="/data/test",
            )

        with patch.object(service, "get_plugin", return_value=None):
            with pytest.raises(ValueError, match="No plugin found"):
                await service.scan_library_for_media(library.guid)


# ---------------------------------------------------------------------------
# match_media_with_metadata: library not found (line 629), no plugin (line 633)
# ---------------------------------------------------------------------------


class TestMatchMediaMetadata:
    @pytest.mark.asyncio
    async def test_match_media_library_not_found(self, db_session: AsyncSession):
        """match_media_with_metadata returns None when library not found."""
        service = LibraryService(db_session)
        result = await service.match_media_with_metadata(
            uuid.uuid4(), {"path": "/test.mp4"}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_match_media_no_plugin(self, db_session: AsyncSession):
        """match_media_with_metadata returns None when no plugin."""
        service = LibraryService(db_session)

        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="Test",
                type="MOVIES",
                plugin_id="movies",
                path="/data/test",
            )

        with patch.object(service, "get_plugin", return_value=None):
            result = await service.match_media_with_metadata(
                library.guid, {"path": "/test.mp4"}
            )

        assert result is None


# ---------------------------------------------------------------------------
# rescore_releases (lines 708-709, 718-722, 755-757)
# ---------------------------------------------------------------------------


class TestRescoreReleases:
    @pytest.mark.asyncio
    async def test_rescore_empty_releases(self, db_session: AsyncSession):
        """rescore_releases returns empty list for empty input."""
        service = LibraryService(db_session)
        media_item = MagicMock()
        result = await service.rescore_releases(media_item, [])
        assert result == []

    @pytest.mark.asyncio
    async def test_rescore_no_scoring_plugin(self, db_session: AsyncSession):
        """rescore_releases returns releases unchanged when no plugin."""
        service = LibraryService(db_session)
        media_item = MagicMock()
        media_item.media_type = MediaType.MOVIES

        releases = [MagicMock(title="Release 1", score=50)]

        with patch.object(service, "get_plugin", return_value=None):
            result = await service.rescore_releases(media_item, releases)

        assert result == releases

    @pytest.mark.asyncio
    async def test_rescore_with_allowed_languages(self, db_session: AsyncSession):
        """rescore_releases injects allowed_languages into scoring preferences."""
        service = LibraryService(db_session)
        media_item = MagicMock()
        media_item.media_type = MediaType.MOVIES

        mock_release = MagicMock()
        mock_release.title = "Test Release"
        mock_release.score = 50
        mock_release.release_metadata = {}

        mock_plugin = MagicMock()
        mock_plugin.extract_release_metadata = AsyncMock(return_value={"resolution": "1080p"})
        mock_plugin.score_release = AsyncMock(return_value=75)

        with patch.object(service, "get_plugin", return_value=mock_plugin), \
             patch("streamarr.services.library.SettingsService") as MockSS:
            mock_ss = MagicMock()
            mock_ss.get = AsyncMock(side_effect=[None, ["en", "de"]])
            MockSS.return_value = mock_ss

            with patch.object(db_session, "commit", new_callable=AsyncMock):
                result = await service.rescore_releases(media_item, [mock_release])

        assert mock_release.score == 75

    @pytest.mark.asyncio
    async def test_rescore_commit_error(self, db_session: AsyncSession):
        """rescore_releases catches commit errors (lines 755-757)."""
        service = LibraryService(db_session)
        media_item = MagicMock()
        media_item.media_type = MediaType.MOVIES

        mock_release = MagicMock()
        mock_release.title = "Test Release"
        mock_release.score = 50
        mock_release.release_metadata = {}

        mock_plugin = MagicMock()
        mock_plugin.extract_release_metadata = AsyncMock(return_value={"resolution": "1080p"})
        mock_plugin.score_release = AsyncMock(return_value=80)

        with patch.object(service, "get_plugin", return_value=mock_plugin), \
             patch("streamarr.services.library.SettingsService") as MockSS:
            mock_ss = MagicMock()
            mock_ss.get = AsyncMock(return_value=None)
            MockSS.return_value = mock_ss

            with patch.object(db_session, "commit", side_effect=Exception("commit error")), \
                 patch.object(db_session, "rollback", new_callable=AsyncMock):
                result = await service.rescore_releases(media_item, [mock_release])

        # Should still return releases despite commit error
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_rescore_scoring_error(self, db_session: AsyncSession):
        """rescore_releases catches per-release scoring errors."""
        service = LibraryService(db_session)
        media_item = MagicMock()
        media_item.media_type = MediaType.MOVIES

        mock_release = MagicMock()
        mock_release.title = "Test Release"
        mock_release.score = 50

        mock_plugin = MagicMock()
        mock_plugin.extract_release_metadata = AsyncMock(side_effect=Exception("parse error"))
        mock_plugin.score_release = AsyncMock(return_value=80)

        with patch.object(service, "get_plugin", return_value=mock_plugin), \
             patch("streamarr.services.library.SettingsService") as MockSS:
            mock_ss = MagicMock()
            mock_ss.get = AsyncMock(return_value=None)
            MockSS.return_value = mock_ss

            result = await service.rescore_releases(media_item, [mock_release])

        assert len(result) == 1


# ---------------------------------------------------------------------------
# update_media_item not found (line 465)
# ---------------------------------------------------------------------------


class TestUpdateMediaItemNotFound:
    @pytest.mark.asyncio
    async def test_update_media_item_not_found(self, db_session: AsyncSession):
        """update_media_item returns None for nonexistent item."""
        service = LibraryService(db_session)
        result = await service.update_media_item(uuid.uuid4(), title="New")
        assert result is None
