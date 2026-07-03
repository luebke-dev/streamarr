"""Tests for SystemSettingsService (compatibility layer over SettingsService)."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.services.system_settings import SystemSettingsService


@pytest_asyncio.fixture
async def system_settings(db_session: AsyncSession) -> SystemSettingsService:
    """Create a SystemSettingsService instance."""
    return SystemSettingsService(db_session)


class TestLibrarySettings:
    """Tests for library enable/disable settings."""

    @pytest.mark.asyncio
    async def test_get_libraries_enabled_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test that all libraries are enabled by default."""
        result = await system_settings.get_libraries_enabled()

        assert result["movies_enabled"] is True
        assert result["shows_enabled"] is True
        assert result["music_enabled"] is True
        assert result["books_enabled"] is True
        assert result["games_enabled"] is True

    @pytest.mark.asyncio
    async def test_update_libraries_enabled(
        self, system_settings: SystemSettingsService
    ):
        """Test updating library enabled states."""
        result = await system_settings.update_libraries_enabled(
            movies_enabled=False,
            games_enabled=False,
        )

        assert result["movies_enabled"] is False
        assert result["games_enabled"] is False
        # Unchanged
        assert result["shows_enabled"] is True
        assert result["music_enabled"] is True
        assert result["books_enabled"] is True

    @pytest.mark.asyncio
    async def test_update_libraries_enabled_persists(
        self, system_settings: SystemSettingsService
    ):
        """Test that library changes persist across reads."""
        await system_settings.update_libraries_enabled(music_enabled=False)
        result = await system_settings.get_libraries_enabled()
        assert result["music_enabled"] is False


class TestMovieSettings:
    """Tests for movie library settings."""

    @pytest.mark.asyncio
    async def test_get_movie_settings_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default movie settings."""
        result = await system_settings.get_library_settings("movies")

        assert result["enable_library"] is True
        assert result["library_path"] == "/library/movies"
        assert result["enable_on_demand_downloads"] is True
        assert result["enable_prefetch_downloads"] is False
        assert result["download_rules"] == []
        assert result["on_demand_rules"] == []

    @pytest.mark.asyncio
    async def test_update_movie_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating movie settings."""
        rules = [{"quality": "1080p", "source": "bluray"}]
        result = await system_settings.update_library_settings(
            "movies",
            library_path="/custom/movies",
            enable_prefetch_downloads=True,
            download_rules=rules,
        )

        assert result["library_path"] == "/custom/movies"
        assert result["enable_prefetch_downloads"] is True
        assert result["download_rules"] == rules
        # Unchanged defaults
        assert result["enable_library"] is True
        assert result["enable_on_demand_downloads"] is True


class TestShowSettings:
    """Tests for show library settings."""

    @pytest.mark.asyncio
    async def test_get_show_settings_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default show settings."""
        result = await system_settings.get_library_settings("shows")

        assert result["enable_library"] is True
        assert result["library_path"] == "/library/shows"
        assert result["hide_season_zero"] is False

    @pytest.mark.asyncio
    async def test_update_show_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating show settings."""
        result = await system_settings.update_library_settings(
            "shows",
            hide_season_zero=True,
            library_path="/custom/shows",
        )

        assert result["hide_season_zero"] is True
        assert result["library_path"] == "/custom/shows"


class TestMusicSettings:
    """Tests for music library settings."""

    @pytest.mark.asyncio
    async def test_get_music_settings_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default music settings."""
        result = await system_settings.get_library_settings("music")

        assert result["enable_library"] is True
        assert result["library_path"] == "/library/music"

    @pytest.mark.asyncio
    async def test_update_music_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating music settings."""
        result = await system_settings.update_library_settings(
            "music",
            enable_library=False,
            library_path="/custom/music",
        )

        assert result["enable_library"] is False
        assert result["library_path"] == "/custom/music"


class TestBooksSettings:
    """Tests for books library settings."""

    @pytest.mark.asyncio
    async def test_get_books_settings_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default books settings."""
        result = await system_settings.get_library_settings("books")

        assert result["enable_library"] is True
        assert result["library_path"] == "/library/books"

    @pytest.mark.asyncio
    async def test_update_books_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating books settings."""
        result = await system_settings.update_library_settings(
            "books",
            enable_library=False,
            library_path="/custom/books",
        )

        assert result["enable_library"] is False
        assert result["library_path"] == "/custom/books"


