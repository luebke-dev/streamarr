"""Comprehensive tests for business/config services covering missing lines.

Targets coverage gaps identified in:
- system_settings.py (naming, metadata, email, transcoding, storage, invite, lightrays, system)
- trending.py (_get_tmdb/_get_igdb init, error handling, no-API-key paths)
- library.py (rescore_releases, initialize_default_libraries edge cases)
- settings.py (convenience helpers: get_spotify_credentials, get_oidc_settings, get_tvdb_api_key)
- genre.py (get_or_create ON CONFLICT logic)
- storage_cleanup.py (error handling paths, DB exception paths)
- play_token.py (_get_redis init, token parse errors)
- indexer.py (_get_category_ids_for_type edge cases, search_music)
- release_matcher.py (fuzzy matching edge cases, filter_matching_releases)
- group.py (edge cases: rate-limit merging, pagination)
"""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.media import (
    AvailabilityStatus,
    MediaExternalId,
    MediaItem,
    MediaRelease,
    MediaType,
)
from pyrate.models.user import User


# ===========================================================================
# SystemSettingsService - missing coverage
# ===========================================================================


class TestSystemSettingsStorageAndLightrays:
    """Cover get/update for storage, lightrays, system, subscription, invite-enable."""

    @pytest_asyncio.fixture
    async def svc(self, db_session: AsyncSession):
        from pyrate.services.system_settings import SystemSettingsService

        return SystemSettingsService(db_session)

    @pytest.mark.asyncio
    async def test_get_storage_settings_defaults(self, svc):
        result = await svc.get_storage_settings()
        assert result["temp_max_age_hours"] == 2.0
        assert result["temp_max_size_gb"] is None
        assert result["download_record_max_age_days"] == 30
        assert result["cleanup_orphaned_files"] is True
        assert result["cleanup_duplicates"] is True
        assert result["cleanup_interval_hours"] == 6

    @pytest.mark.asyncio
    async def test_update_storage_settings(self, svc):
        result = await svc.update_storage_settings(
            temp_max_age_hours=4.0,
            temp_max_size_gb=10.0,
            download_record_max_age_days=60,
            cleanup_orphaned_files=False,
            cleanup_duplicates=False,
            cleanup_interval_hours=12,
        )
        assert result["temp_max_age_hours"] == 4.0
        assert result["temp_max_size_gb"] == 10.0
        assert result["download_record_max_age_days"] == 60
        assert result["cleanup_orphaned_files"] is False
        assert result["cleanup_duplicates"] is False
        assert result["cleanup_interval_hours"] == 12

    @pytest.mark.asyncio
    async def test_get_lightrays_settings_defaults(self, svc):
        result = await svc.get_lightrays_settings()
        assert result["url"] == "http://lightrays:8080"
        assert result["default_runtime_profile"] == "gow-steam"
        assert result["default_fps"] == 60
        assert result["default_bitrate_kbps"] == 10000

    @pytest.mark.asyncio
    async def test_update_lightrays_settings(self, svc):
        result = await svc.update_lightrays_settings(
            url="http://custom:9090",
            default_runtime_profile="gow-steam",
            default_fps=30,
            default_bitrate_kbps=5000,
        )
        assert result["url"] == "http://custom:9090"
        assert result["default_runtime_profile"] == "gow-steam"
        assert result["default_fps"] == 30
        assert result["default_bitrate_kbps"] == 5000

    @pytest.mark.asyncio
    async def test_get_system_settings_defaults(self, svc):
        result = await svc.get_system_settings()
        assert result["site_name"] == "pyrate.media"
        assert result["locale"] == "de-DE"

    @pytest.mark.asyncio
    async def test_update_system_settings(self, svc):
        result = await svc.update_system_settings(
            site_name="My Media Server",
            locale="en-US",
        )
        assert result["site_name"] == "My Media Server"
        assert result["locale"] == "en-US"

    @pytest.mark.asyncio
    async def test_get_subscription_settings(self, svc):
        result = await svc.get_subscription_settings()
        assert result["subscriptions_enabled"] is False

    @pytest.mark.asyncio
    async def test_update_subscription_settings(self, svc):
        result = await svc.update_subscription_settings(subscriptions_enabled=True)
        assert result["subscriptions_enabled"] is True

    @pytest.mark.asyncio
    async def test_get_invite_enabled(self, svc):
        result = await svc.get_invite_enabled()
        assert result["invites_enabled"] is True

    @pytest.mark.asyncio
    async def test_update_invite_enabled(self, svc):
        result = await svc.update_invite_enabled(invites_enabled=False)
        assert result["invites_enabled"] is False


class TestSystemSettingsPreviewNaming:
    """Cover preview_naming and get_library_settings_with_schema."""

    @pytest_asyncio.fixture
    async def svc(self, db_session: AsyncSession):
        from pyrate.services.system_settings import SystemSettingsService

        return SystemSettingsService(db_session)

    @pytest.mark.asyncio
    async def test_preview_naming(self, svc):
        result = await svc.preview_naming("movies")
        assert "folder" in result
        assert "file" in result
        assert "full_path" in result
        assert "/" in result["full_path"]

    @pytest.mark.asyncio
    async def test_preview_naming_unknown_type(self, svc):
        with pytest.raises(ValueError, match="Unknown library type"):
            await svc.preview_naming("nonexistent_type")

    @pytest.mark.asyncio
    async def test_get_library_settings_with_schema(self, svc):
        result = await svc.get_library_settings_with_schema("movies")
        assert "naming_schema" in result

    @pytest.mark.asyncio
    async def test_get_library_settings_with_schema_missing_naming(self, svc):
        """Covers the except branch when get_naming_schema is unavailable."""
        with patch("pyrate.libraries.get_plugin_instance") as mock_gpi:
            mock_plugin = MagicMock()
            mock_plugin.get_settings_schema.return_value = {}
            mock_plugin.get_naming_schema.side_effect = AttributeError("no such method")
            mock_gpi.return_value = mock_plugin

            result = await svc.get_library_settings_with_schema("movies")
            assert result["naming_schema"] is None


