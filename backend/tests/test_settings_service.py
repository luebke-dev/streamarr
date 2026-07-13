"""Tests for the SettingsService."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from streamarr.models.setting import DEFAULT_SETTINGS, Setting
from streamarr.services import settings as settings_module
from streamarr.services.settings import SettingsService


class TestSettingsBasicOperations:
    """Test basic get/set/delete operations."""

    @pytest.mark.asyncio
    async def test_set_and_get_string(self, db_session: AsyncSession):
        """Test setting and getting a string value."""
        service = SettingsService(db_session)

        await service.set("test.key", "hello")
        result = await service.get("test.key")

        assert result == "hello"

    @pytest.mark.asyncio
    async def test_set_and_get_integer(self, db_session: AsyncSession):
        """Test setting and getting an integer value."""
        service = SettingsService(db_session)

        await service.set("test.number", 42)
        result = await service.get("test.number")

        assert result == 42

    @pytest.mark.asyncio
    async def test_set_and_get_boolean(self, db_session: AsyncSession):
        """Test setting and getting a boolean value."""
        service = SettingsService(db_session)

        await service.set("test.flag", True)
        result = await service.get("test.flag")

        assert result is True

    @pytest.mark.asyncio
    async def test_set_and_get_list(self, db_session: AsyncSession):
        """Test setting and getting a list value."""
        service = SettingsService(db_session)

        await service.set("test.list", ["a", "b", "c"])
        result = await service.get("test.list")

        assert result == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_set_and_get_dict(self, db_session: AsyncSession):
        """Test setting and getting a dict value."""
        service = SettingsService(db_session)

        data = {"host": "localhost", "port": 5432}
        await service.set("test.dict", data)
        result = await service.get("test.dict")

        assert result == data

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, db_session: AsyncSession):
        """Test getting a non-existent key returns None."""
        service = SettingsService(db_session)

        result = await service.get("nonexistent.key")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_with_default(self, db_session: AsyncSession):
        """Test getting a non-existent key with a default value."""
        service = SettingsService(db_session)

        result = await service.get("nonexistent.key", default="fallback")

        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_get_returns_default_settings(self, db_session: AsyncSession):
        """Test that DEFAULT_SETTINGS are returned when no override exists."""
        service = SettingsService(db_session)

        # This key should exist in DEFAULT_SETTINGS
        result = await service.get("plugin.movies.enabled")

        assert result is True  # Default from DEFAULT_SETTINGS

    @pytest.mark.asyncio
    async def test_set_overwrites_existing(self, db_session: AsyncSession):
        """Test that setting an existing key overwrites it."""
        service = SettingsService(db_session)

        await service.set("test.key", "first")
        await service.set("test.key", "second")
        result = await service.get("test.key")

        assert result == "second"

    @pytest.mark.asyncio
    async def test_delete_setting(self, db_session: AsyncSession):
        """Test deleting a setting."""
        service = SettingsService(db_session)

        await service.set("test.delete.me", "value")
        deleted = await service.delete("test.delete.me")

        assert deleted is True
        result = await service.get("test.delete.me")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_setting(self, db_session: AsyncSession):
        """Test deleting a non-existent setting."""
        service = SettingsService(db_session)

        deleted = await service.delete("nonexistent.key")

        assert deleted is False


class TestSettingsCache:
    """Test settings caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_is_populated_on_get(self, db_session: AsyncSession):
        """Test that cache is populated when getting a value."""
        service = SettingsService(db_session)

        await service.set("cached.key", "cached_value")
        # Clear internal cache
        settings_module._cache.clear()

        # First get populates cache
        result = await service.get("cached.key")
        assert result == "cached_value"
        assert "cached.key" in settings_module._cache

    @pytest.mark.asyncio
    async def test_cache_is_updated_on_set(self, db_session: AsyncSession):
        """Test that cache is updated when setting a value."""
        service = SettingsService(db_session)

        await service.set("cache.test", "value1")
        assert settings_module._cache.get("cache.test") == "value1"

        await service.set("cache.test", "value2")
        assert settings_module._cache.get("cache.test") == "value2"

    @pytest.mark.asyncio
    async def test_cache_is_cleared_on_delete(self, db_session: AsyncSession):
        """Test that cache is cleared when deleting a setting."""
        service = SettingsService(db_session)

        await service.set("cache.delete", "value")
        assert "cache.delete" in settings_module._cache

        await service.delete("cache.delete")
        assert "cache.delete" not in settings_module._cache

    @pytest.mark.asyncio
    async def test_cache_serves_subsequent_gets(self, db_session: AsyncSession):
        """Test that subsequent gets use the cache."""
        service = SettingsService(db_session)

        await service.set("cached.key", "value")
        # Manually change cache to verify it's used
        settings_module._cache["cached.key"] = "cached_override"

        result = await service.get("cached.key")
        assert result == "cached_override"