class TestGamesSettings:
    """Tests for games library settings."""

    @pytest.mark.asyncio
    async def test_get_games_settings_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default games settings."""
        result = await system_settings.get_library_settings("games")

        assert result["enable_library"] is True
        assert result["library_path"] == "/library/games"

    @pytest.mark.asyncio
    async def test_update_games_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating games settings."""
        result = await system_settings.update_library_settings(
            "games",
            library_path="/custom/games",
        )

        assert result["library_path"] == "/custom/games"
        assert result["enable_library"] is True  # unchanged


class TestMetadataSettings:
    """Tests for metadata provider settings."""

    @pytest.mark.asyncio
    async def test_get_metadata_settings_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default metadata settings."""
        result = await system_settings.get_metadata_settings()

        assert result["tmdb_api_key"] is None
        assert result["igdb_client_id"] is None
        assert result["igdb_client_secret"] is None
        assert result["spotify_client_id"] is None
        assert result["spotify_client_secret"] is None
        assert result["locale"] == "de-DE"

    @pytest.mark.asyncio
    async def test_update_metadata_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating metadata settings."""
        result = await system_settings.update_metadata_settings(
            tmdb_api_key="tmdb-key-123",
            igdb_client_id="igdb-id",
            igdb_client_secret="igdb-secret",
            locale="en-US",
        )

        assert result["tmdb_api_key"] == "tmdb-key-123"
        assert result["igdb_client_id"] == "igdb-id"
        assert result["igdb_client_secret"] == "igdb-secret"
        assert result["locale"] == "en-US"
        # Unchanged
        assert result["spotify_client_id"] is None


class TestEmailSettings:
    """Tests for email settings."""

    @pytest.mark.asyncio
    async def test_get_email_settings_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default email settings."""
        result = await system_settings.get_email_settings()

        assert result["enabled"] is False
        assert result["smtp_host"] == "localhost"
        assert result["smtp_port"] == 587
        assert result["smtp_use_tls"] is True
        assert result["smtp_use_ssl"] is False
        assert result["from_email"] == "noreply@pyrate.media"
        assert result["from_name"] == "Pyrate Media"

    @pytest.mark.asyncio
    async def test_update_email_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating email settings."""
        result = await system_settings.update_email_settings(
            enabled=True,
            smtp_host="smtp.gmail.com",
            smtp_port=465,
            smtp_user="user@gmail.com",
            smtp_password="secret",
            smtp_use_ssl=True,
            smtp_use_tls=False,
        )

        assert result["enabled"] is True
        assert result["smtp_host"] == "smtp.gmail.com"
        assert result["smtp_port"] == 465
        assert result["smtp_user"] == "user@gmail.com"
        assert result["smtp_password"] == "secret"
        assert result["smtp_use_ssl"] is True
        assert result["smtp_use_tls"] is False


class TestTranscodingSettings:
    """Tests for transcoding settings."""

    @pytest.mark.asyncio
    async def test_get_transcoding_settings_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default transcoding settings."""
        result = await system_settings.get_transcoding_settings()

        assert result["enabled"] is False
        assert result["max_resolution"] == "1080p"
        assert result["hardware_acceleration"] is False
        assert result["hardware_acceleration_device"] is None
        assert result["ffmpeg_image"] == "lscr.io/linuxserver/ffmpeg:latest"

    @pytest.mark.asyncio
    async def test_update_transcoding_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating transcoding settings."""
        result = await system_settings.update_transcoding_settings(
            enabled=True,
            max_resolution="4k",
            hardware_acceleration=True,
            hardware_acceleration_device="/dev/dri/renderD128",
            ffmpeg_image="custom/ffmpeg:7.0",
        )

        assert result["enabled"] is True
        assert result["max_resolution"] == "4k"
        assert result["hardware_acceleration"] is True
        assert result["hardware_acceleration_device"] == "/dev/dri/renderD128"
        assert result["ffmpeg_image"] == "custom/ffmpeg:7.0"