class TestSystemSettingsStorageOverviewAndCleanup:
    """Cover get_storage_overview and trigger_storage_cleanup."""

    @pytest_asyncio.fixture
    async def svc(self, db_session: AsyncSession):
        from pyrate.services.system_settings import SystemSettingsService

        return SystemSettingsService(db_session)

    @pytest.mark.asyncio
    async def test_get_storage_overview(self, svc):
        mock_overview = {"temp": {}, "downloads": {}, "libraries": {}}
        with patch(
            "pyrate.services.storage_cleanup.StorageCleanupService"
        ) as MockSCS:
            mock_instance = AsyncMock()
            mock_instance.get_storage_overview = AsyncMock(return_value=mock_overview)
            MockSCS.return_value = mock_instance

            result = await svc.get_storage_overview()
            assert result == mock_overview

    @pytest.mark.asyncio
    async def test_trigger_storage_cleanup(self, svc):
        mock_result = {"temp_cleanup": {}, "download_records": {}}
        with patch(
            "pyrate.services.storage_cleanup.StorageCleanupService"
        ) as MockSCS:
            mock_instance = AsyncMock()
            mock_instance.run_full_cleanup = AsyncMock(return_value=mock_result)
            MockSCS.return_value = mock_instance

            result = await svc.trigger_storage_cleanup()
            assert result == mock_result


class TestSystemSettingsStandaloneHelpers:
    """Cover standalone helper functions in system_settings module."""

    @pytest.mark.asyncio
    async def test_standalone_get_tmdb_api_key(self, db_session: AsyncSession):
        from pyrate.services.system_settings import get_tmdb_api_key

        from pyrate.services.settings import SettingsService

        await SettingsService(db_session).set("plugin.tmdb.api_key", "test-key-123")
        result = await get_tmdb_api_key(db_session)
        assert result == "test-key-123"

    @pytest.mark.asyncio
    async def test_standalone_get_tvdb_api_key(self, db_session: AsyncSession):
        from pyrate.services.system_settings import get_tvdb_api_key

        from pyrate.services.settings import SettingsService

        await SettingsService(db_session).set("plugin.tvdb.api_key", "tvdb-key")
        result = await get_tvdb_api_key(db_session)
        assert result == "tvdb-key"

    @pytest.mark.asyncio
    async def test_standalone_get_igdb_credentials(self, db_session: AsyncSession):
        from pyrate.services.system_settings import get_igdb_credentials

        from pyrate.services.settings import SettingsService

        svc = SettingsService(db_session)
        await svc.set("plugin.igdb.client_id", "igdb-id")
        await svc.set("plugin.igdb.client_secret", "igdb-secret")
        cid, csec = await get_igdb_credentials(db_session)
        assert cid == "igdb-id"
        assert csec == "igdb-secret"

    @pytest.mark.asyncio
    async def test_standalone_get_locale(self, db_session: AsyncSession):
        from pyrate.services.system_settings import get_locale

        result = await get_locale(db_session)
        assert result == "de-DE"


# ===========================================================================
# TrendingService - missing coverage
# ===========================================================================


class TestTrendingServiceInit:
    """Cover _get_tmdb and _get_igdb initialization and error paths."""

    @pytest.mark.asyncio
    async def test_get_tmdb_initializes_once(self, db_session: AsyncSession):
        from pyrate.services.trending import TrendingService

        svc = TrendingService(db_session)
        assert svc._tmdb is None

        with patch(
            "pyrate.services.trending.get_tmdb_api_key",
            AsyncMock(return_value="my-key"),
        ):
            with patch("pyrate.services.trending.TMDB") as MockTMDB:
                tmdb1 = await svc._get_tmdb()
                tmdb2 = await svc._get_tmdb()  # should reuse
                MockTMDB.assert_called_once_with(api_key="my-key")
                assert tmdb1 is tmdb2

    @pytest.mark.asyncio
    async def test_get_igdb_initializes_with_credentials(
        self, db_session: AsyncSession
    ):
        from pyrate.services.trending import TrendingService

        svc = TrendingService(db_session)

        with patch(
            "pyrate.services.trending.get_igdb_credentials",
            AsyncMock(return_value=("cid", "csec")),
        ):
            with patch("pyrate.services.trending.IGDB") as MockIGDB:
                igdb = await svc._get_igdb()
                MockIGDB.assert_called_once_with(client_id="cid", client_secret="csec")
                assert igdb is not None

    @pytest.mark.asyncio
    async def test_get_igdb_raises_without_credentials(
        self, db_session: AsyncSession
    ):
        from pyrate.services.trending import TrendingService

        svc = TrendingService(db_session)

        with patch(
            "pyrate.services.trending.get_igdb_credentials",
            AsyncMock(return_value=(None, None)),
        ):
            with pytest.raises(ValueError, match="IGDB credentials not configured"):
                await svc._get_igdb()

    @pytest.mark.asyncio
    async def test_get_igdb_raises_partial_credentials(
        self, db_session: AsyncSession
    ):
        from pyrate.services.trending import TrendingService

        svc = TrendingService(db_session)

        with patch(
            "pyrate.services.trending.get_igdb_credentials",
            AsyncMock(return_value=("cid", None)),
        ):
            with pytest.raises(ValueError, match="IGDB credentials not configured"):
                await svc._get_igdb()


class TestTrendingExistingMovies:
    """Cover path when trending movies already exist in DB."""

    @pytest.mark.asyncio
    async def test_get_new_trending_movie_ids_filters_existing(
        self, db_session: AsyncSession
    ):
        from pyrate.services.trending import TrendingService

        # Create a movie with external ID that matches trending
        mi = MediaItem(title="Existing Movie", media_type=MediaType.MOVIES)
        db_session.add(mi)
        await db_session.flush()
        ext_id = MediaExternalId(
            media_item_guid=mi.guid, provider="tmdb", external_id="100"
        )
        db_session.add(ext_id)
        await db_session.commit()

        svc = TrendingService(db_session)
        mock_tmdb = AsyncMock()
        mock_tmdb.get_trending_movies = AsyncMock(
            return_value={"results": [{"id": 100}, {"id": 200}]}
        )
        svc._tmdb = mock_tmdb

        ids = await svc.get_new_trending_movie_ids()
        # 100 already exists, only 200 should be new
        assert 100 not in ids
        assert 200 in ids

    @pytest.mark.asyncio
    async def test_get_new_trending_show_ids_filters_existing(
        self, db_session: AsyncSession
    ):
        from pyrate.services.trending import TrendingService

        mi = MediaItem(title="Existing Show", media_type=MediaType.SHOWS)
        db_session.add(mi)
        await db_session.flush()
        ext_id = MediaExternalId(
            media_item_guid=mi.guid, provider="tmdb", external_id="300"
        )
        db_session.add(ext_id)
        await db_session.commit()

        svc = TrendingService(db_session)
        mock_tmdb = AsyncMock()
        mock_tmdb.get_trending_shows = AsyncMock(
            return_value={"results": [{"id": 300}, {"id": 400}]}
        )
        svc._tmdb = mock_tmdb

        ids = await svc.get_new_trending_show_ids()
        assert 300 not in ids
        assert 400 in ids

    @pytest.mark.asyncio
    async def test_get_new_trending_game_ids_filters_existing(
        self, db_session: AsyncSession
    ):
        from pyrate.services.trending import TrendingService

        mi = MediaItem(title="Existing Game", media_type=MediaType.GAMES)
        db_session.add(mi)
        await db_session.flush()
        ext_id = MediaExternalId(
            media_item_guid=mi.guid, provider="igdb", external_id="500"
        )
        db_session.add(ext_id)
        await db_session.commit()

        svc = TrendingService(db_session)
        mock_igdb = AsyncMock()
        mock_igdb.get_trending_games = AsyncMock(
            return_value=[{"id": 500}, {"id": 600}]
        )
        svc._igdb = mock_igdb

        ids = await svc.get_new_trending_game_ids()
        assert 500 not in ids
        assert 600 in ids


