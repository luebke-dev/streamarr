"""Setting Model - Key-Value based settings storage."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlmodel import JSON, Column, Field, SQLModel


class Setting(SQLModel, table=True):
    """
    Key-Value based settings storage.
    Each setting is stored as a separate row with a unique key.
    Values are stored as JSON to support any data type.
    """

    __tablename__ = "settings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    key: str = Field(unique=True, index=True)
    value: Any = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True)),
    )


# Default settings with their default values and types
# This serves as documentation and provides defaults when settings don't exist
DEFAULT_SETTINGS: dict[str, Any] = {
    # Plugin Settings - Movies Library
    "plugin.movies.enabled": True,
    "plugin.movies.library_path": "/library/movies",
    "plugin.movies.enable_on_demand_downloads": True,
    "plugin.movies.enable_prefetch_downloads": False,
    "plugin.movies.download_rules": [],
    "plugin.movies.on_demand_rules": [],
    "plugin.movies.naming.folder": "{movie_title} ({movie_year})",
    "plugin.movies.naming.file": "{movie_title} ({movie_year})",
    "plugin.movies.naming.replace_illegal_characters": True,
    "plugin.movies.naming.colon_replacement": " -",
    # Plugin Settings - Shows Library
    "plugin.shows.enabled": True,
    "plugin.shows.library_path": "/library/shows",
    "plugin.shows.enable_on_demand_downloads": True,
    "plugin.shows.enable_prefetch_downloads": False,
    "plugin.shows.hide_season_zero": False,
    "plugin.shows.download_rules": [],
    "plugin.shows.on_demand_rules": [],
    "plugin.shows.naming.series_folder": "{series_title} ({series_year})",
    "plugin.shows.naming.season_folder": "Season {season_number_2}",
    "plugin.shows.naming.episode_file": "{series_title} - S{season_number_2}E{episode_number_2} - {episode_title}",
    "plugin.shows.naming.multi_episode_style": "extend",
    "plugin.shows.naming.replace_illegal_characters": True,
    "plugin.shows.naming.colon_replacement": " -",
    # Plugin Settings - Music Library
    "plugin.music.enabled": True,
    "plugin.music.library_path": "/library/music",
    "plugin.music.enable_on_demand_downloads": True,
    "plugin.music.enable_prefetch_downloads": False,
    "plugin.music.download_rules": [],
    "plugin.music.on_demand_rules": [],
    # Plugin Settings - Books Library
    "plugin.books.enabled": True,
    "plugin.books.library_path": "/library/books",
    # Plugin Settings - Games Library
    "plugin.games.enabled": True,
    "plugin.games.library_path": "/library/games",
    # Plugin Settings - Photos/Home Videos Library
    "plugin.photos.enabled": True,
    "plugin.photos.library_path": "/library/photos",
    # Cast Target Registry
    "cast.targets": [],
    # Server Plugin Package Registry
    "plugins.repositories": [],
    "plugins.installed": [],
    # Branding Settings
    "branding.server_name": "Streamarr",
    "branding.login_disclaimer": "",
    "branding.custom_css": "",
    "branding.logo_url": None,
    "branding.splashscreen_enabled": False,
    "branding.themes": [],
    "branding.active_theme_id": None,
    # Plugin Settings - Metadata Providers
    "plugin.tmdb.api_key": None,
    "plugin.igdb.client_id": None,
    "plugin.igdb.client_secret": None,
    "plugin.spotify.client_id": None,
    "plugin.spotify.client_secret": None,
    # System Settings
    "system.locale": "de-DE",
    "system.site_name": "Streamarr",
    # Public-facing app URL used in outbound email links, OIDC redirects,
    # invite URLs. Admins should set this to the canonical https URL in
    # production — e.g. "https://streamarr.luebke.dev". Falls back to
    # `APP_URL` env var or the first CORS origin when empty.
    "system.app_url": "",
    # OIDC Settings
    "oidc.enabled": False,
    "oidc.client_id": None,
    "oidc.client_secret": None,
    "oidc.server_metadata_url": None,
    "oidc.issuer": None,
    "oidc.authorization_endpoint": None,
    "oidc.token_endpoint": None,
    "oidc.userinfo_endpoint": None,
    "oidc.jwks_uri": None,
    "oidc.end_session_endpoint": None,
    "oidc.scopes": ["openid", "profile", "email"],
    "oidc.redirect_uri": "http://localhost:8000/api/auth/callback",
    "oidc.post_logout_redirect_uri": "http://localhost:8000",
    "oidc.jwt_secret_key": "your-secret-key-change-this-in-production",
    "oidc.jwt_algorithm": "HS256",
    "oidc.jwt_access_token_expire_minutes": 30,
    "oidc.jwt_refresh_token_expire_days": 7,
    "oidc.claim_mapping": {
        "sub": "oidc_sub",
        "email": "email",
        "given_name": "first_name",
        "family_name": "last_name",
        "preferred_username": "preferred_username",
        "picture": "picture",
        "locale": "locale",
        "groups": "groups",
    },
    "oidc.auto_register_users": True,
    "oidc.default_user_active": True,
    "oidc.default_user_superuser": False,
    "oidc.local_auth_enabled": True,
    "oidc.require_password_complexity": True,
    "oidc.min_password_length": 8,
    # Favorites Settings
    "favorites.permanent": False,
    # Friends Settings
    "friends.enabled": True,
    # Invite Settings
    "invites.enabled": True,
    "invites.default_expiry_hours": 72,
    "invites.max_expiry_hours": 168,
    "invites.allow_multiple_uses": False,
    "invites.require_admin_creation": False,
    # Subscription/Payment Settings
    "subscriptions.enabled": False,
    # Transcoding Settings
    "transcoding.enabled": False,
    "transcoding.max_resolution": "1080p",
    "transcoding.hardware_acceleration": False,
    "transcoding.hardware_acceleration_device": None,
    "transcoding.ffmpeg_path": "ffmpeg",
    # Email Settings
    "email.enabled": False,
    "email.smtp_host": "localhost",
    "email.smtp_port": 587,
    "email.smtp_user": None,
    "email.smtp_password": None,
    "email.smtp_use_tls": True,
    "email.smtp_use_ssl": False,
    "email.from_email": "noreply@streamarr.media",
    "email.from_name": "Streamarr",
    "email.reply_to": None,
    # CORS Settings
    "cors.allowed_origins": [
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:9000",
        "http://localhost:9001",
        "http://localhost:9002",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    # Permission Defaults (Global caps — override group/user permissions)
    "permissions.allowed_libraries": ["movies", "series", "games", "books", "music", "photos"],
    "permissions.max_concurrent_streams": 3,
    "permissions.max_game_streams": 1,
    "permissions.max_video_quality": "uhd",
    "permissions.max_audio_quality": "lossless",
    "permissions.max_concurrent_transcodings": 2,
    "permissions.offline_download_limit": None,
    "permissions.offline_download_period_minutes": 1440,
    "permissions.prefetch_limit": None,
    "permissions.prefetch_period_minutes": 1440,
    "permissions.on_demand_fetch_limit": None,
    "permissions.on_demand_fetch_period_minutes": 1440,
    "permissions.indexer_api_requests_limit": None,
    "permissions.indexer_api_requests_period_minutes": 60,
    "permissions.indexer_downloads_limit": None,
    "permissions.indexer_downloads_period_minutes": 1440,
    "permissions.playback_limit": None,
    "permissions.playback_period_minutes": 1440,
    # Skip Intro/Outro settings
    "playback.skip_intro_mode": "button",    # "button", "auto", "disabled"
    "playback.skip_outro_mode": "button",    # "button", "auto", "disabled"
    "playback.skip_credits_mode": "button",  # "button", "auto", "disabled"
    "playback.profiles": [],
    # Subtitle settings
    "subtitles.fallback_font_family": "Arial",
    "subtitles.fallback_font_path": None,
    "subtitles.fallback_font_enabled": True,
    "subtitles.providers": [],
    "subtitles.provider_urls": {},
    "subtitles.provider_api_keys": {},
    # Lyrics settings
    "lyrics.providers": [],
    "lyrics.provider_urls": {},
    "lyrics.provider_api_keys": {},
    # Smart collections / list-source provider settings
    # API keys keyed by provider slug: "tmdb", "trakt", "mdblist", "mal", "anilist".
    # Letterboxd & IMDb use public HTML and don't require a key.
    "smart_collections.api_keys": {},
    "smart_collections.enabled": True,
    "smart_collections.cache_ttl_seconds": 21600,  # 6 hours
    # Favorites auto-download / upgrades / RSS sync. All master switches
    # default OFF — favoriting only acts once an operator opts in on prod.
    "automation.favorites_autodownload_enabled": False,
    "automation.upgrades_enabled": False,
    "automation.rss_sync_enabled": False,
    "automation.rss_min_interval_minutes": 15,
    "automation.upgrade_scan_batch_size": 25,
    "automation.max_concurrent_upgrade_downloads": 3,
    "automation.library_scan_interval_hours": 12,
    "automation.realtime_library_monitor": True,
    "automation.rss_seen_ttl_seconds": 1209600,  # 14 days
    "favorites.monitor_enabled": True,
    # Overlay rendering settings
    "overlays.enabled": True,
    "overlays.cache_dir": "data/image_cache",
    # Network/SSL settings
    "network.public_hostname": None,
    "network.bind_host": "0.0.0.0",
    "network.bind_port": 8000,
    "network.enable_https": False,
    "network.ssl_certificate_path": None,
    "network.ssl_key_path": None,
    "network.remote_access_enabled": True,
}