class TestSettingsBulkOperations:
    """Test bulk setting operations."""

    @pytest.mark.asyncio
    async def test_get_all(self, db_session: AsyncSession):
        """Test getting all settings."""
        service = SettingsService(db_session)

        await service.set("custom.key1", "val1")
        await service.set("custom.key2", "val2")

        all_settings = await service.get_all()

        # Should contain default settings plus custom ones
        assert "custom.key1" in all_settings
        assert "custom.key2" in all_settings
        assert all_settings["custom.key1"] == "val1"

    @pytest.mark.asyncio
    async def test_get_all_with_prefix(self, db_session: AsyncSession):
        """Test getting settings with a specific prefix."""
        service = SettingsService(db_session)

        await service.set("plugin.movies.custom", "movie_val")
        await service.set("plugin.shows.custom", "show_val")

        movie_settings = await service.get_all(prefix="plugin.movies.")

        assert "plugin.movies.custom" in movie_settings
        assert "plugin.shows.custom" not in movie_settings

    @pytest.mark.asyncio
    async def test_set_many(self, db_session: AsyncSession):
        """Test setting multiple values at once."""
        service = SettingsService(db_session)

        settings = {
            "batch.key1": "value1",
            "batch.key2": 42,
            "batch.key3": True,
        }
        results = await service.set_many(settings)

        assert len(results) == 3
        assert await service.get("batch.key1") == "value1"
        assert await service.get("batch.key2") == 42
        assert await service.get("batch.key3") is True

    @pytest.mark.asyncio
    async def test_get_many(self, db_session: AsyncSession):
        """Test getting multiple values at once."""
        service = SettingsService(db_session)

        await service.set("multi.a", "alpha")
        await service.set("multi.b", "beta")

        results = await service.get_many(["multi.a", "multi.b", "multi.c"])

        assert results["multi.a"] == "alpha"
        assert results["multi.b"] == "beta"
        assert results["multi.c"] is None