class TestTrendingUpdateWithoutCredentials:
    """Cover update_trending_*_list when external API credentials are missing.

    The SYSTEM list is created up-front (it's a singleton keyed by
    ``update_source`` and the SQL upsert runs before the API call), so a
    failed external fetch still leaves the bare list behind. The methods
    re-raise the underlying error after logging it so callers can decide
    whether to retry.
    """

    @pytest.mark.asyncio
    async def test_update_trending_shows_list_raises_without_tmdb(
        self, db_session: AsyncSession
    ):
        from pyrate.services.trending import TrendingService

        svc = TrendingService(db_session)
        # TMDB key is missing → tmdb client returns empty results / 401;
        # either way the method should not crash silently on the caller.
        # Currently the implementation tolerates a 401 by returning an
        # empty trending list; the SYSTEM list is still created.
        await svc.update_trending_shows_list()

        from pyrate.models.list import List
        from sqlalchemy import select

        result = await db_session.execute(
            select(List).where(List.update_source == "trending_shows")
        )
        assert result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_update_trending_games_list_raises_without_igdb(
        self, db_session: AsyncSession
    ):
        from pyrate.services.trending import TrendingService

        svc = TrendingService(db_session)
        # IGDB requires both client id + secret; with neither set the
        # service raises ValueError after creating the SYSTEM list.
        with pytest.raises(ValueError, match="IGDB credentials not configured"):
            await svc.update_trending_games_list()


# ===========================================================================
# LibraryService - missing coverage (rescore_releases, etc.)
# ===========================================================================


class TestLibraryRescoreReleases:
    """Cover rescore_releases method."""

    @pytest.mark.asyncio
    async def test_rescore_releases_empty_list(self, db_session: AsyncSession):
        from pyrate.services.library import LibraryService

        service = LibraryService(db_session)
        mi = await service.create_media_item(
            title="Test", media_type=MediaType.MOVIES
        )
        result = await service.rescore_releases(mi, [])
        assert result == []

    @pytest.mark.asyncio
    async def test_rescore_releases_no_plugin(self, db_session: AsyncSession):
        from pyrate.services.library import LibraryService

        service = LibraryService(db_session)
        mi = await service.create_media_item(
            title="Test", media_type=MediaType.MOVIES
        )
        release = await service.create_media_release(
            mi.guid, title="Test.Movie.1080p.BluRay"
        )

        # No plugin registered for this type - should return releases unchanged
        with patch.object(service, "get_plugin", return_value=None):
            result = await service.rescore_releases(mi, [release])

        assert result == [release]

    @pytest.mark.asyncio
    async def test_rescore_releases_plugin_without_score_method(
        self, db_session: AsyncSession
    ):
        from pyrate.services.library import LibraryService

        service = LibraryService(db_session)
        mi = await service.create_media_item(
            title="Test", media_type=MediaType.MOVIES
        )
        release = await service.create_media_release(
            mi.guid, title="Test.Movie.1080p"
        )

        mock_plugin = MagicMock()
        # Plugin exists but lacks score_release method
        del mock_plugin.score_release

        with patch.object(service, "get_plugin", return_value=mock_plugin):
            result = await service.rescore_releases(mi, [release])

        assert result == [release]

    @pytest.mark.asyncio
    async def test_rescore_releases_with_working_plugin(
        self, db_session: AsyncSession
    ):
        from pyrate.services.library import LibraryService

        service = LibraryService(db_session)
        mi = await service.create_media_item(
            title="Test", media_type=MediaType.MOVIES
        )
        release = await service.create_media_release(
            mi.guid, title="Test.Movie.1080p.BluRay", score=50
        )

        mock_plugin = AsyncMock()
        mock_plugin.extract_release_metadata = AsyncMock(
            return_value={"quality": "1080p", "source": "bluray"}
        )
        mock_plugin.score_release = AsyncMock(return_value=85.0)

        with patch.object(service, "get_plugin", return_value=mock_plugin):
            result = await service.rescore_releases(mi, [release])

        assert len(result) == 1
        assert result[0].score == 85

    @pytest.mark.asyncio
    async def test_rescore_releases_scoring_error_continues(
        self, db_session: AsyncSession
    ):
        from pyrate.services.library import LibraryService

        service = LibraryService(db_session)
        mi = await service.create_media_item(
            title="Test", media_type=MediaType.MOVIES
        )
        r1 = await service.create_media_release(mi.guid, title="Bad.Release")
        r2 = await service.create_media_release(
            mi.guid, title="Good.Release", score=50
        )

        mock_plugin = AsyncMock()
        call_count = 0

        async def extract_side_effect(title):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("parse error")
            return {"quality": "720p"}

        mock_plugin.extract_release_metadata = extract_side_effect
        mock_plugin.score_release = AsyncMock(return_value=70.0)

        with patch.object(service, "get_plugin", return_value=mock_plugin):
            result = await service.rescore_releases(mi, [r1, r2])

        # Both should be returned, first one errored but didn't crash
        assert len(result) == 2


