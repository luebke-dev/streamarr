"""
Environment-based configuration for connection settings only.
All other application settings are stored in the database.

This module provides:
1. ConnectionSettings - Environment-based settings for DB, Redis, Elasticsearch
2. Compatibility classes with defaults for OIDC, Invites, Payment, etc.
   These will be populated from the database at runtime.
"""

import logging

from dataclasses import dataclass, field

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ElasticsearchConfig(BaseSettings):
    """Elasticsearch connection settings from environment."""

    model_config = SettingsConfigDict(env_prefix="ELASTICSEARCH_")

    host: str = Field(default="localhost")
    port: int = Field(default=9200)
    index_prefix: str = Field(default="streamarr")
    use_ssl: bool = Field(default=False)
    verify_certs: bool = Field(default=False)
    timeout: int = Field(default=30)
    max_retries: int = Field(default=3)


# Compatibility dataclasses for settings that come from database
# These provide defaults until the DB settings are loaded


@dataclass
class OIDCConfig:
    """OIDC settings - populated from database at runtime."""

    enabled: bool = False
    client_id: str | None = None
    client_secret: str | None = None
    server_metadata_url: str | None = None
    issuer: str | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    userinfo_endpoint: str | None = None
    jwks_uri: str | None = None
    end_session_endpoint: str | None = None
    scopes: list[str] = field(default_factory=lambda: ["openid", "profile", "email"])
    redirect_uri: str = "http://localhost:8000/api/auth/callback"
    post_logout_redirect_uri: str = "http://localhost:8000"
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    claim_mapping: dict = field(
        default_factory=lambda: {
            "sub": "oidc_sub",
            "email": "email",
            "given_name": "first_name",
            "family_name": "last_name",
            "preferred_username": "preferred_username",
            "picture": "picture",
            "locale": "locale",
            "groups": "groups",
        }
    )
    auto_register_users: bool = True
    default_user_active: bool = True
    default_user_superuser: bool = False
    local_auth_enabled: bool = True
    open_registration: bool = False
    require_password_complexity: bool = True
    min_password_length: int = 8


@dataclass
class InvitesConfig:
    """Invites settings - populated from database at runtime."""

    enabled: bool = True
    default_expiry_hours: int = 72
    max_expiry_hours: int = 168
    allow_multiple_uses: bool = False
    require_admin_creation: bool = False


@dataclass
class PaymentConfig:
    """Payment settings - populated from database at runtime."""

    enabled: bool = False
    provider: str = "stripe"
    stripe_secret_key: str | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: str | None = None


@dataclass
class EmailConfig:
    """Email settings - populated from database at runtime."""

    enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    from_email: str = "noreply@streamarr.media"
    from_name: str = "Streamarr"
    reply_to: str | None = None
    templates_dir: str = "templates/email"


@dataclass
class TranscodingConfig:
    """Transcoding settings - populated from database at runtime."""

    enabled: bool = False
    max_resolution: str = "1080p"
    hardware_acceleration: bool = False
    hardware_acceleration_device: str | None = None
    ffmpeg_path: str = "ffmpeg"
    kubernetes_enabled: bool = False
    job_cpu_limit: str = "2"
    job_memory_limit: str = "4Gi"
    job_cpu_request: str = "1"
    job_memory_request: str = "2Gi"


@dataclass
class MetadataConfig:
    """Metadata settings - populated from database at runtime."""

    tmdb_api_key: str | None = None
    igdb_client_id: str | None = None
    igdb_client_secret: str | None = None
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    locale: str = "de-DE"


@dataclass
class LibraryConfig:
    """Library settings for a specific media type."""

    enabled: bool = True
    library_path: str = "/library"
    enable_on_demand_downloads: bool = True
    enable_prefetch_downloads: bool = False
    download_rules: list = field(default_factory=list)
    on_demand_rules: list = field(default_factory=list)


