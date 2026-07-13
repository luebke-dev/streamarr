"""Tests for streamarr.config module - covers dataclass defaults and load_settings_from_database."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------

class TestOIDCConfig:
    def test_defaults(self):
        from streamarr.config import OIDCConfig

        cfg = OIDCConfig()
        assert cfg.enabled is False
        assert cfg.client_id is None
        assert cfg.client_secret is None
        assert cfg.scopes == ["openid", "profile", "email"]
        assert cfg.redirect_uri == "http://localhost:8000/api/auth/callback"
        assert cfg.jwt_algorithm == "HS256"
        assert cfg.jwt_access_token_expire_minutes == 30
        assert cfg.jwt_refresh_token_expire_days == 7
        assert cfg.auto_register_users is True
        assert cfg.local_auth_enabled is True
        assert cfg.require_password_complexity is True
        assert cfg.min_password_length == 8
        assert "sub" in cfg.claim_mapping


class TestInvitesConfig:
    def test_defaults(self):
        from streamarr.config import InvitesConfig

        cfg = InvitesConfig()
        assert cfg.enabled is True
        assert cfg.default_expiry_hours == 72
        assert cfg.max_expiry_hours == 168
        assert cfg.allow_multiple_uses is False


class TestPaymentConfig:
    def test_defaults(self):
        from streamarr.config import PaymentConfig

        cfg = PaymentConfig()
        assert cfg.enabled is False
        assert cfg.provider == "stripe"
        assert cfg.stripe_secret_key is None


class TestEmailConfig:
    def test_defaults(self):
        from streamarr.config import EmailConfig

        cfg = EmailConfig()
        assert cfg.enabled is False
        assert cfg.smtp_host == "localhost"
        assert cfg.smtp_port == 587
        assert cfg.smtp_use_tls is True
        assert cfg.from_email == "noreply@streamarr.media"


class TestTranscodingConfig:
    def test_defaults(self):
        from streamarr.config import TranscodingConfig

        cfg = TranscodingConfig()
        assert cfg.enabled is False
        assert cfg.max_resolution == "1080p"
        assert cfg.hardware_acceleration is False
        assert cfg.ffmpeg_path == "ffmpeg"
        assert cfg.kubernetes_enabled is False


class TestMetadataConfig:
    def test_defaults(self):
        from streamarr.config import MetadataConfig

        cfg = MetadataConfig()
        assert cfg.tmdb_api_key is None
        assert cfg.igdb_client_id is None
        assert cfg.spotify_client_id is None
        assert cfg.locale == "de-DE"


class TestLibraryConfig:
    def test_defaults(self):
        from streamarr.config import LibraryConfig

        cfg = LibraryConfig()
        assert cfg.enabled is True
        assert cfg.library_path == "/library"
        assert cfg.enable_on_demand_downloads is True
        assert cfg.enable_prefetch_downloads is False
        assert cfg.download_rules == []

    def test_custom_path(self):
        from streamarr.config import LibraryConfig

        cfg = LibraryConfig(library_path="/data/movies")
        assert cfg.library_path == "/data/movies"


class TestElasticsearchConfig:
    @patch.dict("os.environ", {}, clear=True)
    def test_defaults(self):
        from streamarr.config import ElasticsearchConfig

        cfg = ElasticsearchConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 9200
        assert cfg.index_prefix == "streamarr"
        assert cfg.use_ssl is False
        assert cfg.timeout == 30


# ---------------------------------------------------------------------------
# AppSettings
# ---------------------------------------------------------------------------

class TestAppSettings:
    def test_app_settings_init(self):
        from streamarr.config import AppSettings

        app = AppSettings()
        assert app.oidc is not None
        assert app.invites is not None
        assert app.payment is not None
        assert app.email is not None
        assert app.transcoding is not None
        assert app.metadata is not None
        assert app.movies.library_path == "/library/movies"
        assert app.shows.library_path == "/library/shows"
        assert app.music.library_path == "/library/music"
        assert app.books.library_path == "/library/books"
        assert app.games.library_path == "/library/games"


# ---------------------------------------------------------------------------
# ConnectionSettings (already loaded as module-level singleton)
# ---------------------------------------------------------------------------

class TestConnectionSettings:
    def test_singleton_exists(self):
        from streamarr.config import connection_settings, settings

        assert connection_settings is not None
        assert settings is not None
        assert connection_settings.secret_key != ""

    def test_settings_has_database_url(self):
        from streamarr.config import settings

        assert settings.database_url is not None


# ---------------------------------------------------------------------------
# load_settings_from_database
# ---------------------------------------------------------------------------

class TestLoadSettingsFromDatabase:
    @pytest.mark.asyncio
    async def test_load_settings_applies_prefixes(self):
        from streamarr.config import load_settings_from_database, settings

        mock_settings = {
            "oidc.enabled": True,
            "oidc.client_id": "test-client",
            "invites.enabled": False,
            "invites.default_expiry_hours": 48,
            "payment.enabled": True,
            "email.smtp_host": "mail.example.com",
            "transcoding.enabled": True,
            "plugin.tmdb.api_key": "tmdb-key",
            "plugin.igdb.client_id": "igdb-id",
            "plugin.igdb.client_secret": "igdb-secret",
            "plugin.spotify.client_id": "spotify-id",
            "plugin.spotify.client_secret": "spotify-secret",
            "system.locale": "en-US",
            "system.cors_allowed_origins": ["http://example.com"],
            "plugin.movies.library_path": "/custom/movies",
        }

        mock_session = AsyncMock()
        mock_settings_service = AsyncMock()
        mock_settings_service.get_all.return_value = mock_settings

        with (
            patch("streamarr.database.sessionmanager") as mock_sm,
            patch("streamarr.services.settings.SettingsService", return_value=mock_settings_service),
        ):
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_session)
            mock_context.__aexit__ = AsyncMock(return_value=False)
            mock_sm.session.return_value = mock_context

            await load_settings_from_database()

        assert settings.oidc.enabled is True
        assert settings.oidc.client_id == "test-client"
        assert settings.invites.enabled is False
        assert settings.invites.default_expiry_hours == 48
        assert settings.payment.enabled is True
        assert settings.email.smtp_host == "mail.example.com"
        assert settings.transcoding.enabled is True
        assert settings.metadata.tmdb_api_key == "tmdb-key"
        assert settings.metadata.igdb_client_id == "igdb-id"
        assert settings.metadata.igdb_client_secret == "igdb-secret"
        assert settings.metadata.spotify_client_id == "spotify-id"
        assert settings.metadata.spotify_client_secret == "spotify-secret"
        assert settings.metadata.locale == "en-US"
        assert settings.cors_allowed_origins == ["http://example.com"]
        assert settings.movies.library_path == "/custom/movies"

    @pytest.mark.asyncio
    async def test_load_settings_empty(self):
        """Loading with empty settings doesn't crash."""
        from streamarr.config import load_settings_from_database

        mock_session = AsyncMock()
        mock_settings_service = AsyncMock()
        mock_settings_service.get_all.return_value = {}

        with (
            patch("streamarr.database.sessionmanager") as mock_sm,
            patch("streamarr.services.settings.SettingsService", return_value=mock_settings_service),
        ):
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_session)
            mock_context.__aexit__ = AsyncMock(return_value=False)
            mock_sm.session.return_value = mock_context

            await load_settings_from_database()
