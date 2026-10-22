"""Import placement: register in place or move into the library.

`automation.import_mode` decides what happens to a finished download. The
historical behaviour ("register") suits rclone-backed instances where the
download folder *is* the library entry; "library" is Sonarr/Radarr semantics -
move the file into the library under its final name and drop the download copy.
"""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.libraries.base import (
    IMPORT_MODE_LIBRARY,
    IMPORT_MODE_REGISTER,
    get_import_mode,
)
from streamarr.libraries.movies import MovieLibraryPlugin
from streamarr.libraries.shows import ShowLibraryPlugin
from streamarr.models.media import MediaFile
from streamarr.services.settings import SettingsService


def _media_file(path) -> MediaFile:
    return MediaFile(
        guid=uuid.uuid4(),
        media_item_guid=uuid.uuid4(),
        file_path=str(path),
        file_name=path.name,
        file_size=123,
    )


class TestGetImportMode:
    async def test_default_is_register(self, db_session: AsyncSession):
        assert await get_import_mode(db_session) == IMPORT_MODE_REGISTER

    async def test_library_mode_is_read_from_settings(self, db_session: AsyncSession):
        await SettingsService(db_session).set("automation.import_mode", "library")
        assert await get_import_mode(db_session) == IMPORT_MODE_LIBRARY

    async def test_unknown_value_falls_back_to_register(
        self, db_session: AsyncSession
    ):
        """A stray value must never silently turn imports into file moves."""
        await SettingsService(db_session).set("automation.import_mode", "move-please")
        assert await get_import_mode(db_session) == IMPORT_MODE_REGISTER


class TestFinalizeImportLocation:
    async def test_register_mode_leaves_the_file_alone(
        self, db_session: AsyncSession, tmp_path
    ):
        plugin = MovieLibraryPlugin()
        source = tmp_path / "downloads" / "Some.Movie.2024.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"x")

        called = False

        async def _promote(_media_file, _db):
            nonlocal called
            called = True
            return {"success": True}

        plugin.promote_to_library = _promote
        result = await plugin.finalize_import_location(_media_file(source), db_session)

        assert result == {"success": True, "moved": False}
        assert called is False
        assert source.exists()

    async def test_library_mode_moves_and_drops_the_download_copy(
        self, db_session: AsyncSession, tmp_path
    ):
        await SettingsService(db_session).set("automation.import_mode", "library")
        plugin = ShowLibraryPlugin()
        source = tmp_path / "downloads" / "Show.S01E01.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"payload")
        destination = tmp_path / "library" / "Show (2020)" / "Season 01" / "Show - S01E01.mkv"
        media_file = _media_file(source)

        async def _promote(mf, _db):
            # Mirrors the real promotion path: copy, then repoint the row.
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"payload")
            mf.file_path = str(destination)
            return {"success": True, "file_path": str(destination)}

        plugin.promote_to_library = _promote
        result = await plugin.finalize_import_location(media_file, db_session)

        assert result["success"] is True
        assert result["moved"] is True
        assert result["source_removed"] is True
        assert media_file.file_path == str(destination)
        assert destination.exists()
        assert source.exists() is False

    async def test_failed_promotion_keeps_the_download(
        self, db_session: AsyncSession, tmp_path
    ):
        await SettingsService(db_session).set("automation.import_mode", "library")
        plugin = MovieLibraryPlugin()
        source = tmp_path / "downloads" / "Movie.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"x")

        async def _promote(_mf, _db):
            return {"success": False, "error": "Source missing"}

        plugin.promote_to_library = _promote
        result = await plugin.finalize_import_location(_media_file(source), db_session)

        assert result["success"] is False
        assert result["moved"] is False
        assert source.exists() is True

    async def test_leftover_download_copy_is_not_an_import_failure(
        self, db_session: AsyncSession, tmp_path, monkeypatch
    ):
        """The library copy is what matters; a stuck unlink is only a warning."""
        await SettingsService(db_session).set("automation.import_mode", "library")
        plugin = MovieLibraryPlugin()
        source = tmp_path / "downloads" / "Movie.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"x")
        destination = tmp_path / "library" / "Movie (2024)" / "Movie.mkv"
        media_file = _media_file(source)

        async def _promote(_mf, _db):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"x")
            _mf.file_path = str(destination)
            return {"success": True, "file_path": str(destination)}

        plugin.promote_to_library = _promote

        real_to_thread = asyncio.to_thread

        async def _to_thread(func, *args, **kwargs):
            if getattr(func, "__name__", "") == "unlink":
                raise OSError("stale NFS handle")
            return await real_to_thread(func, *args, **kwargs)

        monkeypatch.setattr("streamarr.libraries.base.asyncio.to_thread", _to_thread)
        result = await plugin.finalize_import_location(media_file, db_session)

        assert result["success"] is True
        assert result["moved"] is True
        assert result["source_removed"] is False
        assert destination.exists() is True
        assert source.exists() is True

    async def test_plugin_without_promotion_path_is_left_in_place(
        self, db_session: AsyncSession, tmp_path
    ):
        await SettingsService(db_session).set("automation.import_mode", "library")

        class _NoPromotionPlugin(MovieLibraryPlugin):
            # Music/games style plugin: no promotion path at all.
            promote_to_library = None

        plugin = _NoPromotionPlugin()
        source = tmp_path / "downloads" / "Movie.mkv"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"x")

        result = await plugin.finalize_import_location(_media_file(source), db_session)

        assert result == {"success": True, "moved": False}
        assert source.exists() is True