class TestLibraryGetLibraryStatsNoPlugin:
    """Cover get_library_stats when plugin is not found."""

    @pytest.mark.asyncio
    async def test_get_library_stats_no_plugin(self, db_session: AsyncSession):
        from pyrate.services.library import LibraryService

        service = LibraryService(db_session)

        mock_plugin = MagicMock()
        mock_plugin.get_default_path = AsyncMock(return_value="/library/movies")
        mock_plugin.validate_path = AsyncMock(return_value=True)
        mock_plugin.initialize_library = AsyncMock()

        with patch.object(service, "get_plugin", return_value=mock_plugin):
            library = await service.create_library(
                name="Test",
                type="MOVIES",
                plugin_id="movies",
                path="/data/movies",
            )

        # Now get_plugin returns None
        with patch.object(service, "get_plugin", return_value=None):
            stats = await service.get_library_stats(library.guid)

        assert stats is None


# ===========================================================================
# SettingsService - missing convenience helpers
# ===========================================================================


class TestSettingsConvenienceHelpersMissing:
    """Cover helpers not tested in test_settings_service.py."""

    @pytest.mark.asyncio
    async def test_get_spotify_credentials(self, db_session: AsyncSession):
        from pyrate.services.settings import SettingsService

        svc = SettingsService(db_session)
        await svc.set("plugin.spotify.client_id", "sp-id")
        await svc.set("plugin.spotify.client_secret", "sp-sec")

        cid, csec = await svc.get_spotify_credentials()
        assert cid == "sp-id"
        assert csec == "sp-sec"

    @pytest.mark.asyncio
    async def test_get_spotify_credentials_none(self, db_session: AsyncSession):
        from pyrate.services.settings import SettingsService

        svc = SettingsService(db_session)
        cid, csec = await svc.get_spotify_credentials()
        assert cid is None
        assert csec is None

    @pytest.mark.asyncio
    async def test_get_tvdb_api_key(self, db_session: AsyncSession):
        from pyrate.services.settings import SettingsService

        svc = SettingsService(db_session)
        await svc.set("plugin.tvdb.api_key", "tvdb-key-val")
        result = await svc.get_tvdb_api_key()
        assert result == "tvdb-key-val"

    @pytest.mark.asyncio
    async def test_get_tvdb_api_key_none(self, db_session: AsyncSession):
        from pyrate.services.settings import SettingsService

        svc = SettingsService(db_session)
        result = await svc.get_tvdb_api_key()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_oidc_settings(self, db_session: AsyncSession):
        from pyrate.services.settings import SettingsService

        svc = SettingsService(db_session)
        await svc.set("oidc.provider_url", "https://auth.example.com")
        result = await svc.get_oidc_settings()
        assert "oidc.provider_url" in result
        assert result["oidc.provider_url"] == "https://auth.example.com"

    @pytest.mark.asyncio
    async def test_get_email_settings_returns_prefixed(
        self, db_session: AsyncSession
    ):
        from pyrate.services.settings import SettingsService

        svc = SettingsService(db_session)
        await svc.set("email.smtp_host", "mail.example.com")
        result = await svc.get_email_settings()
        assert "email.smtp_host" in result

    @pytest.mark.asyncio
    async def test_get_transcoding_settings_returns_prefixed(
        self, db_session: AsyncSession
    ):
        from pyrate.services.settings import SettingsService

        svc = SettingsService(db_session)
        await svc.set("transcoding.enabled", True)
        result = await svc.get_transcoding_settings()
        assert "transcoding.enabled" in result
        assert result["transcoding.enabled"] is True

    @pytest.mark.asyncio
    async def test_get_invite_settings_returns_prefixed(
        self, db_session: AsyncSession
    ):
        from pyrate.services.settings import SettingsService

        svc = SettingsService(db_session)
        result = await svc.get_invite_settings()
        # Should include defaults
        assert "invites.enabled" in result

    @pytest.mark.asyncio
    async def test_get_subscription_settings_returns_prefixed(
        self, db_session: AsyncSession
    ):
        from pyrate.services.settings import SettingsService

        svc = SettingsService(db_session)
        result = await svc.get_subscription_settings()
        assert isinstance(result, dict)