class TestSettingsConvenienceMethods:
    """Test convenience methods for common settings."""

    @pytest.mark.asyncio
    async def test_get_locale_default(self, db_session: AsyncSession):
        """Test getting locale with default value."""
        service = SettingsService(db_session)

        locale = await service.get_locale()

        assert locale == "de-DE"  # Default locale

    @pytest.mark.asyncio
    async def test_get_locale_custom(self, db_session: AsyncSession):
        """Test getting custom locale."""
        service = SettingsService(db_session)

        await service.set("system.locale", "en-US")
        locale = await service.get_locale()

        assert locale == "en-US"

    @pytest.mark.asyncio
    async def test_get_tmdb_api_key(self, db_session: AsyncSession):
        """Test getting TMDB API key."""
        service = SettingsService(db_session)

        await service.set("plugin.tmdb.api_key", "my-tmdb-key")
        key = await service.get_tmdb_api_key()

        assert key == "my-tmdb-key"

    @pytest.mark.asyncio
    async def test_get_igdb_credentials(self, db_session: AsyncSession):
        """Test getting IGDB credentials."""
        service = SettingsService(db_session)

        await service.set("plugin.igdb.client_id", "igdb-id")
        await service.set("plugin.igdb.client_secret", "igdb-secret")

        client_id, client_secret = await service.get_igdb_credentials()

        assert client_id == "igdb-id"
        assert client_secret == "igdb-secret"

    @pytest.mark.asyncio
    async def test_is_library_enabled_default(self, db_session: AsyncSession):
        """Test checking if a library is enabled with default."""
        service = SettingsService(db_session)

        enabled = await service.is_library_enabled("movies")

        assert enabled is True  # Default

    @pytest.mark.asyncio
    async def test_is_library_enabled_disabled(self, db_session: AsyncSession):
        """Test checking if a library is explicitly disabled."""
        service = SettingsService(db_session)

        await service.set("plugin.games.enabled", False)
        enabled = await service.is_library_enabled("games")

        assert enabled is False

    @pytest.mark.asyncio
    async def test_get_library_path_default(self, db_session: AsyncSession):
        """Test getting default library path."""
        service = SettingsService(db_session)

        path = await service.get_library_path("movies")

        assert path == "/library/movies"

    @pytest.mark.asyncio
    async def test_get_library_path_custom(self, db_session: AsyncSession):
        """Test getting custom library path."""
        service = SettingsService(db_session)

        await service.set("plugin.movies.library_path", "/data/movies")
        path = await service.get_library_path("movies")

        assert path == "/data/movies"

    @pytest.mark.asyncio
    async def test_is_oidc_enabled_default(self, db_session: AsyncSession):
        """Test OIDC disabled by default."""
        service = SettingsService(db_session)

        enabled = await service.is_oidc_enabled()

        assert enabled is False

    @pytest.mark.asyncio
    async def test_oidc_settings_mask_secret(self, db_session: AsyncSession):
        from streamarr.services.system_settings import SystemSettingsService

        service = SystemSettingsService(db_session)
        await service.update_oidc_settings(
            enabled=True,
            client_id="streamarr",
            client_secret="super-secret",
            scopes=["openid", "profile", "email"],
        )

        result = await service.get_oidc_settings()

        assert result["enabled"] is True
        assert result["client_id"] == "streamarr"
        assert result["client_secret_configured"] is True
        assert "client_secret" not in result

        await service.update_oidc_settings(client_secret="")
        stored = await SettingsService(db_session).get("oidc.client_secret")
        assert stored == "super-secret"

    @pytest.mark.asyncio
    async def test_is_email_enabled_default(self, db_session: AsyncSession):
        """Test email disabled by default."""
        service = SettingsService(db_session)

        enabled = await service.is_email_enabled()

        assert enabled is False

    @pytest.mark.asyncio
    async def test_is_transcoding_enabled_default(self, db_session: AsyncSession):
        """Test transcoding disabled by default."""
        service = SettingsService(db_session)

        enabled = await service.is_transcoding_enabled()

        assert enabled is False

    @pytest.mark.asyncio
    async def test_is_invites_enabled_default(self, db_session: AsyncSession):
        """Test invites enabled by default."""
        service = SettingsService(db_session)

        enabled = await service.is_invites_enabled()

        assert enabled is True

    @pytest.mark.asyncio
    async def test_is_subscriptions_enabled_default(self, db_session: AsyncSession):
        """Test subscriptions disabled by default."""
        service = SettingsService(db_session)

        enabled = await service.is_subscriptions_enabled()

        assert enabled is False

    @pytest.mark.asyncio
    async def test_get_cors_origins_default(self, db_session: AsyncSession):
        """Test getting CORS origins default."""
        service = SettingsService(db_session)

        origins = await service.get_cors_origins()

        assert origins == []

    @pytest.mark.asyncio
    async def test_get_library_settings(self, db_session: AsyncSession):
        """Test getting all settings for a library."""
        service = SettingsService(db_session)

        await service.set("plugin.movies.custom_setting", "custom")

        settings = await service.get_library_settings("movies")

        # Should include both defaults and custom settings
        assert "plugin.movies.enabled" in settings
        assert "plugin.movies.custom_setting" in settings
