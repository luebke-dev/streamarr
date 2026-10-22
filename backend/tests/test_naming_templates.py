"""Naming templates: configured templates drive folder and file names.

`plugin.shows.naming.*` and `plugin.movies.naming.*` shipped as settings with
defaults, but nothing read them - every path was built by the hardcoded
Trash-style convention. An explicitly configured template now wins; leaving it
unset keeps the previous names, so existing libraries do not get renamed.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.libraries.movies import MovieLibraryPlugin
from streamarr.libraries.shows import ShowLibraryPlugin
from streamarr.services.settings import SettingsService


@pytest.fixture
def show_plugin() -> ShowLibraryPlugin:
    return ShowLibraryPlugin()


@pytest.fixture
def movie_plugin() -> MovieLibraryPlugin:
    return MovieLibraryPlugin()


class TestShowNamingTemplates:
    async def test_unset_template_keeps_the_trash_style_folder(
        self, db_session: AsyncSession, show_plugin: ShowLibraryPlugin
    ):
        folder = await show_plugin.suggest_folder_name(
            media_info={"title": "The Series Title!", "year": 2010}, tmdb_id=12345,
            db=db_session,
        )
        assert folder == "The Series Title! (2010) {tmdb-12345}"

    async def test_configured_folder_template_wins(
        self, db_session: AsyncSession, show_plugin: ShowLibraryPlugin
    ):
        await SettingsService(db_session).set(
            "plugin.shows.naming.series_folder",
            "{series_title} ({series_year}) [tvdbid-{tvdb_id}]",
        )
        folder = await show_plugin.suggest_folder_name(
            media_info={"title": "Stargate SG-1", "year": 1997, "tvdb_id": 72449},
            db=db_session,
        )
        assert folder == "Stargate SG-1 (1997) [tvdbid-72449]"

    async def test_missing_id_drops_the_whole_group(
        self, db_session: AsyncSession, show_plugin: ShowLibraryPlugin
    ):
        """A show without a TVDB id must not produce `[tvdbid-]`."""
        await SettingsService(db_session).set(
            "plugin.shows.naming.series_folder",
            "{series_title} ({series_year}) [tvdbid-{tvdb_id}]",
        )
        folder = await show_plugin.suggest_folder_name(
            media_info={"title": "No Id Show", "year": 2001}, db=db_session,
        )
        assert folder == "No Id Show (2001)"

    async def test_season_folder_template(
        self, db_session: AsyncSession, show_plugin: ShowLibraryPlugin
    ):
        assert await show_plugin.suggest_season_folder_name(3, db=db_session) == "Season 03"

        await SettingsService(db_session).set(
            "plugin.shows.naming.season_folder", "Staffel {season_number}"
        )
        assert await show_plugin.suggest_season_folder_name(3, db=db_session) == "Staffel 3"

    async def test_episode_file_template_uses_probe_metadata(
        self, db_session: AsyncSession, show_plugin: ShowLibraryPlugin
    ):
        await SettingsService(db_session).set(
            "plugin.shows.naming.episode_file",
            "{series_title} - S{season_number_2}E{episode_number_2} - "
            "{episode_title} [{resolution}][{video_codec}]",
        )
        probe = {
            "video_streams": [{"codec_name": "hevc", "width": 1920, "height": 1080}],
            "audio_streams": [{"codec_name": "eac3", "channels": 6}],
            "subtitle_streams": [],
        }
        name = await show_plugin.suggest_file_name(
            media_info={
                "show_title": "Futurama",
                "year": 1999,
                "season": 2,
                "episode": 4,
                "episode_title": "Xmas Story",
            },
            probe_data=probe,
            db=db_session,
        )
        # ffprobe says "hevc"; the canonical Streamarr name for it is h265.
        assert name == "Futurama - S02E04 - Xmas Story [1080p][h265]"

    async def test_unprobed_episode_has_no_empty_brackets(
        self, db_session: AsyncSession, show_plugin: ShowLibraryPlugin
    ):
        await SettingsService(db_session).set(
            "plugin.shows.naming.episode_file",
            "{series_title} - S{season_number_2}E{episode_number_2} "
            "[{resolution}][{video_codec}]",
        )
        name = await show_plugin.suggest_file_name(
            media_info={
                "show_title": "Futurama",
                "season": 1,
                "episode": 1,
                "episode_title": "Space Pilot 3000",
            },
            db=db_session,
        )
        assert name == "Futurama - S01E01"
        assert "[]" not in name


class TestMovieNamingTemplates:
    async def test_unset_template_keeps_the_trash_style_name(
        self, db_session: AsyncSession, movie_plugin: MovieLibraryPlugin
    ):
        folder = await movie_plugin.suggest_folder_name(
            media_info={"title": "Heat", "year": 1995}, tmdb_id=949, db=db_session,
        )
        assert folder == "Heat (1995) {tmdb-949}"

    async def test_configured_folder_and_file_templates(
        self, db_session: AsyncSession, movie_plugin: MovieLibraryPlugin
    ):
        settings = SettingsService(db_session)
        await settings.set(
            "plugin.movies.naming.folder", "{movie_title} ({movie_year}) [tmdbid-{tmdb_id}]"
        )
        await settings.set(
            "plugin.movies.naming.file",
            "{movie_title} ({movie_year}) [{resolution}][{video_codec}]",
        )

        folder = await movie_plugin.suggest_folder_name(
            media_info={"title": "Heat", "year": 1995, "tmdb_id": 949}, db=db_session,
        )
        name = await movie_plugin.suggest_file_name(
            media_info={"title": "Heat", "year": 1995, "tmdb_id": 949},
            probe_data={
                "video_streams": [{"codec_name": "av1", "width": 3840, "height": 2160}],
                "audio_streams": [{"codec_name": "eac3", "channels": 6}],
                "subtitle_streams": [],
            },
            db=db_session,
        )

        assert folder == "Heat (1995) [tmdbid-949]"
        assert name == "Heat (1995) [2160p][av1]"