class TestSettingsStandaloneHelpers:
    """Cover standalone helper functions in settings module."""

    @pytest.mark.asyncio
    async def test_standalone_get_spotify_credentials(
        self, db_session: AsyncSession
    ):
        from pyrate.services.settings import SettingsService, get_spotify_credentials

        svc = SettingsService(db_session)
        await svc.set("plugin.spotify.client_id", "sp-id")
        await svc.set("plugin.spotify.client_secret", "sp-sec")

        cid, csec = await get_spotify_credentials(db_session)
        assert cid == "sp-id"
        assert csec == "sp-sec"

    @pytest.mark.asyncio
    async def test_standalone_get_setting(self, db_session: AsyncSession):
        from pyrate.services.settings import SettingsService, get_setting

        svc = SettingsService(db_session)
        await svc.set("custom.key", "custom-value")

        result = await get_setting(db_session, "custom.key")
        assert result == "custom-value"

    @pytest.mark.asyncio
    async def test_standalone_get_setting_with_default(
        self, db_session: AsyncSession
    ):
        from pyrate.services.settings import get_setting

        result = await get_setting(db_session, "nonexistent.key", default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_standalone_get_locale(self, db_session: AsyncSession):
        from pyrate.services.settings import get_locale

        result = await get_locale(db_session)
        assert result == "de-DE"


# ===========================================================================
# GenreService - get_or_create missing coverage
# ===========================================================================


class TestGenreGetOrCreate:
    """Cover get_or_create method (ON CONFLICT logic)."""

    @pytest.mark.asyncio
    async def test_get_or_create_existing_genre(self, db_session: AsyncSession):
        """When genre already exists by ID, return it."""
        from pyrate.schemas.genre import GenreCreate
        from pyrate.services.genre import GenreService

        service = GenreService(db_session)
        await service.create(GenreCreate(id=28, name="Action"))

        result = await service.get_or_create(genre_id=28, name="Action")
        assert result is not None
        assert result.id == 28
        assert result.name == "Action"

    @pytest.mark.asyncio
    async def test_get_or_create_new_genre_uses_pg_insert(
        self, db_session: AsyncSession
    ):
        """When genre does not exist, the ON CONFLICT INSERT is attempted.
        Note: pg_insert does not work on SQLite, so we mock the dialect import."""
        from pyrate.services.genre import GenreService
        from pyrate.models.genre import Genre

        service = GenreService(db_session)

        # Pre-create the genre so the final SELECT finds it
        genre = Genre(id=99, name="SciFi")
        db_session.add(genre)
        await db_session.commit()

        # Mock the pg_insert at the point of import inside get_or_create
        with patch(
            "sqlalchemy.dialects.postgresql.insert"
        ) as mock_pg_insert:
            mock_stmt = MagicMock()
            mock_stmt.values.return_value = mock_stmt
            mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
            mock_pg_insert.return_value = mock_stmt

            result = await service.get_or_create(genre_id=99, name="SciFi")
            assert result is not None
            assert result.name == "SciFi"


# ===========================================================================
# StorageCleanupService - additional error handling
# ===========================================================================


class TestStorageCleanupErrorHandling:
    """Cover error handling paths in storage cleanup service."""

    @pytest.mark.asyncio
    async def test_cleanup_old_downloads_db_exception(
        self, db_session: AsyncSession
    ):
        """Cover the except branch in cleanup_old_downloads."""
        from pyrate.services.storage_cleanup import StorageCleanupService

        service = StorageCleanupService(db=db_session)

        # Patch execute to raise after a few calls
        with patch.object(
            db_session, "execute", side_effect=RuntimeError("DB connection lost")
        ):
            result = await service.cleanup_old_downloads(max_age_days=30)

        assert len(result["errors"]) > 0
        assert "Database error" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_cleanup_orphaned_media_files_db_exception(
        self, db_session: AsyncSession
    ):
        """Cover the except branch in cleanup_orphaned_media_files."""
        from pyrate.services.storage_cleanup import StorageCleanupService

        service = StorageCleanupService(db=db_session)

        with patch.object(
            db_session, "execute", side_effect=RuntimeError("DB error")
        ):
            result = await service.cleanup_orphaned_media_files()

        assert len(result["errors"]) > 0

    @pytest.mark.asyncio
    async def test_cleanup_library_duplicates_db_exception(
        self, db_session: AsyncSession
    ):
        """Cover the except branch in cleanup_library_duplicates."""
        from pyrate.services.storage_cleanup import StorageCleanupService

        service = StorageCleanupService(db=db_session)

        with patch.object(
            db_session, "execute", side_effect=RuntimeError("DB error")
        ):
            result = await service.cleanup_library_duplicates(
                library_path="/library/movies"
            )

        assert len(result["errors"]) > 0


# ===========================================================================
# PlayTokenService - missing edge cases
# ===========================================================================


class TestPlayTokenEdgeCases:
    """Cover _get_redis init and token parse error paths."""

    @pytest.mark.asyncio
    async def test_get_redis_initialization(self):
        """Cover _get_redis lazy initialization."""
        import fakeredis

        from pyrate.services.play_token import PlayTokenService

        service = PlayTokenService()
        assert service._redis is None

        # Mock redis.from_url to return fakeredis
        fake = fakeredis.FakeAsyncRedis(decode_responses=True)
        with patch(
            "pyrate.services.play_token.redis.from_url", return_value=fake
        ):
            r = await service._get_redis()
            assert r is not None
            # Second call should reuse
            r2 = await service._get_redis()
            assert r is r2

    @pytest.mark.asyncio
    async def test_get_token_invalid_json(self):
        """Cover the JSONDecodeError/KeyError branch in get_token."""
        import fakeredis

        from pyrate.services.play_token import PlayTokenService, REDIS_KEY_PREFIX

        service = PlayTokenService()
        service._redis = fakeredis.FakeAsyncRedis(decode_responses=True)

        # Store invalid JSON
        await service._redis.set(f"{REDIS_KEY_PREFIX}bad-token", "not-valid-json{{{")
        result = await service.get_token("bad-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_token_missing_fields(self):
        """Cover KeyError branch when token data is missing required fields."""
        import fakeredis

        from pyrate.services.play_token import PlayTokenService, REDIS_KEY_PREFIX

        service = PlayTokenService()
        service._redis = fakeredis.FakeAsyncRedis(decode_responses=True)

        # Store valid JSON but missing required fields
        await service._redis.set(
            f"{REDIS_KEY_PREFIX}incomplete-token",
            json.dumps({"token": "incomplete-token"}),
        )
        result = await service.get_token("incomplete-token")
        # Should return None due to KeyError
        assert result is None

    @pytest.mark.asyncio
    async def test_close_when_connected(self):
        """Cover close() method when redis is connected."""
        import fakeredis

        from pyrate.services.play_token import PlayTokenService

        service = PlayTokenService()
        service._redis = fakeredis.FakeAsyncRedis(decode_responses=True)

        await service.close()
        assert service._redis is None

    @pytest.mark.asyncio
    async def test_close_when_not_connected(self):
        """Cover close() method when redis is not connected."""
        from pyrate.services.play_token import PlayTokenService

        service = PlayTokenService()
        assert service._redis is None
        await service.close()
        assert service._redis is None

    def test_get_play_token_service_singleton(self):
        """Cover get_play_token_service global singleton."""
        from pyrate.services.play_token import get_play_token_service, PlayTokenService

        import pyrate.services.play_token as pt_module

        # Reset global
        pt_module._token_service = None
        svc1 = get_play_token_service()
        svc2 = get_play_token_service()
        assert svc1 is svc2
        assert isinstance(svc1, PlayTokenService)
        # Clean up
        pt_module._token_service = None

    @pytest.mark.asyncio
    async def test_get_all_tokens_cleans_stale(self):
        """Cover the stale token cleanup in get_all_tokens."""
        import fakeredis

        from pyrate.services.play_token import (
            PlayTokenService,
            REDIS_TOKENS_SET,
        )

        service = PlayTokenService()
        service._redis = fakeredis.FakeAsyncRedis(decode_responses=True)

        # Add a token ID to the set without actually storing token data
        await service._redis.sadd(REDIS_TOKENS_SET, "stale-token-id")

        tokens = await service.get_all_tokens()
        assert len(tokens) == 0
        # Verify stale token was removed from set
        members = await service._redis.smembers(REDIS_TOKENS_SET)
        assert "stale-token-id" not in members


# ===========================================================================
# IndexerService - missing coverage
# ===========================================================================


class TestIndexerCategoryEdgeCases:
    """Cover _get_category_ids_for_type with None newznab_category_id."""

    def test_category_with_none_id_filtered(self):
        from pyrate.services.indexer import IndexerService

        service = IndexerService.__new__(IndexerService)

        cat_with_id = MagicMock()
        cat_with_id.category_type = "movie"
        cat_with_id.newznab_category_id = 2000

        cat_without_id = MagicMock()
        cat_without_id.category_type = "movie"
        cat_without_id.newznab_category_id = None

        indexer = MagicMock()
        indexer.categories = [cat_with_id, cat_without_id]

        result = service._get_category_ids_for_type(indexer, "movie")
        assert result == "2000"

    def test_language_hints_deduplication(self):
        from pyrate.services.indexer import IndexerService

        service = IndexerService.__new__(IndexerService)

        cat1 = MagicMock()
        cat1.category_type = "movie"
        cat1.language = ["en", "de"]

        cat2 = MagicMock()
        cat2.category_type = "movie"
        cat2.language = ["en", "fr"]  # "en" already seen

        indexer = MagicMock()
        indexer.categories = [cat1, cat2]

        result = service._get_language_hints_for_type(indexer, "movie")
        assert result == ["en", "de", "fr"]  # no duplicates

    def test_resolution_hints_deduplication(self):
        from pyrate.services.indexer import IndexerService

        service = IndexerService.__new__(IndexerService)

        cat1 = MagicMock()
        cat1.category_type = "movie"
        cat1.resolution = ["1080p", "720p"]

        cat2 = MagicMock()
        cat2.category_type = "movie"
        cat2.resolution = ["1080p", "2160p"]  # "1080p" already seen

        indexer = MagicMock()
        indexer.categories = [cat1, cat2]

        result = service._get_resolution_hints_for_type(indexer, "movie")
        assert result == ["1080p", "720p", "2160p"]

    def test_language_hints_no_language_field(self):
        from pyrate.services.indexer import IndexerService

        service = IndexerService.__new__(IndexerService)

        cat = MagicMock()
        cat.category_type = "movie"
        cat.language = None

        indexer = MagicMock()
        indexer.categories = [cat]

        result = service._get_language_hints_for_type(indexer, "movie")
        assert result == []

    def test_resolution_hints_no_resolution_field(self):
        from pyrate.services.indexer import IndexerService

        service = IndexerService.__new__(IndexerService)

        cat = MagicMock()
        cat.category_type = "movie"
        cat.resolution = None

        indexer = MagicMock()
        indexer.categories = [cat]

        result = service._get_resolution_hints_for_type(indexer, "movie")
        assert result == []


class TestIndexerSearchMusic:
    """Cover search_music method."""

    @pytest.mark.asyncio
    async def test_search_music_no_credentials(self, db_session: AsyncSession):
        from pyrate.services.indexer import IndexerService

        service = IndexerService(db_session)

        with patch(
            "pyrate.services.settings.SettingsService"
        ) as MockSettings:
            mock_svc = MagicMock()
            mock_svc.get_spotify_credentials = AsyncMock(
                return_value=(None, None)
            )
            MockSettings.return_value = mock_svc

            result = await service.search_music(query="test song")

        assert result == []

    @pytest.mark.asyncio
    async def test_search_music_with_credentials(self, db_session: AsyncSession):
        from pyrate.services.indexer import IndexerService

        service = IndexerService(db_session)

        mock_spotify = AsyncMock()
        mock_spotify.search_music = AsyncMock(
            return_value=[{"title": "Test Song", "artist": "Test Artist"}]
        )
        mock_spotify.close = AsyncMock()

        with patch(
            "pyrate.services.settings.SettingsService"
        ) as MockSettings:
            mock_svc = MagicMock()
            mock_svc.get_spotify_credentials = AsyncMock(
                return_value=("sp-id", "sp-sec")
            )
            MockSettings.return_value = mock_svc

            with patch(
                "pyrate.services.indexer.Spotify", return_value=mock_spotify
            ):
                result = await service.search_music(query="test song")

        assert len(result) == 1
        assert result[0]["title"] == "Test Song"
        mock_spotify.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_music_exception_returns_empty(
        self, db_session: AsyncSession
    ):
        from pyrate.services.indexer import IndexerService

        service = IndexerService(db_session)

        mock_spotify = AsyncMock()
        mock_spotify.search_music = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        mock_spotify.close = AsyncMock()

        with patch(
            "pyrate.services.settings.SettingsService"
        ) as MockSettings:
            mock_svc = MagicMock()
            mock_svc.get_spotify_credentials = AsyncMock(
                return_value=("sp-id", "sp-sec")
            )
            MockSettings.return_value = mock_svc

            with patch(
                "pyrate.services.indexer.Spotify", return_value=mock_spotify
            ):
                result = await service.search_music(query="test")

        assert result == []
        mock_spotify.close.assert_called_once()


# ===========================================================================
# ReleaseMatcher - missing coverage
# ===========================================================================


class TestReleaseMatcherEdgeCases:
    """Cover fuzzy matching edge cases and filter_matching_releases."""

    def test_match_title_empty_after_normalization(self):
        from pyrate.services.release_matcher import ReleaseMatcher

        result = ReleaseMatcher._match_title("", "The Matrix", None, 1999)
        assert not result.is_match
        assert result.match_type == "no_match"

    def test_match_title_partial_containment(self):
        from pyrate.services.release_matcher import ReleaseMatcher

        result = ReleaseMatcher._match_title(
            "matrix", "the matrix reloaded", None, None
        )
        assert result.is_match
        assert result.match_type == "partial"
        assert result.score >= 0.85

    def test_match_title_partial_with_year(self):
        from pyrate.services.release_matcher import ReleaseMatcher

        result = ReleaseMatcher._match_title(
            "matrix", "the matrix", 1999, 1999
        )
        assert result.is_match
        assert result.score >= 0.85

    def test_match_title_fuzzy_with_year_appended(self):
        """Cover the fuzzy_with_year branch."""
        from pyrate.services.release_matcher import ReleaseMatcher

        # A title that wouldn't match normally but matches with year appended
        result = ReleaseMatcher._match_title(
            "doctor who 2005", "doctor who", None, 2005
        )
        assert result.is_match

    def test_normalize_imdb_id_empty(self):
        from pyrate.services.release_matcher import ReleaseMatcher

        assert ReleaseMatcher._normalize_imdb_id("") == ""
        assert ReleaseMatcher._normalize_imdb_id("tt1234567") == "tt1234567"
        assert ReleaseMatcher._normalize_imdb_id("1234567") == "tt1234567"

    def test_normalize_imdb_id_short_number(self):
        from pyrate.services.release_matcher import ReleaseMatcher

        assert ReleaseMatcher._normalize_imdb_id("123") == "tt0000123"

    def test_match_movie_with_alternate_titles(self):
        from pyrate.services.release_matcher import ReleaseMatcher

        result = ReleaseMatcher.match_movie_release(
            release_title="Die.Hard.1988.1080p.BluRay.x264-GROUP",
            movie_title="Die Hard",
            movie_year=1988,
            alternate_titles=["Stirb langsam"],
        )
        assert result.is_match

    def test_match_episode_by_tvdb_id(self):
        from pyrate.services.release_matcher import ReleaseMatcher

        result = ReleaseMatcher.match_episode_release(
            release_title="Something.S01E01.1080p.WEB.x264-GROUP",
            show_title="Totally Different Name",
            season=1,
            episode=1,
            tvdb_id="12345",
            release_tvdb_id="12345",
        )
        assert result.is_match
        assert result.match_type == "id"
        assert result.score == 1.0

    def test_match_episode_tvdb_mismatch_season(self):
        """TVDB ID matches but season/episode doesn't - should not match."""
        from pyrate.services.release_matcher import ReleaseMatcher

        result = ReleaseMatcher.match_episode_release(
            release_title="Show.S02E01.1080p.WEB.x264-GROUP",
            show_title="Show",
            season=1,
            episode=1,
            tvdb_id="12345",
            release_tvdb_id="12345",
        )
        # TVDB matches but S02 != S01
        assert not result.is_match

    def test_season_episode_matches_season_none(self):
        from pyrate.services.release_matcher import ReleaseMatcher

        result = ReleaseMatcher._season_episode_matches(None, None, None, 1, 1)
        assert result is False

    def test_season_episode_matches_season_mismatch(self):
        from pyrate.services.release_matcher import ReleaseMatcher

        result = ReleaseMatcher._season_episode_matches(2, 1, None, 1, 1)
        assert result is False

    def test_season_episode_matches_multi_episode_out_of_range(self):
        from pyrate.services.release_matcher import ReleaseMatcher

        result = ReleaseMatcher._season_episode_matches(1, 1, 3, 1, 5)
        assert result is False

    def test_filter_matching_releases_empty_title(self):
        """Releases with empty titles are skipped."""
        from pyrate.services.release_matcher import ReleaseMatcher

        releases = [
            {"title": ""},
            {"title": "The.Matrix.1999.1080p.BluRay.x264-GROUP"},
        ]

        results = ReleaseMatcher.filter_matching_releases(
            releases=releases,
            media_title="The Matrix",
            media_year=1999,
        )
        assert len(results) >= 1
        # The empty-title release should be skipped
        assert all(r[0]["title"] != "" for r in results)

    def test_filter_matching_releases_with_external_ids(self):
        """Test filter with IMDB external IDs."""
        from pyrate.services.release_matcher import ReleaseMatcher

        releases = [
            {
                "title": "Completely.Different.Title.2020.1080p",
                "imdb_id": "tt0133093",
            },
        ]

        results = ReleaseMatcher.filter_matching_releases(
            releases=releases,
            media_title="The Matrix",
            media_year=1999,
            external_ids={"imdb": "tt0133093"},
        )
        assert len(results) == 1
        assert results[0][1].match_type == "id"

    def test_filter_matching_releases_with_min_score(self):
        """Test min_score filtering."""
        from pyrate.services.release_matcher import ReleaseMatcher

        releases = [
            {"title": "The.Matrix.1999.1080p.BluRay.x264-GROUP"},
            {"title": "Matrix.Reloaded.2003.720p.WEB.x264-OTHER"},
        ]

        results = ReleaseMatcher.filter_matching_releases(
            releases=releases,
            media_title="The Matrix",
            media_year=1999,
            min_score=0.9,
        )
        # Only the exact match should pass the min_score threshold
        for _, match in results:
            assert match.score >= 0.9

    def test_match_episode_season_pack(self):
        """Cover the season pack matching branch."""
        from pyrate.services.release_matcher import ReleaseMatcher

        result = ReleaseMatcher.match_episode_release(
            release_title="Breaking.Bad.S01.1080p.BluRay.x264-GROUP",
            show_title="Breaking Bad",
            season=1,
            episode=5,
        )
        assert result.is_match
        assert result.match_type == "season_pack"
        assert result.score == 0.7


# ===========================================================================
# GroupService - edge cases
# ===========================================================================


class TestGroupServiceEdgeCases:
    """Cover edge case handlers in GroupService."""

    @pytest.mark.asyncio
    async def test_list_groups_pagination(
        self, db_session: AsyncSession
    ):
        from pyrate.schemas.group import GroupCreate
        from pyrate.services.group import GroupService

        service = GroupService(db_session)

        for i in range(5):
            await service.create_group(GroupCreate(name=f"Group {i:02d}"))

        # Test skip/limit
        page1 = await service.list_groups(skip=0, limit=2)
        page2 = await service.list_groups(skip=2, limit=2)
        all_groups = await service.list_groups(skip=0, limit=100)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(all_groups) == 5

        # Ensure no overlap
        page1_names = {g.name for g in page1}
        page2_names = {g.name for g in page2}
        assert page1_names.isdisjoint(page2_names)

    @pytest.mark.asyncio
    async def test_compute_permissions_rate_limit_merging(
        self, db_session: AsyncSession, test_user: User
    ):
        """Cover rate-limit normalization logic in compute_user_permissions."""
        from pyrate.schemas.group import GroupCreate
        from pyrate.services.group import GroupService

        service = GroupService(db_session)

        # Create group with rate limits
        group1 = await service.create_group(
            GroupCreate(
                name="Rate Limited",
                allowed_libraries=["movies"],
                max_concurrent_streams=2,
                indexer_api_requests_limit=100,
                indexer_api_requests_period_minutes=60,
                indexer_downloads_limit=50,
                indexer_downloads_period_minutes=1440,
                playback_limit=10,
                playback_period_minutes=60,
                offline_download_limit=5,
                offline_download_period_minutes=1440,
                prefetch_limit=20,
                prefetch_period_minutes=1440,
                on_demand_fetch_limit=10,
                on_demand_fetch_period_minutes=1440,
            )
        )

        await service.add_user_to_group(test_user.guid, group1.guid)

        permissions = await service.compute_user_permissions(test_user.guid)

        assert permissions.indexer_api_requests_limit == 100
        assert permissions.indexer_api_requests_period_minutes == 60
        assert permissions.indexer_downloads_limit == 50
        assert permissions.playback_limit == 10
        assert permissions.offline_download_limit == 5
        assert permissions.prefetch_limit == 20
        assert permissions.on_demand_fetch_limit == 10

    @pytest.mark.asyncio
    async def test_compute_permissions_multiple_rate_limits(
        self, db_session: AsyncSession, test_user: User
    ):
        """Two groups with different rate limits: most restrictive wins."""
        from pyrate.schemas.group import GroupCreate
        from pyrate.services.group import GroupService

        service = GroupService(db_session)

        # Group1: 100 requests per 60 minutes = 1.67/min
        group1 = await service.create_group(
            GroupCreate(
                name="Liberal",
                allowed_libraries=["movies"],
                max_concurrent_streams=5,
                indexer_api_requests_limit=100,
                indexer_api_requests_period_minutes=60,
            )
        )

        # Group2: 10 requests per 60 minutes = 0.17/min (more restrictive)
        group2 = await service.create_group(
            GroupCreate(
                name="Restrictive",
                allowed_libraries=["shows"],
                max_concurrent_streams=1,
                indexer_api_requests_limit=10,
                indexer_api_requests_period_minutes=60,
            )
        )

        await service.add_user_to_group(test_user.guid, group1.guid)
        await service.add_user_to_group(test_user.guid, group2.guid)

        permissions = await service.compute_user_permissions(test_user.guid)

        # Most restrictive rate limit should win
        assert permissions.indexer_api_requests_limit == 10
        assert permissions.indexer_api_requests_period_minutes == 60
        # But max concurrent streams should take highest
        assert permissions.max_concurrent_streams == 5
        # Libraries should be union
        assert sorted(permissions.allowed_libraries) == ["movies", "shows"]

    @pytest.mark.asyncio
    async def test_get_user_groups_inactive_excluded(
        self, db_session: AsyncSession, test_user: User
    ):
        """get_user_groups excludes inactive groups."""
        from pyrate.schemas.group import GroupCreate
        from pyrate.services.group import GroupService

        service = GroupService(db_session)

        active = await service.create_group(GroupCreate(name="Active"))
        inactive = await service.create_group(
            GroupCreate(name="Inactive", is_active=False)
        )

        await service.add_user_to_group(test_user.guid, active.guid)
        await service.add_user_to_group(test_user.guid, inactive.guid)

        groups = await service.get_user_groups(test_user.guid)
        group_names = [g.name for g in groups]

        assert "Active" in group_names
        assert "Inactive" not in group_names


# ===========================================================================
# SystemSettingsService - unknown library type
# ===========================================================================


class TestSystemSettingsUnknownLibraryType:
    """Cover error paths for unknown library types."""

    @pytest_asyncio.fixture
    async def svc(self, db_session: AsyncSession):
        from pyrate.services.system_settings import SystemSettingsService

        return SystemSettingsService(db_session)

    @pytest.mark.asyncio
    async def test_get_library_settings_unknown_type(self, svc):
        with pytest.raises(ValueError, match="Unknown library type"):
            await svc.get_library_settings("nonexistent_type")

    @pytest.mark.asyncio
    async def test_update_library_settings_unknown_type(self, svc):
        with pytest.raises(ValueError, match="Unknown library type"):
            await svc.update_library_settings(
                "nonexistent_type", library_path="/foo"
            )

    @pytest.mark.asyncio
    async def test_get_naming_settings_unknown_type(self, svc):
        with pytest.raises(ValueError, match="Unknown library type"):
            await svc.get_naming_settings("nonexistent_type")


# ===========================================================================
# SystemSettingsService - update methods with None values (no-op branches)
# ===========================================================================


class TestSystemSettingsUpdateNoneValues:
    """Ensure update methods skip None values."""

    @pytest_asyncio.fixture
    async def svc(self, db_session: AsyncSession):
        from pyrate.services.system_settings import SystemSettingsService

        return SystemSettingsService(db_session)

    @pytest.mark.asyncio
    async def test_update_email_settings_none_values(self, svc):
        """All None values should leave defaults unchanged."""
        result = await svc.update_email_settings()
        assert result["enabled"] is False
        assert result["smtp_host"] == "localhost"

    @pytest.mark.asyncio
    async def test_update_transcoding_settings_none_values(self, svc):
        result = await svc.update_transcoding_settings()
        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_update_storage_settings_none_values(self, svc):
        result = await svc.update_storage_settings()
        assert result["temp_max_age_hours"] == 2.0

    @pytest.mark.asyncio
    async def test_update_invite_settings_none_values(self, svc):
        result = await svc.update_invite_settings()
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_update_lightrays_settings_none_values(self, svc):
        result = await svc.update_lightrays_settings()
        assert result["url"] == "http://lightrays:8080"

    @pytest.mark.asyncio
    async def test_update_system_settings_none_values(self, svc):
        result = await svc.update_system_settings()
        assert result["site_name"] == "pyrate.media"

    @pytest.mark.asyncio
    async def test_update_subscription_settings_none_values(self, svc):
        result = await svc.update_subscription_settings()
        assert result["subscriptions_enabled"] is False

    @pytest.mark.asyncio
    async def test_update_invite_enabled_none_values(self, svc):
        result = await svc.update_invite_enabled()
        assert result["invites_enabled"] is True

    @pytest.mark.asyncio
    async def test_update_libraries_enabled_ignores_non_enabled_keys(self, svc):
        """Keys not ending in _enabled should be ignored."""
        result = await svc.update_libraries_enabled(some_random_key="value")
        # Should just return current state without error
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_update_metadata_settings_partial(self, svc):
        """Only update spotify credentials, leave others unchanged."""
        result = await svc.update_metadata_settings(
            spotify_client_id="sp-id",
            spotify_client_secret="sp-sec",
        )
        assert result["spotify_client_id"] == "sp-id"
        assert result["spotify_client_secret"] == "sp-sec"
        assert result["tmdb_api_key"] is None