class ConnectionSettings(BaseSettings):
    """
    Connection settings loaded from environment variables only.
    All application configuration is stored in the database.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database connection
    database_url: str = Field(
        default="postgresql+asyncpg://streamarr:streamarr@localhost:5432/streamarr",
        validation_alias="DATABASE_URL",
    )

    # Redis connection
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL",
    )

    # Elasticsearch connection
    elasticsearch: ElasticsearchConfig = Field(default_factory=ElasticsearchConfig)

    # Secret key for JWT — MUST be set via SECRET_KEY environment variable
    secret_key: str = Field(
        default="",
        validation_alias="SECRET_KEY",
    )

    # Shared secret required on downloader webhook callbacks. When unset the
    # handlers reject the call (fail-closed); production deployments must set
    # DOWNLOADER_WEBHOOK_SECRET.
    downloader_webhook_secret: str = Field(
        default="",
        validation_alias="DOWNLOADER_WEBHOOK_SECRET",
    )

    # Number of trusted reverse proxies in front of the app. The rate limiter
    # derives the client IP from the (count+1)-th X-Forwarded-For entry from the
    # right so a client cannot spoof it by prepending values.
    trusted_proxy_count: int = Field(
        default=1,
        validation_alias="TRUSTED_PROXY_COUNT",
    )

    # Default CORS origins (used before DB settings are loaded)
    cors_allowed_origins: list[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:8080",
            "http://localhost:9000",
            "http://localhost:9001",
            "http://localhost:9002",
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ]
    )

    # Public-facing app URL used as the base for links in outbound emails,
    # OIDC redirects, invite URLs, etc. Falls back to the first allowed CORS
    # origin when unset (which was the legacy behavior) but should be set
    # explicitly in production because the first CORS entry may be a
    # localhost default. Override via `APP_URL` env var or the
    # `system.app_url` DB setting (DB wins).
    app_url: str = Field(
        default="",
        validation_alias="APP_URL",
    )

    # Enable hosted web app at app.streamarr.media (adds CORS origin)
    enable_hosted_app: bool = Field(
        default=True,
        validation_alias="ENABLE_HOSTED_APP",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
    )
    log_format: str = Field(
        default="text",
        validation_alias="LOG_FORMAT",
    )

    # Compatibility settings - these have defaults and can be updated from DB
    oidc: OIDCConfig = field(default_factory=OIDCConfig)
    invites: InvitesConfig = field(default_factory=InvitesConfig)
    payment: PaymentConfig = field(default_factory=PaymentConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    transcoding: TranscodingConfig = field(default_factory=TranscodingConfig)
    metadata: MetadataConfig = field(default_factory=MetadataConfig)
    movies: LibraryConfig = field(
        default_factory=lambda: LibraryConfig(library_path="/library/movies")
    )
    shows: LibraryConfig = field(
        default_factory=lambda: LibraryConfig(library_path="/library/shows")
    )
    music: LibraryConfig = field(
        default_factory=lambda: LibraryConfig(library_path="/library/music")
    )
    books: LibraryConfig = field(
        default_factory=lambda: LibraryConfig(library_path="/library/books")
    )
    games: LibraryConfig = field(
        default_factory=lambda: LibraryConfig(library_path="/library/games")
    )


# Create the connection settings using pydantic, then add dataclass defaults
_base_settings = ConnectionSettings()

if not _base_settings.secret_key:
    import sys

    logging.critical(
        "SECRET_KEY environment variable is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )
    sys.exit(1)


class AppSettings:
    """
    Combined settings that includes environment-based connection settings
    and database-loaded application settings with defaults.
    """

    def __init__(self):
        # Copy connection settings from pydantic model
        self.database_url = _base_settings.database_url
        self.redis_url = _base_settings.redis_url
        self.elasticsearch = _base_settings.elasticsearch
        self.secret_key = _base_settings.secret_key
        self.downloader_webhook_secret = _base_settings.downloader_webhook_secret
        self.trusted_proxy_count = _base_settings.trusted_proxy_count
        self.cors_allowed_origins = _base_settings.cors_allowed_origins
        self.app_url = _base_settings.app_url

        # Initialize with defaults - these will be updated from DB at runtime
        self.oidc = OIDCConfig()
        self.invites = InvitesConfig()
        self.payment = PaymentConfig()
        self.email = EmailConfig()
        self.transcoding = TranscodingConfig()
        self.metadata = MetadataConfig()
        self.movies = LibraryConfig(library_path="/library/movies")
        self.shows = LibraryConfig(library_path="/library/shows")
        self.music = LibraryConfig(library_path="/library/music")
        self.books = LibraryConfig(library_path="/library/books")
        self.games = LibraryConfig(library_path="/library/games")


# Singleton instance
connection_settings = _base_settings
settings = AppSettings()


async def load_settings_from_database():
    """
    Load all application settings from the database KV store.
    This should be called during application startup.
    """
    from streamarr.database import sessionmanager
    from streamarr.services.settings import SettingsService

    async with sessionmanager.session() as session:
        settings_service = SettingsService(session)

        # Load all settings from database with prefix filtering
        all_settings = await settings_service.get_all()

        def _apply_prefix(prefix: str, target: object):
            """Apply settings with the given prefix to the target dataclass."""
            prefix_dot = f"{prefix}."
            for k, v in all_settings.items():
                if k.startswith(prefix_dot):
                    attr = k[len(prefix_dot):]
                    if hasattr(target, attr):
                        setattr(target, attr, v)

        _apply_prefix("oidc", settings.oidc)
        _apply_prefix("invites", settings.invites)
        _apply_prefix("payment", settings.payment)
        _apply_prefix("email", settings.email)
        _apply_prefix("transcoding", settings.transcoding)

        # Update Metadata settings from plugin settings
        if "plugin.tmdb.api_key" in all_settings:
            settings.metadata.tmdb_api_key = all_settings["plugin.tmdb.api_key"]
        if "plugin.igdb.client_id" in all_settings:
            settings.metadata.igdb_client_id = all_settings["plugin.igdb.client_id"]
        if "plugin.igdb.client_secret" in all_settings:
            settings.metadata.igdb_client_secret = all_settings[
                "plugin.igdb.client_secret"
            ]
        if "plugin.spotify.client_id" in all_settings:
            settings.metadata.spotify_client_id = all_settings[
                "plugin.spotify.client_id"
            ]
        if "plugin.spotify.client_secret" in all_settings:
            settings.metadata.spotify_client_secret = all_settings[
                "plugin.spotify.client_secret"
            ]
        if "system.locale" in all_settings:
            settings.metadata.locale = all_settings["system.locale"]

        # Update Library settings (plugin.movies.*, plugin.shows.*, etc.)
        for library_name in ["movies", "shows", "music", "books", "games"]:
            _apply_prefix(f"plugin.{library_name}", getattr(settings, library_name))

        # Update CORS origins if set in database
        if "system.cors_allowed_origins" in all_settings:
            settings.cors_allowed_origins = all_settings["system.cors_allowed_origins"]

        # Update public app URL if set in database (overrides env + default)
        if "system.app_url" in all_settings:
            db_app_url = all_settings["system.app_url"]
            if isinstance(db_app_url, str) and db_app_url.strip():
                settings.app_url = db_app_url.strip()

        # Surface fallback usage — if neither DB nor ``APP_URL`` env is set,
        # outbound emails / OIDC redirects will point at a CORS origin or the
        # hardcoded localhost default. Log once at startup so operators notice.
        effective = (settings.app_url or "").strip()
        if not effective:
            import logging as _logging
            _logger = _logging.getLogger("streamarr.config")
            if settings.cors_allowed_origins:
                _logger.warning(
                    "APP_URL is not configured; outbound links will fall back "
                    "to CORS origin %s. Set APP_URL env var or system.app_url.",
                    settings.cors_allowed_origins[0],
                )
            else:
                _logger.warning(
                    "APP_URL is not configured and no CORS origins set; "
                    "outbound links fall back to http://localhost:8080.",
                )


def get_app_url() -> str:
    """Resolve the public-facing app URL for outbound links.

    Precedence:
    1. `system.app_url` DB setting (loaded into `settings.app_url` at startup)
    2. `APP_URL` environment variable (also lands in `settings.app_url`)
    3. First allowed CORS origin (legacy fallback)
    4. Hardcoded `http://localhost:8080`

    Always returns a URL without a trailing slash so callers can safely
    append paths like `/auth/verify-email?token=…`.
    """
    candidate = (settings.app_url or "").strip()
    if not candidate and settings.cors_allowed_origins:
        candidate = settings.cors_allowed_origins[0]
    if not candidate:
        candidate = "http://localhost:8080"
    return candidate.rstrip("/")
