"""System Settings Service - Compatibility layer using new Key-Value settings.

This module provides backward compatibility for code using the old SystemSettingsService.
It delegates to the new SettingsService internally.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.services.settings import SettingsService

logger = logging.getLogger(__name__)


class SystemSettingsService:
    """
    Compatibility service for managing system settings.
    Delegates to SettingsService internally using the Key-Value store.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._settings_service = SettingsService(session)

    # ==================== Dynamic Library Settings ====================

    async def get_libraries_enabled(self) -> dict[str, bool]:
        """Get which libraries are enabled (dynamic from registered plugins)."""
        from streamarr.libraries import get_available_media_types

        result = {}
        for media_type in get_available_media_types():
            prefix = media_type.lower()
            result[f"{prefix}_enabled"] = await self._settings_service.get(
                f"plugin.{prefix}.enabled", True
            )
        return result

    async def update_libraries_enabled(self, **kwargs) -> dict[str, bool]:
        """Update which libraries are enabled."""
        for key, value in kwargs.items():
            if value is not None:
                media_type = key.removesuffix("_enabled")
                logger.info("Library %s enabled=%s", media_type, value)
                await self._settings_service.set(
                    f"plugin.{media_type}.enabled", value
                )
        return await self.get_libraries_enabled()

    async def get_library_settings(self, library_type: str) -> dict[str, Any]:
        """Get settings for any library type dynamically from plugin schema."""
        from streamarr.libraries import get_plugin_instance

        plugin = get_plugin_instance(library_type)
        if not plugin:
            logger.warning("Requested settings for unknown library type: %s", library_type)
            raise ValueError(f"Unknown library type: {library_type}")

        schema = plugin.get_settings_schema()
        prefix = library_type.lower()
        settings = {}
        for field_name, field_def in schema.items():
            kv_suffix = field_def.get("key", field_name)
            settings[field_name] = await self._settings_service.get(
                f"plugin.{prefix}.{kv_suffix}", field_def["default"]
            )
        return settings

    async def update_library_settings(
        self, library_type: str, **kwargs
    ) -> dict[str, Any]:
        """Update settings for any library type."""
        from streamarr.libraries import get_plugin_instance

        plugin = get_plugin_instance(library_type)
        if not plugin:
            logger.warning("Cannot update settings for unknown library type: %s", library_type)
            raise ValueError(f"Unknown library type: {library_type}")

        schema = plugin.get_settings_schema()
        prefix = library_type.lower()
        for field_name, value in kwargs.items():
            if value is not None:
                kv_suffix = schema.get(field_name, {}).get("key", field_name)
                await self._settings_service.set(
                    f"plugin.{prefix}.{kv_suffix}", value
                )
        logger.debug("Updated library settings for %s: %s", library_type, list(kwargs.keys()))
        return await self.get_library_settings(library_type)

    async def get_library_settings_with_schema(
        self, library_type: str
    ) -> dict[str, Any]:
        """Get library settings including naming schema from plugin."""
        settings = await self.get_library_settings(library_type)
        try:
            from streamarr.libraries import get_plugin_instance

            plugin = get_plugin_instance(library_type)
            if plugin:
                settings["naming_schema"] = plugin.get_naming_schema()
        except Exception:
            logger.warning("Failed to load naming schema for library type %s", library_type, exc_info=True)
            settings["naming_schema"] = None
        return settings

    async def get_naming_settings(self, library_type: str) -> dict[str, Any]:
        """Get naming settings for any library type from plugin's naming schema."""
        from streamarr.libraries import get_plugin_instance

        plugin = get_plugin_instance(library_type)
        if not plugin:
            raise ValueError(f"Unknown library type: {library_type}")

        naming_schema = plugin.get_naming_schema()
        prefix = library_type.lower()

        settings = {}
        for key, default_value in naming_schema.get("defaults", {}).items():
            settings[key] = await self._settings_service.get(
                f"plugin.{prefix}.naming.{key}", default_value
            )
        for key, default_value in naming_schema.get("options", {}).items():
            settings[key] = await self._settings_service.get(
                f"plugin.{prefix}.naming.{key}", default_value
            )
        return settings

    async def update_naming_settings(
        self, library_type: str, **kwargs
    ) -> dict[str, Any]:
        """Update naming settings for any library type."""
        prefix = library_type.lower()
        for key, value in kwargs.items():
            if value is not None:
                await self._settings_service.set(
                    f"plugin.{prefix}.naming.{key}", value
                )
        return await self.get_naming_settings(library_type)

    async def preview_naming(self, library_type: str, **kwargs) -> dict[str, str]:
        """Preview naming with example or custom data."""
        from streamarr.libraries import get_plugin_instance

        plugin = get_plugin_instance(library_type)
        if not plugin:
            raise ValueError(f"Unknown library type: {library_type}")

        preview_data = plugin.get_preview_data()
        preview_data.update(kwargs)

        folder = await plugin.suggest_folder_name(
            media_info=preview_data, tmdb_id=None
        )
        filename = await plugin.suggest_file_name(
            media_info=preview_data, probe_data=None
        )

        return {
            "folder": folder,
            "file": filename,
            "full_path": f"{folder}/{filename}",
        }

    # Metadata settings helpers
    async def get_metadata_settings(self) -> dict[str, Any]:
        """Get metadata provider settings."""
        return {
            "tmdb_api_key": await self._settings_service.get("plugin.tmdb.api_key"),
            "igdb_client_id": await self._settings_service.get("plugin.igdb.client_id"),
            "igdb_client_secret": await self._settings_service.get(
                "plugin.igdb.client_secret"
            ),
            "spotify_client_id": await self._settings_service.get(
                "plugin.spotify.client_id"
            ),
            "spotify_client_secret": await self._settings_service.get(
                "plugin.spotify.client_secret"
            ),
            "locale": await self._settings_service.get("system.locale", "de-DE"),
        }

    async def update_metadata_settings(
        self,
        tmdb_api_key: str | None = None,
        igdb_client_id: str | None = None,
        igdb_client_secret: str | None = None,
        spotify_client_id: str | None = None,
        spotify_client_secret: str | None = None,
        locale: str | None = None,
    ) -> dict[str, Any]:
        """Update metadata provider settings."""
        logger.info("Updating metadata settings")
        if tmdb_api_key is not None:
            await self._settings_service.set("plugin.tmdb.api_key", tmdb_api_key)
        if igdb_client_id is not None:
            await self._settings_service.set("plugin.igdb.client_id", igdb_client_id)
        if igdb_client_secret is not None:
            await self._settings_service.set(
                "plugin.igdb.client_secret", igdb_client_secret
            )
        if spotify_client_id is not None:
            await self._settings_service.set(
                "plugin.spotify.client_id", spotify_client_id
            )
        if spotify_client_secret is not None:
            await self._settings_service.set(
                "plugin.spotify.client_secret", spotify_client_secret
            )
        if locale is not None:
            await self._settings_service.set("system.locale", locale)
        return await self.get_metadata_settings()

    # Email settings helpers
    async def get_email_settings(self) -> dict[str, Any]:
        """Get email settings."""
        return {
            "enabled": await self._settings_service.get("email.enabled", False),
            "smtp_host": await self._settings_service.get(
                "email.smtp_host", "localhost"
            ),
            "smtp_port": await self._settings_service.get("email.smtp_port", 587),
            "smtp_user": await self._settings_service.get("email.smtp_user"),
            "smtp_password": await self._settings_service.get("email.smtp_password"),
            "smtp_use_tls": await self._settings_service.get(
                "email.smtp_use_tls", True
            ),
            "smtp_use_ssl": await self._settings_service.get(
                "email.smtp_use_ssl", False
            ),
            "from_email": await self._settings_service.get(
                "email.from_email", "noreply@streamarr.media"
            ),
            "from_name": await self._settings_service.get(
                "email.from_name", "Streamarr"
            ),
            "reply_to": await self._settings_service.get("email.reply_to"),
        }

    async def update_email_settings(
        self,
        enabled: bool | None = None,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        smtp_use_tls: bool | None = None,
        smtp_use_ssl: bool | None = None,
        from_email: str | None = None,
        from_name: str | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """Update email settings."""
        logger.info("Updating email settings")
        if enabled is not None:
            await self._settings_service.set("email.enabled", enabled)
        if smtp_host is not None:
            await self._settings_service.set("email.smtp_host", smtp_host)
        if smtp_port is not None:
            await self._settings_service.set("email.smtp_port", smtp_port)
        if smtp_user is not None:
            await self._settings_service.set("email.smtp_user", smtp_user)
        if smtp_password is not None:
            await self._settings_service.set("email.smtp_password", smtp_password)
        if smtp_use_tls is not None:
            await self._settings_service.set("email.smtp_use_tls", smtp_use_tls)
        if smtp_use_ssl is not None:
            await self._settings_service.set("email.smtp_use_ssl", smtp_use_ssl)
        if from_email is not None:
            await self._settings_service.set("email.from_email", from_email)
        if from_name is not None:
            await self._settings_service.set("email.from_name", from_name)
        if reply_to is not None:
            await self._settings_service.set("email.reply_to", reply_to)
        return await self.get_email_settings()

    # Transcoding settings helpers
    async def get_transcoding_settings(self) -> dict[str, Any]:
        """Get transcoding settings."""
        return {
            "enabled": await self._settings_service.get("transcoding.enabled", False),
            "max_resolution": await self._settings_service.get(
                "transcoding.max_resolution", "1080p"
            ),
            "hardware_acceleration": await self._settings_service.get(
                "transcoding.hardware_acceleration", False
            ),
            "hardware_acceleration_device": await self._settings_service.get(
                "transcoding.hardware_acceleration_device"
            ),
            "ffmpeg_image": await self._settings_service.get(
                "transcoding.ffmpeg_image", "lscr.io/linuxserver/ffmpeg:latest"
            ),
            "allowed_video_codecs": await self._settings_service.get(
                "transcoding.allowed_video_codecs",
                ["h264", "h265", "av1", "vp9"],
            ),
            "allowed_audio_codecs": await self._settings_service.get(
                "transcoding.allowed_audio_codecs", ["aac", "opus", "mp3"]
            ),
            "default_video_bitrate": await self._settings_service.get(
                "transcoding.default_video_bitrate"
            ),
            "default_audio_bitrate": await self._settings_service.get(
                "transcoding.default_audio_bitrate", "128k"
            ),
            "default_crf": await self._settings_service.get(
                "transcoding.default_crf", 23
            ),
            "hls_segment_duration": await self._settings_service.get(
                "transcoding.hls_segment_duration", 6
            ),
            "thread_count": await self._settings_service.get(
                "transcoding.thread_count", 0
            ),
            "temp_path": await self._settings_service.get(
                "transcoding.temp_path", "/temp"
            ),
            "max_concurrent_transcodes": await self._settings_service.get(
                "transcoding.max_concurrent_transcodes", 0
            ),
            "prefer_compatible_codecs": await self._settings_service.get(
                "transcoding.prefer_compatible_codecs", False
            ),
        }

    async def update_transcoding_settings(
        self,
        enabled: bool | None = None,
        max_resolution: str | None = None,
        hardware_acceleration: bool | None = None,
        hardware_acceleration_device: str | None = None,
        ffmpeg_image: str | None = None,
        allowed_video_codecs: list[str] | None = None,
        allowed_audio_codecs: list[str] | None = None,
        default_video_bitrate: str | None = None,
        default_audio_bitrate: str | None = None,
        default_crf: int | None = None,
        hls_segment_duration: int | None = None,
        thread_count: int | None = None,
        temp_path: str | None = None,
        max_concurrent_transcodes: int | None = None,
        prefer_compatible_codecs: bool | None = None,
    ) -> dict[str, Any]:
        """Update transcoding settings."""
        logger.info("Updating transcoding settings")
        if enabled is not None:
            logger.info("Transcoding enabled=%s", enabled)
            await self._settings_service.set("transcoding.enabled", enabled)
        if max_resolution is not None:
            await self._settings_service.set(
                "transcoding.max_resolution", max_resolution
            )
        if hardware_acceleration is not None:
            logger.info("Transcoding hardware_acceleration=%s", hardware_acceleration)
            await self._settings_service.set(
                "transcoding.hardware_acceleration", hardware_acceleration
            )
        if hardware_acceleration_device is not None:
            await self._settings_service.set(
                "transcoding.hardware_acceleration_device", hardware_acceleration_device
            )
        if ffmpeg_image is not None:
            await self._settings_service.set("transcoding.ffmpeg_image", ffmpeg_image)
        if allowed_video_codecs is not None:
            await self._settings_service.set(
                "transcoding.allowed_video_codecs", allowed_video_codecs
            )
        if allowed_audio_codecs is not None:
            await self._settings_service.set(
                "transcoding.allowed_audio_codecs", allowed_audio_codecs
            )
        if default_video_bitrate is not None:
            await self._settings_service.set(
                "transcoding.default_video_bitrate", default_video_bitrate
            )
        if default_audio_bitrate is not None:
            await self._settings_service.set(
                "transcoding.default_audio_bitrate", default_audio_bitrate
            )
        if default_crf is not None:
            await self._settings_service.set("transcoding.default_crf", default_crf)
        if hls_segment_duration is not None:
            await self._settings_service.set(
                "transcoding.hls_segment_duration", hls_segment_duration
            )
        if thread_count is not None:
            await self._settings_service.set("transcoding.thread_count", thread_count)
        if temp_path is not None:
            await self._settings_service.set("transcoding.temp_path", temp_path)
        if max_concurrent_transcodes is not None:
            await self._settings_service.set(
                "transcoding.max_concurrent_transcodes", max_concurrent_transcodes
            )
        if prefer_compatible_codecs is not None:
            await self._settings_service.set(
                "transcoding.prefer_compatible_codecs", prefer_compatible_codecs
            )
        return await self.get_transcoding_settings()

    # Subtitle settings helpers
    async def get_subtitle_settings(self) -> dict[str, Any]:
        """Get subtitle rendering/provider settings."""
        provider_api_keys = await self._settings_service.get(
            "subtitles.provider_api_keys", {}
        )
        if not isinstance(provider_api_keys, dict):
            provider_api_keys = {}
        return {
            "fallback_font_family": await self._settings_service.get(
                "subtitles.fallback_font_family", "Arial"
            ),
            "fallback_font_path": await self._settings_service.get(
                "subtitles.fallback_font_path"
            ),
            "fallback_font_enabled": await self._settings_service.get(
                "subtitles.fallback_font_enabled", True
            ),
            "subtitle_providers": await self._settings_service.get(
                "subtitles.providers", []
            ),
            "subtitle_provider_urls": await self._settings_service.get(
                "subtitles.provider_urls", {}
            ),
            "subtitle_provider_api_key_configured": {
                provider: bool(api_key)
                for provider, api_key in provider_api_keys.items()
            },
        }

    async def update_subtitle_settings(
        self,
        fallback_font_family: str | None = None,
        fallback_font_path: str | None = None,
        fallback_font_enabled: bool | None = None,
        subtitle_providers: list[str] | None = None,
        subtitle_provider_urls: dict[str, str] | None = None,
        subtitle_provider_api_keys: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Update subtitle rendering/provider settings."""
        logger.info("Updating subtitle settings")
        if fallback_font_family is not None:
            await self._settings_service.set(
                "subtitles.fallback_font_family", fallback_font_family
            )
        if fallback_font_path is not None:
            await self._settings_service.set(
                "subtitles.fallback_font_path", fallback_font_path
            )
        if fallback_font_enabled is not None:
            await self._settings_service.set(
                "subtitles.fallback_font_enabled", fallback_font_enabled
            )
        if subtitle_providers is not None:
            await self._settings_service.set(
                "subtitles.providers", subtitle_providers
            )
        if subtitle_provider_urls is not None:
            await self._settings_service.set(
                "subtitles.provider_urls", subtitle_provider_urls
            )
        if subtitle_provider_api_keys is not None:
            existing = await self._settings_service.get("subtitles.provider_api_keys", {})
            if not isinstance(existing, dict):
                existing = {}
            updated = dict(existing)
            for provider, api_key in subtitle_provider_api_keys.items():
                if api_key:
                    updated[provider] = api_key
            await self._settings_service.set("subtitles.provider_api_keys", updated)
        return await self.get_subtitle_settings()

    # Lyrics settings helpers
    async def get_lyrics_settings(self) -> dict[str, Any]:
        """Get lyrics provider settings."""
        provider_api_keys = await self._settings_service.get(
            "lyrics.provider_api_keys", {}
        )
        if not isinstance(provider_api_keys, dict):
            provider_api_keys = {}
        return {
            "lyrics_providers": await self._settings_service.get(
                "lyrics.providers", []
            ),
            "lyrics_provider_urls": await self._settings_service.get(
                "lyrics.provider_urls", {}
            ),
            "lyrics_provider_api_key_configured": {
                provider: bool(api_key)
                for provider, api_key in provider_api_keys.items()
            },
        }

    async def update_lyrics_settings(
        self,
        lyrics_providers: list[str] | None = None,
        lyrics_provider_urls: dict[str, str] | None = None,
        lyrics_provider_api_keys: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Update lyrics provider settings."""
        logger.info("Updating lyrics settings")
        if lyrics_providers is not None:
            await self._settings_service.set("lyrics.providers", lyrics_providers)
        if lyrics_provider_urls is not None:
            await self._settings_service.set(
                "lyrics.provider_urls", lyrics_provider_urls
            )
        if lyrics_provider_api_keys is not None:
            existing = await self._settings_service.get("lyrics.provider_api_keys", {})
            if not isinstance(existing, dict):
                existing = {}
            updated = dict(existing)
            for provider, api_key in lyrics_provider_api_keys.items():
                if api_key:
                    updated[provider] = api_key
            await self._settings_service.set("lyrics.provider_api_keys", updated)
        return await self.get_lyrics_settings()

    # Network/SSL settings helpers
    async def get_network_settings(self) -> dict[str, Any]:
        """Get network and SSL settings."""
        return {
            "public_hostname": await self._settings_service.get(
                "network.public_hostname"
            ),
            "bind_host": await self._settings_service.get(
                "network.bind_host", "0.0.0.0"
            ),
            "bind_port": await self._settings_service.get(
                "network.bind_port", 8000
            ),
            "enable_https": await self._settings_service.get(
                "network.enable_https", False
            ),
            "ssl_certificate_path": await self._settings_service.get(
                "network.ssl_certificate_path"
            ),
            "ssl_key_path": await self._settings_service.get(
                "network.ssl_key_path"
            ),
            "remote_access_enabled": await self._settings_service.get(
                "network.remote_access_enabled", True
            ),
        }

    async def update_network_settings(
        self,
        public_hostname: str | None = None,
        bind_host: str | None = None,
        bind_port: int | None = None,
        enable_https: bool | None = None,
        ssl_certificate_path: str | None = None,
        ssl_key_path: str | None = None,
        remote_access_enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Update network and SSL settings."""
        logger.info("Updating network settings")
        if public_hostname is not None:
            await self._settings_service.set("network.public_hostname", public_hostname)
        if bind_host is not None:
            await self._settings_service.set("network.bind_host", bind_host)
        if bind_port is not None:
            await self._settings_service.set("network.bind_port", bind_port)
        if enable_https is not None:
            await self._settings_service.set("network.enable_https", enable_https)
        if ssl_certificate_path is not None:
            await self._settings_service.set(
                "network.ssl_certificate_path", ssl_certificate_path
            )
        if ssl_key_path is not None:
            await self._settings_service.set("network.ssl_key_path", ssl_key_path)
        if remote_access_enabled is not None:
            await self._settings_service.set(
                "network.remote_access_enabled", remote_access_enabled
            )
        return await self.get_network_settings()

    # Storage cleanup settings helpers
    async def get_storage_settings(self) -> dict[str, Any]:
        """Get storage management settings."""
        return {
            "temp_max_age_hours": await self._settings_service.get(
                "storage.temp_max_age_hours", 2.0
            ),
            "temp_max_size_gb": await self._settings_service.get(
                "storage.temp_max_size_gb", None
            ),
            "download_record_max_age_days": await self._settings_service.get(
                "storage.download_record_max_age_days", 30
            ),
            "cleanup_orphaned_files": await self._settings_service.get(
                "storage.cleanup_orphaned_files", True
            ),
            "cleanup_duplicates": await self._settings_service.get(
                "storage.cleanup_duplicates", True
            ),
            "cleanup_interval_hours": await self._settings_service.get(
                "storage.cleanup_interval_hours", 6
            ),
        }

    async def update_storage_settings(
        self,
        temp_max_age_hours: float | None = None,
        temp_max_size_gb: float | None = None,
        download_record_max_age_days: int | None = None,
        cleanup_orphaned_files: bool | None = None,
        cleanup_duplicates: bool | None = None,
        cleanup_interval_hours: int | None = None,
    ) -> dict[str, Any]:
        """Update storage management settings."""
        if temp_max_age_hours is not None:
            await self._settings_service.set(
                "storage.temp_max_age_hours", temp_max_age_hours
            )
        if temp_max_size_gb is not None:
            await self._settings_service.set(
                "storage.temp_max_size_gb", temp_max_size_gb
            )
        if download_record_max_age_days is not None:
            await self._settings_service.set(
                "storage.download_record_max_age_days", download_record_max_age_days
            )
        if cleanup_orphaned_files is not None:
            await self._settings_service.set(
                "storage.cleanup_orphaned_files", cleanup_orphaned_files
            )
        if cleanup_duplicates is not None:
            await self._settings_service.set(
                "storage.cleanup_duplicates", cleanup_duplicates
            )
        if cleanup_interval_hours is not None:
            await self._settings_service.set(
                "storage.cleanup_interval_hours", cleanup_interval_hours
            )
        return await self.get_storage_settings()

    # Invite settings helpers
    async def get_invite_settings(self) -> dict[str, Any]:
        """Get invite settings."""
        return {
            "enabled": await self._settings_service.get("invites.enabled", True),
            "default_expiry_hours": await self._settings_service.get(
                "invites.default_expiry_hours", 72
            ),
            "max_expiry_hours": await self._settings_service.get(
                "invites.max_expiry_hours", 168
            ),
            "allow_multiple_uses": await self._settings_service.get(
                "invites.allow_multiple_uses", False
            ),
            "require_admin_creation": await self._settings_service.get(
                "invites.require_admin_creation", False
            ),
        }

    async def update_invite_settings(
        self,
        enabled: bool | None = None,
        default_expiry_hours: int | None = None,
        max_expiry_hours: int | None = None,
        allow_multiple_uses: bool | None = None,
        require_admin_creation: bool | None = None,
    ) -> dict[str, Any]:
        """Update invite settings."""
        logger.info("Updating invite settings")
        if enabled is not None:
            await self._settings_service.set("invites.enabled", enabled)
        if default_expiry_hours is not None:
            await self._settings_service.set(
                "invites.default_expiry_hours", default_expiry_hours
            )
        if max_expiry_hours is not None:
            await self._settings_service.set(
                "invites.max_expiry_hours", max_expiry_hours
            )
        if allow_multiple_uses is not None:
            await self._settings_service.set(
                "invites.allow_multiple_uses", allow_multiple_uses
            )
        if require_admin_creation is not None:
            await self._settings_service.set(
                "invites.require_admin_creation", require_admin_creation
            )
        return await self.get_invite_settings()

    # Lightrays (cloud gaming) settings helpers
    async def get_lightrays_settings(self) -> dict[str, Any]:
        """Get Lightrays cloud gaming settings."""
        return {
            "url": await self._settings_service.get(
                "lightrays.url", "http://lightrays:8080"
            ),
            "default_runtime_profile": await self._settings_service.get(
                "lightrays.default_runtime_profile", "gow-steam"
            ),
            "default_fps": await self._settings_service.get(
                "lightrays.default_fps", 60
            ),
            "default_bitrate_kbps": await self._settings_service.get(
                "lightrays.default_bitrate_kbps", 10000
            ),
        }

    async def update_lightrays_settings(
        self,
        url: str | None = None,
        default_runtime_profile: str | None = None,
        default_fps: int | None = None,
        default_bitrate_kbps: int | None = None,
    ) -> dict[str, Any]:
        """Update Lightrays cloud gaming settings."""
        if url is not None:
            await self._settings_service.set("lightrays.url", url)
        if default_runtime_profile is not None:
            await self._settings_service.set(
                "lightrays.default_runtime_profile", default_runtime_profile
            )
        if default_fps is not None:
            await self._settings_service.set("lightrays.default_fps", default_fps)
        if default_bitrate_kbps is not None:
            await self._settings_service.set(
                "lightrays.default_bitrate_kbps", default_bitrate_kbps
            )
        return await self.get_lightrays_settings()

    # System settings helpers
    async def get_system_settings(self) -> dict[str, Any]:
        """Get system settings (site_name, locale, public app_url)."""
        return {
            "site_name": await self._settings_service.get(
                "system.site_name", "Streamarr"
            ),
            "locale": await self._settings_service.get("system.locale", "de-DE"),
            "app_url": await self._settings_service.get("system.app_url", ""),
        }

    async def update_system_settings(
        self,
        site_name: str | None = None,
        locale: str | None = None,
        app_url: str | None = None,
    ) -> dict[str, Any]:
        """Update system settings. A non-None `app_url` hot-updates the
        process-wide `settings.app_url` so outbound emails + OIDC redirects
        pick up the new value without a restart."""
        logger.info(
            "Updating system settings: site_name=%s locale=%s app_url=%s",
            site_name,
            locale,
            app_url,
        )
        if site_name is not None:
            await self._settings_service.set("system.site_name", site_name)
        if locale is not None:
            await self._settings_service.set("system.locale", locale)
        if app_url is not None:
            await self._settings_service.set("system.app_url", app_url)
            # Hot-reload the runtime setting so existing workers don't need
            # a restart to start emitting the new URL.
            from streamarr.config import settings as app_settings

            app_settings.app_url = app_url.strip()
        return await self.get_system_settings()

    # Subscription settings helpers
    async def get_subscription_settings(self) -> dict[str, bool]:
        """Get subscription settings."""
        return {
            "subscriptions_enabled": await self._settings_service.is_subscriptions_enabled(),
        }

    async def update_subscription_settings(
        self,
        subscriptions_enabled: bool | None = None,
    ) -> dict[str, bool]:
        """Update subscription settings."""
        if subscriptions_enabled is not None:
            logger.info("Subscriptions enabled=%s", subscriptions_enabled)
            await self._settings_service.set(
                "subscriptions.enabled", subscriptions_enabled
            )
        return await self.get_subscription_settings()

    # Invite enable/disable helpers
    async def get_invite_enabled(self) -> dict[str, bool]:
        """Get whether invites are enabled."""
        return {
            "invites_enabled": await self._settings_service.is_invites_enabled(),
        }

    async def update_invite_enabled(
        self,
        invites_enabled: bool | None = None,
    ) -> dict[str, bool]:
        """Update invite enabled setting."""
        if invites_enabled is not None:
            await self._settings_service.set("invites.enabled", invites_enabled)
        return await self.get_invite_enabled()

    # OIDC settings helpers
    async def get_oidc_settings(self) -> dict[str, Any]:
        """Get OIDC settings without exposing the client secret."""
        values = await self._settings_service.get_all("oidc.")
        return {
            "enabled": values.get("oidc.enabled", False),
            "client_id": values.get("oidc.client_id"),
            "client_secret_configured": bool(values.get("oidc.client_secret")),
            "server_metadata_url": values.get("oidc.server_metadata_url"),
            "issuer": values.get("oidc.issuer"),
            "authorization_endpoint": values.get("oidc.authorization_endpoint"),
            "token_endpoint": values.get("oidc.token_endpoint"),
            "userinfo_endpoint": values.get("oidc.userinfo_endpoint"),
            "jwks_uri": values.get("oidc.jwks_uri"),
            "end_session_endpoint": values.get("oidc.end_session_endpoint"),
            "scopes": values.get("oidc.scopes", ["openid", "profile", "email"]),
            "redirect_uri": values.get(
                "oidc.redirect_uri", "http://localhost:8000/api/auth/callback"
            ),
            "post_logout_redirect_uri": values.get(
                "oidc.post_logout_redirect_uri", "http://localhost:8000"
            ),
            "claim_mapping": values.get("oidc.claim_mapping", {}),
            "auto_register_users": values.get("oidc.auto_register_users", True),
            "default_user_active": values.get("oidc.default_user_active", True),
            "default_user_superuser": values.get("oidc.default_user_superuser", False),
            "local_auth_enabled": values.get("oidc.local_auth_enabled", True),
        }

    async def update_oidc_settings(self, **kwargs) -> dict[str, Any]:
        """Update OIDC settings and hot-reload the process config."""
        allowed = {
            "enabled",
            "client_id",
            "client_secret",
            "server_metadata_url",
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "userinfo_endpoint",
            "jwks_uri",
            "end_session_endpoint",
            "scopes",
            "redirect_uri",
            "post_logout_redirect_uri",
            "claim_mapping",
            "auto_register_users",
            "default_user_active",
            "default_user_superuser",
            "local_auth_enabled",
        }
        updated: dict[str, Any] = {}
        for key, value in kwargs.items():
            if key not in allowed or value is None:
                continue
            if key == "client_secret" and value == "":
                continue
            updated[key] = value
            await self._settings_service.set(f"oidc.{key}", value)

        if updated:
            from streamarr.auth.oidc_client import oidc_client
            from streamarr.config import settings as app_settings

            for key, value in updated.items():
                if hasattr(app_settings.oidc, key):
                    setattr(app_settings.oidc, key, value)
            oidc_client._metadata = None
            oidc_client._jwks = None
            oidc_client._jwks_loaded_at = 0.0
            logger.info("Updated OIDC settings: %s", sorted(updated.keys()))

        return await self.get_oidc_settings()

    # Favorites settings helpers
    async def get_favorites_settings(self) -> dict[str, bool]:
        """Get favorites settings."""
        return {
            "favorites_permanent": await self._settings_service.get(
                "favorites.permanent", False
            ),
        }

    async def update_favorites_settings(
        self,
        favorites_permanent: bool | None = None,
    ) -> dict[str, bool]:
        """Update favorites settings."""
        if favorites_permanent is not None:
            await self._settings_service.set(
                "favorites.permanent", favorites_permanent
            )
        return await self.get_favorites_settings()

    # Favorites automation (auto-download / upgrades / RSS sync)
    _AUTOMATION_KEYS = {
        "favorites_autodownload_enabled": (
            "automation.favorites_autodownload_enabled",
            False,
        ),
        "upgrades_enabled": ("automation.upgrades_enabled", False),
        "rss_sync_enabled": ("automation.rss_sync_enabled", False),
        "rss_min_interval_minutes": (
            "automation.rss_min_interval_minutes",
            15,
        ),
        "upgrade_scan_batch_size": (
            "automation.upgrade_scan_batch_size",
            25,
        ),
        "max_concurrent_upgrade_downloads": (
            "automation.max_concurrent_upgrade_downloads",
            3,
        ),
    }

    async def get_automation_settings(self) -> dict[str, object]:
        """Get favorites-automation settings."""
        out: dict[str, object] = {}
        for field, (key, default) in self._AUTOMATION_KEYS.items():
            out[field] = await self._settings_service.get(key, default)
        return out

    async def update_automation_settings(self, **kwargs) -> dict[str, object]:
        """Update favorites-automation settings (only provided fields)."""
        for field, (key, _default) in self._AUTOMATION_KEYS.items():
            if kwargs.get(field) is not None:
                await self._settings_service.set(key, kwargs[field])
        return await self.get_automation_settings()

    # Friends enable/disable helpers
    async def get_friends_enabled(self) -> dict[str, bool]:
        """Get whether friends system is enabled."""
        return {
            "friends_enabled": await self._settings_service.is_friends_enabled(),
        }

    async def update_friends_enabled(
        self,
        friends_enabled: bool | None = None,
    ) -> dict[str, bool]:
        """Update friends enabled setting."""
        if friends_enabled is not None:
            logger.info("Friends enabled=%s", friends_enabled)
            await self._settings_service.set("friends.enabled", friends_enabled)
        return await self.get_friends_enabled()

    # Storage action helpers
    async def get_storage_overview(self) -> dict[str, Any]:
        """Get disk usage overview for all managed storage paths."""
        from streamarr.services.storage_cleanup import StorageCleanupService

        temp_path = await self._settings_service.get("transcoding.temp_path", "/temp")
        downloads_path = await self._settings_service.get(
            "downloads.path", "/downloads"
        )

        cleanup_service = StorageCleanupService(self.session)
        return await cleanup_service.get_storage_overview(
            temp_path=temp_path,
            downloads_path=downloads_path,
        )

    async def trigger_storage_cleanup(self) -> dict[str, Any]:
        """Trigger a manual storage cleanup."""
        logger.info("Manual storage cleanup triggered")
        from streamarr.services.storage_cleanup import StorageCleanupService

        temp_path = await self._settings_service.get("transcoding.temp_path", "/temp")
        temp_max_age = await self._settings_service.get(
            "storage.temp_max_age_hours", 2.0
        )
        temp_max_size = await self._settings_service.get(
            "storage.temp_max_size_gb", None
        )
        download_max_age = await self._settings_service.get(
            "storage.download_record_max_age_days", 30
        )

        cleanup_service = StorageCleanupService(self.session)
        return await cleanup_service.run_full_cleanup(
            temp_path=temp_path,
            temp_max_age_hours=temp_max_age,
            temp_max_size_gb=temp_max_size,
            download_max_age_days=download_max_age,
        )


# Standalone helper functions for use in workers/tasks
async def get_tmdb_api_key(session: AsyncSession) -> str | None:
    """Standalone helper to get TMDB API key."""
    service = SettingsService(session)
    return await service.get_tmdb_api_key()


async def get_tvdb_api_key(session: AsyncSession) -> str | None:
    """Standalone helper to get TVDB API key."""
    service = SettingsService(session)
    return await service.get_tvdb_api_key()


async def get_igdb_credentials(session: AsyncSession) -> tuple[str | None, str | None]:
    """Standalone helper to get IGDB credentials."""
    service = SettingsService(session)
    return await service.get_igdb_credentials()


async def get_locale(session: AsyncSession) -> str:
    """Standalone helper to get locale."""
    service = SettingsService(session)
    return await service.get_locale()
