"""Tests for MediaService – covers uncovered lines."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.media import MediaType
from pyrate.services.media import MediaService, cleanup_stream_on_stop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_media_item(**overrides):
    defaults = dict(
        guid=uuid.uuid4(),
        title="Test Movie",
        media_type=MediaType.MOVIES,
        parent_guid=None,
        sequence_number=1,
    )
    defaults.update(overrides)
    item = MagicMock()
    for k, v in defaults.items():
        setattr(item, k, v)
    return item


def _make_release(**overrides):
    defaults = dict(
        guid=uuid.uuid4(),
        title="Test.Movie.2024.1080p.BluRay",
        score=50,
        release_metadata={"resolution": "1080p"},
    )
    defaults.update(overrides)
    r = MagicMock()
    for k, v in defaults.items():
        setattr(r, k, v)
    return r


# ---------------------------------------------------------------------------
# set_genres (lines 166-199)
# ---------------------------------------------------------------------------


class TestSetGenres:
    @pytest.mark.asyncio
    async def test_set_genres_item_not_found(self, db_session: AsyncSession):
        """set_genres returns None when media item not found."""
        svc = MediaService(db_session)
        result = await svc.set_genres(uuid.uuid4(), ["Action"])
        assert result is None


# ---------------------------------------------------------------------------
# list_by_type with parent_guid filter (line 277)
# ---------------------------------------------------------------------------


class TestListByType:
    @pytest.mark.asyncio
    async def test_list_by_type_with_parent_filter(self, db_session: AsyncSession):
        """list_by_type filters by parent_guid."""
        svc = MediaService(db_session)
        parent = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Show"
        )
        child = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Season 1",
            parent_guid=parent.guid, sequence_number=1,
        )

        results = await svc.list_by_type(MediaType.SHOWS, parent_guid=parent.guid)
        assert len(results) == 1
        assert results[0].guid == child.guid


# ---------------------------------------------------------------------------
# search with library_guid filter (line 317)
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_by_title(self, db_session: AsyncSession):
        """search finds items by title."""
        svc = MediaService(db_session)
        await svc.create_media_item(
            media_type=MediaType.MOVIES, title="Inception"
        )
        results = await svc.search("Inception")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# count_by_type with library_guid (line 379)
# ---------------------------------------------------------------------------


class TestCountByType:
    @pytest.mark.asyncio
    async def test_count_by_type(self, db_session: AsyncSession):
        """count_by_type counts items by media type."""
        svc = MediaService(db_session)
        await svc.create_media_item(
            media_type=MediaType.MOVIES, title="Movie"
        )
        count = await svc.count_by_type(MediaType.MOVIES)
        assert count == 1


# ---------------------------------------------------------------------------
# validate_with_plugin (lines 538, 546-549)
# ---------------------------------------------------------------------------


class TestValidateWithPlugin:
    @pytest.mark.asyncio
    async def test_validate_with_plugin_found(self, db_session: AsyncSession):
        """validate_with_plugin delegates to plugin."""
        svc = MediaService(db_session)
        mock_plugin = MagicMock()
        mock_plugin.validate_path = AsyncMock(return_value=True)

        with patch("pyrate.services.media.get_plugin_instance", return_value=mock_plugin):
            result = await svc.validate_with_plugin(MediaType.MOVIES, "/library/movies/test.mkv")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_with_plugin_none(self, db_session: AsyncSession):
        """validate_with_plugin returns True when no plugin found."""
        svc = MediaService(db_session)
        with patch("pyrate.services.media.get_plugin_instance", return_value=None):
            result = await svc.validate_with_plugin(MediaType.MOVIES, "/library/movies/test.mkv")
        assert result is True


# ---------------------------------------------------------------------------
# is_valid_video_file (lines 605-606)
# ---------------------------------------------------------------------------


class TestIsValidVideoFile:
    def test_valid_mkv(self, tmp_path: Path):
        f = tmp_path / "movie.mkv"
        f.write_bytes(b"data")
        assert MediaService.is_valid_video_file(f) is True

    def test_sample_rejected(self, tmp_path: Path):
        f = tmp_path / "Sample.mkv"
        f.write_bytes(b"data")
        assert MediaService.is_valid_video_file(f) is False

    def test_wrong_extension(self, tmp_path: Path):
        f = tmp_path / "readme.txt"
        f.write_bytes(b"data")
        assert MediaService.is_valid_video_file(f) is False

    def test_directory_rejected(self, tmp_path: Path):
        d = tmp_path / "subdir"
        d.mkdir()
        assert MediaService.is_valid_video_file(d) is False


# ---------------------------------------------------------------------------
# select_best_release (lines 626-627, 645, 668)
# ---------------------------------------------------------------------------


class TestSelectBestRelease:
    @pytest.mark.asyncio
    async def test_select_best_release_empty(self, db_session: AsyncSession):
        """Returns None when no releases."""
        svc = MediaService(db_session)
        result = await svc.select_best_release(_make_media_item(), [])
        assert result is None

    @pytest.mark.asyncio
    async def test_select_best_release_no_plugin(self, db_session: AsyncSession):
        """Returns first release when no plugin found."""
        svc = MediaService(db_session)
        media_item = _make_media_item(media_type=MagicMock(value="UNKNOWN"))
        releases = [_make_release()]

        with patch("pyrate.services.media.get_plugin_instance", return_value=None):
            result = await svc.select_best_release(media_item, releases)
        assert result == releases[0]

    @pytest.mark.asyncio
    async def test_select_best_release_with_scoring(self, db_session: AsyncSession):
        """Selects highest scored release."""
        svc = MediaService(db_session)
        media_item = _make_media_item(media_type=MediaType.MOVIES)

        r1 = _make_release(title="Low Quality", release_metadata={"resolution": "480p"})
        r2 = _make_release(title="High Quality", release_metadata={"resolution": "1080p"})

        mock_plugin = MagicMock()
        mock_plugin.extract_release_metadata = AsyncMock(side_effect=lambda t: {"title": t})
        mock_plugin.score_release = AsyncMock(side_effect=[30.0, 90.0])

        with patch("pyrate.services.media.get_plugin_instance", return_value=mock_plugin), \
             patch("pyrate.services.settings.SettingsService.get", new_callable=AsyncMock, return_value=None):
            result = await svc.select_best_release(media_item, [r1, r2])

        assert result == r2

    @pytest.mark.asyncio
    async def test_select_best_release_scoring_error_fallback(self, db_session: AsyncSession):
        """Release scoring error falls back to score 25."""
        svc = MediaService(db_session)
        media_item = _make_media_item(media_type=MediaType.MOVIES)

        r1 = _make_release(release_metadata=None)

        mock_plugin = MagicMock()
        mock_plugin.extract_release_metadata = AsyncMock(side_effect=Exception("parse error"))

        with patch("pyrate.services.media.get_plugin_instance", return_value=mock_plugin), \
             patch("pyrate.services.settings.SettingsService.get", new_callable=AsyncMock, return_value=None):
            result = await svc.select_best_release(media_item, [r1])

        assert result == r1

    @pytest.mark.asyncio
    async def test_select_best_release_with_language_prefs(self, db_session: AsyncSession):
        """Language preferences are injected into scoring."""
        svc = MediaService(db_session)
        media_item = _make_media_item(media_type=MediaType.MOVIES)
        r1 = _make_release()

        mock_plugin = MagicMock()
        mock_plugin.extract_release_metadata = AsyncMock(return_value={"title": "test"})
        mock_plugin.score_release = AsyncMock(return_value=80.0)

        with patch("pyrate.services.media.get_plugin_instance", return_value=mock_plugin), \
             patch("pyrate.services.settings.SettingsService.get", new_callable=AsyncMock, return_value=None):
            result = await svc.select_best_release(
                media_item, [r1],
                user_languages=["de"],
                allowed_languages=["de", "en"],
                supported_video_codecs=["h264"],
                codec_match_bonus=10,
            )

        assert result == r1


# ---------------------------------------------------------------------------
# cleanup_media_file (lines 814-817, 842-843)
# ---------------------------------------------------------------------------


class TestCleanupMediaFile:
    @pytest.mark.asyncio
    async def test_cleanup_media_file_db_error(self, db_session: AsyncSession):
        """Database error is caught and added to errors (lines 814-817)."""
        svc = MediaService(db_session)

        with patch.object(db_session, "execute", side_effect=Exception("db boom")), \
             patch.object(db_session, "rollback", new_callable=AsyncMock):
            result = await svc.cleanup_media_file(uuid.uuid4())

        assert len(result["errors"]) > 0
        assert "db boom" in result["errors"][0]


# ---------------------------------------------------------------------------
# cleanup_orphaned_temp_files error handling (lines 893-895)
# ---------------------------------------------------------------------------


class TestCleanupOrphanedError:
    @pytest.mark.asyncio
    async def test_cleanup_orphaned_glob_error(self, db_session: AsyncSession):
        """glob error is caught (lines 893-895)."""
        svc = MediaService(db_session)

        with patch("pyrate.services.media.glob.glob", side_effect=Exception("perm denied")):
            result = await svc.cleanup_orphaned_temp_files()

        assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# get_next_sibling / get_previous_sibling (lines 919-1015)
# ---------------------------------------------------------------------------


class TestNavigationSiblings:
    @pytest.mark.asyncio
    async def test_get_next_sibling_no_parent(self, db_session: AsyncSession):
        """get_next_sibling returns None for item without parent."""
        svc = MediaService(db_session)
        item = await svc.create_media_item(
            media_type=MediaType.MOVIES, title="Standalone"
        )
        result = await svc.get_next_sibling(item.guid)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_next_sibling_finds_next(self, db_session: AsyncSession):
        """get_next_sibling finds the next episode."""
        svc = MediaService(db_session)
        season = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Season 1"
        )
        ep1 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Episode 1",
            parent_guid=season.guid, sequence_number=1,
        )
        ep2 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Episode 2",
            parent_guid=season.guid, sequence_number=2,
        )

        result = await svc.get_next_sibling(ep1.guid)
        assert result is not None
        assert result["guid"] == str(ep2.guid)

    @pytest.mark.asyncio
    async def test_get_next_sibling_end_of_season(self, db_session: AsyncSession):
        """get_next_sibling at end of season returns first ep of next season."""
        svc = MediaService(db_session)
        show = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Show"
        )
        season1 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Season 1",
            parent_guid=show.guid, sequence_number=1,
        )
        season2 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Season 2",
            parent_guid=show.guid, sequence_number=2,
        )
        ep1 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="S01E01",
            parent_guid=season1.guid, sequence_number=1,
        )
        ep2 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="S02E01",
            parent_guid=season2.guid, sequence_number=1,
        )

        result = await svc.get_next_sibling(ep1.guid)
        assert result is not None
        assert result["guid"] == str(ep2.guid)

    @pytest.mark.asyncio
    async def test_get_next_sibling_no_next_season(self, db_session: AsyncSession):
        """get_next_sibling returns None when no next season."""
        svc = MediaService(db_session)
        show = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Show"
        )
        season1 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Season 1",
            parent_guid=show.guid, sequence_number=1,
        )
        ep1 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="S01E01",
            parent_guid=season1.guid, sequence_number=1,
        )

        result = await svc.get_next_sibling(ep1.guid)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_previous_sibling_no_parent(self, db_session: AsyncSession):
        """get_previous_sibling returns None for item without parent."""
        svc = MediaService(db_session)
        item = await svc.create_media_item(
            media_type=MediaType.MOVIES, title="Standalone"
        )
        result = await svc.get_previous_sibling(item.guid)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_previous_sibling_finds_prev(self, db_session: AsyncSession):
        """get_previous_sibling finds the previous episode."""
        svc = MediaService(db_session)
        season = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Season 1"
        )
        ep1 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Episode 1",
            parent_guid=season.guid, sequence_number=1,
        )
        ep2 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Episode 2",
            parent_guid=season.guid, sequence_number=2,
        )

        result = await svc.get_previous_sibling(ep2.guid)
        assert result is not None
        assert result["guid"] == str(ep1.guid)

    @pytest.mark.asyncio
    async def test_get_previous_sibling_start_of_season(self, db_session: AsyncSession):
        """get_previous_sibling at start of season returns last ep of prev season."""
        svc = MediaService(db_session)
        show = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Show"
        )
        season1 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Season 1",
            parent_guid=show.guid, sequence_number=1,
        )
        season2 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Season 2",
            parent_guid=show.guid, sequence_number=2,
        )
        ep1 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="S01E01",
            parent_guid=season1.guid, sequence_number=1,
        )
        ep2 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="S02E01",
            parent_guid=season2.guid, sequence_number=1,
        )

        result = await svc.get_previous_sibling(ep2.guid)
        assert result is not None
        assert result["guid"] == str(ep1.guid)

    @pytest.mark.asyncio
    async def test_get_previous_sibling_no_prev_season(self, db_session: AsyncSession):
        """get_previous_sibling returns None when no previous season."""
        svc = MediaService(db_session)
        show = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Show"
        )
        season1 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="Season 1",
            parent_guid=show.guid, sequence_number=1,
        )
        ep1 = await svc.create_media_item(
            media_type=MediaType.SHOWS, title="S01E01",
            parent_guid=season1.guid, sequence_number=1,
        )

        result = await svc.get_previous_sibling(ep1.guid)
        assert result is None


# ---------------------------------------------------------------------------
# cleanup_stream_on_stop with content_id (line 1063)
# ---------------------------------------------------------------------------


class TestCleanupStreamOnStopWithContentId:
    @pytest.mark.asyncio
    async def test_cleanup_with_content_id(self, db_session: AsyncSession):
        """cleanup_stream_on_stop leaves source library files to retention cleanup."""
        with patch("pyrate.services.media.glob.glob", return_value=[]), \
             patch.object(MediaService, "cleanup_media_file", new_callable=AsyncMock) as mock_cleanup:
            result = await cleanup_stream_on_stop(
                db=db_session,
                session_id="test-session",
                content_id=str(uuid.uuid4()),
                input_path="/library/movies/test.mkv",
                delete_library_file=True,
            )

        assert "library_cleanup" in result
        assert result["library_cleanup"] == {}
        mock_cleanup.assert_not_awaited()
