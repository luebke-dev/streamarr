"""Pydantic schemas for Settings API."""

from pydantic import BaseModel


# Subscription settings
class SubscriptionSettingsResponse(BaseModel):
    subscriptions_enabled: bool


class SubscriptionSettingsUpdate(BaseModel):
    subscriptions_enabled: bool | None = None


# Favorites settings
class FavoritesSettingsResponse(BaseModel):
    favorites_permanent: bool


class FavoritesSettingsUpdate(BaseModel):
    favorites_permanent: bool | None = None


class AutomationSettingsResponse(BaseModel):
    favorites_autodownload_enabled: bool
    upgrades_enabled: bool
    rss_sync_enabled: bool
    rss_min_interval_minutes: int
    upgrade_scan_batch_size: int
    max_concurrent_upgrade_downloads: int


class AutomationSettingsUpdate(BaseModel):
    favorites_autodownload_enabled: bool | None = None
    upgrades_enabled: bool | None = None
    rss_sync_enabled: bool | None = None
    rss_min_interval_minutes: int | None = None
    upgrade_scan_batch_size: int | None = None
    max_concurrent_upgrade_downloads: int | None = None


# Friends settings
class FriendsSettingsResponse(BaseModel):
    friends_enabled: bool


class FriendsSettingsUpdate(BaseModel):
    friends_enabled: bool | None = None


# Invite settings
class InviteSettingsResponse(BaseModel):
    invites_enabled: bool


class InviteSettingsUpdate(BaseModel):
    invites_enabled: bool | None = None


class OIDCSettingsResponse(BaseModel):
    enabled: bool
    client_id: str | None
    client_secret_configured: bool
    server_metadata_url: str | None
    issuer: str | None
    authorization_endpoint: str | None
    token_endpoint: str | None
    userinfo_endpoint: str | None
    jwks_uri: str | None
    end_session_endpoint: str | None
    scopes: list[str]
    redirect_uri: str
    post_logout_redirect_uri: str
    claim_mapping: dict[str, str]
    auto_register_users: bool
    default_user_active: bool
    default_user_superuser: bool
    local_auth_enabled: bool


class OIDCSettingsUpdate(BaseModel):
    enabled: bool | None = None
    client_id: str | None = None
    client_secret: str | None = None
    server_metadata_url: str | None = None
    issuer: str | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    userinfo_endpoint: str | None = None
    jwks_uri: str | None = None
    end_session_endpoint: str | None = None
    scopes: list[str] | None = None
    redirect_uri: str | None = None
    post_logout_redirect_uri: str | None = None
    claim_mapping: dict[str, str] | None = None
    auto_register_users: bool | None = None
    default_user_active: bool | None = None
    default_user_superuser: bool | None = None
    local_auth_enabled: bool | None = None


# Transcoding settings
class TranscodingSettingsResponse(BaseModel):
    enabled: bool
    max_resolution: str
    hardware_acceleration: bool
    hardware_acceleration_device: str | None
    ffmpeg_image: str
    allowed_video_codecs: list[str]
    allowed_audio_codecs: list[str]
    default_video_bitrate: str | None
    default_audio_bitrate: str
    default_crf: int
    hls_segment_duration: int
    thread_count: int
    temp_path: str
    max_concurrent_transcodes: int
    prefer_compatible_codecs: bool


class TranscodingSettingsUpdate(BaseModel):
    enabled: bool | None = None
    max_resolution: str | None = None
    hardware_acceleration: bool | None = None
    hardware_acceleration_device: str | None = None
    ffmpeg_image: str | None = None
    allowed_video_codecs: list[str] | None = None
    allowed_audio_codecs: list[str] | None = None
    default_video_bitrate: str | None = None
    default_audio_bitrate: str | None = None
    default_crf: int | None = None
    hls_segment_duration: int | None = None
    thread_count: int | None = None
    temp_path: str | None = None
    max_concurrent_transcodes: int | None = None
    prefer_compatible_codecs: bool | None = None


# Subtitle settings
class SubtitleSettingsResponse(BaseModel):
    fallback_font_family: str
    fallback_font_path: str | None
    fallback_font_enabled: bool
    subtitle_providers: list[str]
    subtitle_provider_urls: dict[str, str] = {}
    subtitle_provider_api_key_configured: dict[str, bool] = {}


class SubtitleSettingsUpdate(BaseModel):
    fallback_font_family: str | None = None
    fallback_font_path: str | None = None
    fallback_font_enabled: bool | None = None
    subtitle_providers: list[str] | None = None
    subtitle_provider_urls: dict[str, str] | None = None
    subtitle_provider_api_keys: dict[str, str] | None = None