class TestInviteSettings:
    """Tests for invite settings."""

    @pytest.mark.asyncio
    async def test_get_invite_settings_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default invite settings."""
        result = await system_settings.get_invite_settings()

        assert result["enabled"] is True
        assert result["default_expiry_hours"] == 72
        assert result["max_expiry_hours"] == 168
        assert result["allow_multiple_uses"] is False
        assert result["require_admin_creation"] is False

    @pytest.mark.asyncio
    async def test_update_invite_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating invite settings."""
        result = await system_settings.update_invite_settings(
            enabled=False,
            default_expiry_hours=24,
            require_admin_creation=True,
        )

        assert result["enabled"] is False
        assert result["default_expiry_hours"] == 24
        assert result["require_admin_creation"] is True
        # Unchanged
        assert result["max_expiry_hours"] == 168


class TestNamingSettings:
    """Tests for naming template settings."""

    @pytest.mark.asyncio
    async def test_get_show_naming_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default show naming settings."""
        result = await system_settings.get_naming_settings("shows")

        assert result["series_folder"] == "{series_title} ({series_year})"
        assert result["season_folder"] == "Season {season_number_2}"
        assert result["multi_episode_style"] == "extend"
        assert result["replace_illegal_characters"] is True
        assert result["colon_replacement"] == " -"

    @pytest.mark.asyncio
    async def test_update_show_naming_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating show naming settings."""
        result = await system_settings.update_naming_settings(
            "shows",
            series_folder="{series_title}",
            season_folder="S{season_number_2}",
            colon_replacement="_",
        )

        assert result["series_folder"] == "{series_title}"
        assert result["season_folder"] == "S{season_number_2}"
        assert result["colon_replacement"] == "_"

    @pytest.mark.asyncio
    async def test_get_movie_naming_defaults(
        self, system_settings: SystemSettingsService
    ):
        """Test default movie naming settings."""
        result = await system_settings.get_naming_settings("movies")

        assert result["folder"] == "{movie_title} ({movie_year})"
        assert result["file"] == "{movie_title} ({movie_year})"
        assert result["replace_illegal_characters"] is True
        assert result["colon_replacement"] == " -"

    @pytest.mark.asyncio
    async def test_update_movie_naming_settings(
        self, system_settings: SystemSettingsService
    ):
        """Test updating movie naming settings."""
        result = await system_settings.update_naming_settings(
            "movies",
            folder="{movie_title} [{movie_year}]",
            file="{movie_title}",
        )

        assert result["folder"] == "{movie_title} [{movie_year}]"
        assert result["file"] == "{movie_title}"
        assert result["replace_illegal_characters"] is True  # unchanged


class TestSettingsIntegration:
    """Integration tests across multiple setting categories."""

    @pytest.mark.asyncio
    async def test_settings_isolation(self, system_settings: SystemSettingsService):
        """Test that different setting categories don't interfere with each other."""
        # Update movie settings
        await system_settings.update_library_settings("movies", library_path="/movies")
        # Update show settings
        await system_settings.update_library_settings("shows", library_path="/shows")

        movies = await system_settings.get_library_settings("movies")
        shows = await system_settings.get_library_settings("shows")

        assert movies["library_path"] == "/movies"
        assert shows["library_path"] == "/shows"

    @pytest.mark.asyncio
    async def test_full_settings_roundtrip(
        self, system_settings: SystemSettingsService
    ):
        """Test a full get-update-get cycle across all settings categories."""
        # Disable all optional features
        await system_settings.update_libraries_enabled(
            movies_enabled=True,
            shows_enabled=True,
            music_enabled=False,
            books_enabled=False,
            games_enabled=False,
        )
        await system_settings.update_email_settings(enabled=True)
        await system_settings.update_transcoding_settings(enabled=True)
        await system_settings.update_invite_settings(enabled=False)

        # Verify all changes persisted
        libs = await system_settings.get_libraries_enabled()
        assert libs["movies_enabled"] is True
        assert libs["music_enabled"] is False
        assert libs["books_enabled"] is False

        email = await system_settings.get_email_settings()
        assert email["enabled"] is True

        transcoding = await system_settings.get_transcoding_settings()
        assert transcoding["enabled"] is True

        invites = await system_settings.get_invite_settings()
        assert invites["enabled"] is False