# Lyrics settings
class LyricsSettingsResponse(BaseModel):
    lyrics_providers: list[str]
    lyrics_provider_urls: dict[str, str] = {}
    lyrics_provider_api_key_configured: dict[str, bool] = {}


class LyricsSettingsUpdate(BaseModel):
    lyrics_providers: list[str] | None = None
    lyrics_provider_urls: dict[str, str] | None = None
    lyrics_provider_api_keys: dict[str, str] | None = None


# System settings
class SystemSettingsResponse(BaseModel):
    site_name: str
    locale: str
    app_url: str = ""


class SystemSettingsUpdate(BaseModel):
    site_name: str | None = None
    locale: str | None = None
    app_url: str | None = None


# Network settings
class NetworkSettingsResponse(BaseModel):
    public_hostname: str | None
    bind_host: str
    bind_port: int
    enable_https: bool
    ssl_certificate_path: str | None
    ssl_key_path: str | None
    remote_access_enabled: bool


class NetworkRuntimeResponse(NetworkSettingsResponse):
    source: str
    ssl_files_present: bool
    restart_required: bool
    public_base_url: str | None
    internal_base_url: str
    reverse_proxy_env: dict[str, str]


class NetworkSettingsUpdate(BaseModel):
    public_hostname: str | None = None
    bind_host: str | None = None
    bind_port: int | None = None
    enable_https: bool | None = None
    ssl_certificate_path: str | None = None
    ssl_key_path: str | None = None
    remote_access_enabled: bool | None = None


# Storage settings
class StorageSettingsResponse(BaseModel):
    temp_max_age_hours: float
    temp_max_size_gb: float | None
    download_record_max_age_days: int
    cleanup_orphaned_files: bool
    cleanup_duplicates: bool
    cleanup_interval_hours: int


class StorageSettingsUpdate(BaseModel):
    temp_max_age_hours: float | None = None
    temp_max_size_gb: float | None = None
    download_record_max_age_days: int | None = None
    cleanup_orphaned_files: bool | None = None
    cleanup_duplicates: bool | None = None
    cleanup_interval_hours: int | None = None


class DiskUsageResponse(BaseModel):
    path: str
    total: int
    used: int
    free: int
    usage_percent: float
    directory_size: int = 0


class StorageOverviewResponse(BaseModel):
    temp: DiskUsageResponse
    downloads: DiskUsageResponse
    libraries: dict[str, DiskUsageResponse]


# Libraries enabled settings
class LibrariesEnabledUpdate(BaseModel):
    """Update which libraries are enabled."""
    movies: bool | None = None
    shows: bool | None = None
    music: bool | None = None
    games: bool | None = None
    books: bool | None = None
    audiobooks: bool | None = None


# Naming settings
class NamingSettingsUpdate(BaseModel):
    """Update naming settings for a library type."""
    folder_template: str | None = None
    file_template: str | None = None
    season_folder_template: str | None = None


# Library settings (generic)
class LibrarySettingsUpdate(BaseModel):
    """Update settings for a library type."""
    enabled: bool | None = None
    library_path: str | None = None
    enable_on_demand_downloads: bool | None = None
    enable_prefetch_downloads: bool | None = None


class PermissionSettingsResponse(BaseModel):
    """Global permission defaults (caps)."""
    allowed_libraries: list[str]
    max_concurrent_streams: int
    max_game_streams: int
    max_video_quality: str
    max_audio_quality: str
    max_concurrent_transcodings: int
    offline_download_limit: int | None
    offline_download_period_minutes: int
    prefetch_limit: int | None
    prefetch_period_minutes: int
    on_demand_fetch_limit: int | None
    on_demand_fetch_period_minutes: int
    indexer_api_requests_limit: int | None
    indexer_api_requests_period_minutes: int
    indexer_downloads_limit: int | None
    indexer_downloads_period_minutes: int
    playback_limit: int | None
    playback_period_minutes: int


class PermissionSettingsUpdate(BaseModel):
    """Update global permission defaults."""
    allowed_libraries: list[str] | None = None
    max_concurrent_streams: int | None = None
    max_game_streams: int | None = None
    max_video_quality: str | None = None
    max_audio_quality: str | None = None
    max_concurrent_transcodings: int | None = None
    offline_download_limit: int | None = None
    offline_download_period_minutes: int | None = None
    prefetch_limit: int | None = None
    prefetch_period_minutes: int | None = None
    on_demand_fetch_limit: int | None = None
    on_demand_fetch_period_minutes: int | None = None
    indexer_api_requests_limit: int | None = None
    indexer_api_requests_period_minutes: int | None = None
    indexer_downloads_limit: int | None = None
    indexer_downloads_period_minutes: int | None = None
    playback_limit: int | None = None
    playback_period_minutes: int | None = None
