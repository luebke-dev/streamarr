"""Settings API endpoints - Uses database for configuration storage."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.api.dependencies import get_db_session
from streamarr.auth.dependencies import get_current_superuser, get_current_user
from streamarr.schemas.settings import (
    AutomationSettingsResponse,
    AutomationSettingsUpdate,
    FavoritesSettingsResponse,
    FavoritesSettingsUpdate,
    FriendsSettingsResponse,
    FriendsSettingsUpdate,
    InviteSettingsResponse,
    InviteSettingsUpdate,
    LibrariesEnabledUpdate,
    LibrarySettingsUpdate,
    LyricsSettingsResponse,
    LyricsSettingsUpdate,
    NamingSettingsUpdate,
    NetworkRuntimeResponse,
    NetworkSettingsResponse,
    NetworkSettingsUpdate,
    OIDCSettingsResponse,
    OIDCSettingsUpdate,
    PermissionSettingsResponse,
    PermissionSettingsUpdate,
    StorageOverviewResponse,
    StorageSettingsResponse,
    StorageSettingsUpdate,
    SubscriptionSettingsResponse,
    SubscriptionSettingsUpdate,
    SubtitleSettingsResponse,
    SubtitleSettingsUpdate,
    SystemSettingsResponse,
    SystemSettingsUpdate,
    TranscodingSettingsResponse,
    TranscodingSettingsUpdate,
)
from streamarr.schemas.activity_log import ActivityLogCreate
from streamarr.services.activity_log import ActivityLogService
from streamarr.services.network_runtime import get_network_runtime_config
from streamarr.services.settings import SettingsService
from streamarr.services.system_settings import SystemSettingsService

logger = logging.getLogger(__name__)

router = APIRouter()


async def _log_settings_update(
    session: AsyncSession,
    current_user,
    category: str,
    updated_fields,
) -> None:
    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type=f"settings.{category}_update",
            message=f"Updated {category} settings",
            entity_type="settings",
            extra_data=json.dumps(
                {"updated_fields": sorted(updated_fields)},
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )


# Libraries endpoints - which libraries are enabled
@router.get("/libraries")
async def get_libraries_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user),
):
    """Get which libraries are enabled (available to all authenticated users)"""
    service = SystemSettingsService(session)
    return await service.get_libraries_enabled()


@router.put("/libraries")
async def update_libraries_settings(
    libraries_settings: LibrariesEnabledUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update which libraries are enabled (admin only)"""
    service = SystemSettingsService(session)
    result = await service.update_libraries_enabled(
        **libraries_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated libraries settings", current_user.guid)
    return result


# Subscription Settings endpoints
@router.get("/subscriptions", response_model=SubscriptionSettingsResponse)
async def get_subscription_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user),
):
    """Get subscription settings (available to all authenticated users)"""
    service = SystemSettingsService(session)
    settings = await service.get_subscription_settings()
    return SubscriptionSettingsResponse(**settings)


@router.put("/subscriptions", response_model=SubscriptionSettingsResponse)
async def update_subscription_settings(
    subscription_settings: SubscriptionSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update subscription settings (admin only)"""
    service = SystemSettingsService(session)
    settings = await service.update_subscription_settings(
        **subscription_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated subscription settings", current_user.guid)
    await _log_settings_update(
        session,
        current_user,
        "subscriptions",
        subscription_settings.model_dump(exclude_none=True).keys(),
    )
    return SubscriptionSettingsResponse(**settings)


# Invite Settings endpoints
@router.get("/invites", response_model=InviteSettingsResponse)
async def get_invite_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user),
):
    """Get invite settings (available to all authenticated users)"""
    service = SystemSettingsService(session)
    settings = await service.get_invite_enabled()
    return InviteSettingsResponse(**settings)


@router.put("/invites", response_model=InviteSettingsResponse)
async def update_invite_settings(
    invite_settings: InviteSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update invite settings (admin only)"""
    service = SystemSettingsService(session)
    settings = await service.update_invite_enabled(
        **invite_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated invite settings", current_user.guid)
    await _log_settings_update(
        session,
        current_user,
        "invites",
        invite_settings.model_dump(exclude_none=True).keys(),
    )
    return InviteSettingsResponse(**settings)


@router.get("/oidc", response_model=OIDCSettingsResponse)
async def get_oidc_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get OIDC settings (admin only)."""
    settings = await SystemSettingsService(session).get_oidc_settings()
    return OIDCSettingsResponse(**settings)


@router.put("/oidc", response_model=OIDCSettingsResponse)
async def update_oidc_settings(
    oidc_settings: OIDCSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update OIDC settings (admin only)."""
    payload = oidc_settings.model_dump(exclude_none=True)
    settings = await SystemSettingsService(session).update_oidc_settings(**payload)
    await _log_settings_update(
        session,
        current_user,
        "oidc",
        payload.keys(),
    )
    return OIDCSettingsResponse(**settings)


# Favorites Settings endpoints
@router.get("/favorites", response_model=FavoritesSettingsResponse)
async def get_favorites_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user),
):
    """Get favorites settings (available to all authenticated users)"""
    service = SystemSettingsService(session)
    settings = await service.get_favorites_settings()
    return FavoritesSettingsResponse(**settings)


@router.put("/favorites", response_model=FavoritesSettingsResponse)
async def update_favorites_settings(
    favorites_settings: FavoritesSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update favorites settings (admin only)"""
    service = SystemSettingsService(session)
    settings = await service.update_favorites_settings(
        **favorites_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated favorites settings", current_user.guid)
    await _log_settings_update(
        session,
        current_user,
        "favorites",
        favorites_settings.model_dump(exclude_none=True).keys(),
    )
    return FavoritesSettingsResponse(**settings)


# Automation (library scans / auto-download / upgrades / RSS sync) endpoints
@router.get("/automation", response_model=AutomationSettingsResponse)
async def get_automation_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get automation settings (admin only)."""
    service = SystemSettingsService(session)
    settings = await service.get_automation_settings()
    return AutomationSettingsResponse(**settings)


@router.put("/automation", response_model=AutomationSettingsResponse)
async def update_automation_settings(
    automation_settings: AutomationSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update automation settings (admin only)."""
    service = SystemSettingsService(session)
    settings = await service.update_automation_settings(
        **automation_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated automation settings", current_user.guid)
    await _log_settings_update(
        session,
        current_user,
        "automation",
        automation_settings.model_dump(exclude_none=True).keys(),
    )
    return AutomationSettingsResponse(**settings)


# Friends Settings endpoints
@router.get("/friends", response_model=FriendsSettingsResponse)
async def get_friends_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user),
):
    """Get friends settings (available to all authenticated users)"""
    service = SystemSettingsService(session)
    settings = await service.get_friends_enabled()
    return FriendsSettingsResponse(**settings)


@router.put("/friends", response_model=FriendsSettingsResponse)
async def update_friends_settings(
    friends_settings: FriendsSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update friends settings (admin only)"""
    service = SystemSettingsService(session)
    settings = await service.update_friends_enabled(
        **friends_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated friends settings", current_user.guid)
    await _log_settings_update(
        session,
        current_user,
        "friends",
        friends_settings.model_dump(exclude_none=True).keys(),
    )
    return FriendsSettingsResponse(**settings)


# Transcoding Settings endpoints
@router.get("/transcoding", response_model=TranscodingSettingsResponse)
async def get_transcoding_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user),
):
    """Get transcoding settings (available to all authenticated users)"""
    service = SystemSettingsService(session)
    settings = await service.get_transcoding_settings()
    return TranscodingSettingsResponse(**settings)


@router.put("/transcoding", response_model=TranscodingSettingsResponse)
async def update_transcoding_settings(
    transcoding_settings: TranscodingSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update transcoding settings (admin only)"""
    service = SystemSettingsService(session)
    settings = await service.update_transcoding_settings(
        **transcoding_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated transcoding settings", current_user.guid)
    return TranscodingSettingsResponse(**settings)


# Subtitle Settings endpoints
@router.get("/subtitles", response_model=SubtitleSettingsResponse)
async def get_subtitle_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user),
):
    """Get subtitle rendering/provider settings."""
    service = SystemSettingsService(session)
    settings = await service.get_subtitle_settings()
    return SubtitleSettingsResponse(**settings)


@router.put("/subtitles", response_model=SubtitleSettingsResponse)
async def update_subtitle_settings(
    subtitle_settings: SubtitleSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update subtitle rendering/provider settings (admin only)."""
    service = SystemSettingsService(session)
    settings = await service.update_subtitle_settings(
        **subtitle_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated subtitle settings", current_user.guid)
    await _log_settings_update(
        session,
        current_user,
        "subtitles",
        subtitle_settings.model_dump(exclude_none=True).keys(),
    )
    return SubtitleSettingsResponse(**settings)


# Lyrics Settings endpoints
@router.get("/lyrics", response_model=LyricsSettingsResponse)
async def get_lyrics_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user),
):
    """Get lyrics provider settings."""
    service = SystemSettingsService(session)
    settings = await service.get_lyrics_settings()
    return LyricsSettingsResponse(**settings)


@router.put("/lyrics", response_model=LyricsSettingsResponse)
async def update_lyrics_settings(
    lyrics_settings: LyricsSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update lyrics provider settings (admin only)."""
    service = SystemSettingsService(session)
    settings = await service.update_lyrics_settings(
        **lyrics_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated lyrics settings", current_user.guid)
    await _log_settings_update(
        session,
        current_user,
        "lyrics",
        lyrics_settings.model_dump(exclude_none=True).keys(),
    )
    return LyricsSettingsResponse(**settings)


# System Settings
@router.get("/system", response_model=SystemSettingsResponse)
async def get_system_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_user),
):
    """Get system settings (available to all authenticated users)"""
    service = SystemSettingsService(session)
    settings = await service.get_system_settings()
    return SystemSettingsResponse(**settings)


@router.put("/system", response_model=SystemSettingsResponse)
async def update_system_settings(
    system_settings: SystemSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update system settings (admin only)"""
    service = SystemSettingsService(session)
    settings = await service.update_system_settings(
        **system_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated system settings", current_user.guid)
    await _log_settings_update(
        session,
        current_user,
        "system",
        system_settings.model_dump(exclude_none=True).keys(),
    )
    return SystemSettingsResponse(**settings)


# Network Settings
@router.get("/network", response_model=NetworkSettingsResponse)
async def get_network_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get network and SSL settings (admin only)."""
    service = SystemSettingsService(session)
    settings = await service.get_network_settings()
    return NetworkSettingsResponse(**settings)


@router.put("/network", response_model=NetworkSettingsResponse)
async def update_network_settings(
    network_settings: NetworkSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update network and SSL settings (admin only)."""
    service = SystemSettingsService(session)
    settings = await service.update_network_settings(
        **network_settings.model_dump(exclude_none=True)
    )
    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type="settings.network_update",
            message="Updated network settings",
            entity_type="settings",
            extra_data=json.dumps(
                {
                    "updated_fields": sorted(
                        network_settings.model_dump(exclude_none=True).keys()
                    ),
                    "bind_host": settings["bind_host"],
                    "bind_port": settings["bind_port"],
                    "enable_https": settings["enable_https"],
                    "public_hostname": settings["public_hostname"],
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )
    logger.info("Admin %s updated network settings", current_user.guid)
    return NetworkSettingsResponse(**settings)


@router.get("/network/runtime", response_model=NetworkRuntimeResponse)
async def get_network_runtime_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get effective network settings used by the startup runner."""
    config = await get_network_runtime_config(session)
    return NetworkRuntimeResponse(
        public_hostname=config.public_hostname,
        bind_host=config.bind_host,
        bind_port=config.bind_port,
        enable_https=config.enable_https,
        ssl_certificate_path=config.ssl_certificate_path,
        ssl_key_path=config.ssl_key_path,
        remote_access_enabled=config.remote_access_enabled,
        source=config.source,
        ssl_files_present=config.ssl_files_present,
        restart_required=config.restart_required,
        public_base_url=config.public_base_url,
        internal_base_url=config.internal_base_url,
        reverse_proxy_env=config.reverse_proxy_env,
    )


# Storage Settings
@router.get("/storage")
async def get_storage_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get storage management settings (admin only)"""
    service = SystemSettingsService(session)
    return await service.get_storage_settings()


@router.put("/storage", response_model=StorageSettingsResponse)
async def update_storage_settings(
    storage_settings: StorageSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update storage management settings (admin only)"""
    service = SystemSettingsService(session)
    settings = await service.update_storage_settings(
        **storage_settings.model_dump(exclude_none=True)
    )
    logger.info("Admin %s updated storage settings", current_user.guid)
    return StorageSettingsResponse(**settings)


@router.get("/storage/overview", response_model=StorageOverviewResponse)
async def get_storage_overview(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get disk usage overview for all managed storage paths (admin only)"""
    service = SystemSettingsService(session)
    return await service.get_storage_overview()


@router.post("/storage/cleanup")
async def trigger_storage_cleanup(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Trigger a manual storage cleanup (admin only)"""
    service = SystemSettingsService(session)
    logger.info("Admin %s triggered storage cleanup", current_user.guid)
    return await service.trigger_storage_cleanup()


# ============================================================================
# Dynamic library settings - MUST be after all static routes to avoid conflicts
# ============================================================================


@router.get("/naming/{library_type}")
async def get_naming_settings(
    library_type: str,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get naming settings for a library type"""
    service = SystemSettingsService(session)
    try:
        return await service.get_naming_settings(library_type)
    except ValueError:
        raise HTTPException(
            status_code=404, detail=f"Unknown library type: {library_type}"
        )


@router.put("/naming/{library_type}")
async def update_naming_settings(
    library_type: str,
    naming_settings: NamingSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update naming settings for a library type"""
    service = SystemSettingsService(session)
    try:
        result = await service.update_naming_settings(
            library_type, **naming_settings.model_dump(exclude_none=True)
        )
        logger.info("Admin %s updated naming settings for %s", current_user.guid, library_type)
        return result
    except ValueError:
        raise HTTPException(
            status_code=404, detail=f"Unknown library type: {library_type}"
        )


@router.post("/naming/{library_type}/preview")
async def preview_naming(
    library_type: str,
    preview_request: NamingSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Preview naming with example or custom data for a library type"""
    service = SystemSettingsService(session)
    try:
        return await service.preview_naming(
            library_type, **preview_request.model_dump(exclude_none=True)
        )
    except ValueError:
        raise HTTPException(
            status_code=404, detail=f"Unknown library type: {library_type}"
        )


# Permission Defaults endpoints
def _permission_settings_response(settings: dict) -> PermissionSettingsResponse:
    """Build a PermissionSettingsResponse from a ``permissions.``-prefixed dict.

    Shared by the GET and PUT handlers so the key list and defaults live in a
    single place.
    """
    return PermissionSettingsResponse(
        allowed_libraries=settings.get(
            "permissions.allowed_libraries",
            ["movies", "series", "games", "books", "music"],
        ),
        max_concurrent_streams=settings.get("permissions.max_concurrent_streams", 3),
        max_game_streams=settings.get("permissions.max_game_streams", 1),
        max_video_quality=settings.get("permissions.max_video_quality", "uhd"),
        max_audio_quality=settings.get("permissions.max_audio_quality", "lossless"),
        max_concurrent_transcodings=settings.get(
            "permissions.max_concurrent_transcodings", 2
        ),
        offline_download_limit=settings.get("permissions.offline_download_limit"),
        offline_download_period_minutes=settings.get(
            "permissions.offline_download_period_minutes", 1440
        ),
        prefetch_limit=settings.get("permissions.prefetch_limit"),
        prefetch_period_minutes=settings.get(
            "permissions.prefetch_period_minutes", 1440
        ),
        on_demand_fetch_limit=settings.get("permissions.on_demand_fetch_limit"),
        on_demand_fetch_period_minutes=settings.get(
            "permissions.on_demand_fetch_period_minutes", 1440
        ),
        indexer_api_requests_limit=settings.get(
            "permissions.indexer_api_requests_limit"
        ),
        indexer_api_requests_period_minutes=settings.get(
            "permissions.indexer_api_requests_period_minutes", 60
        ),
        indexer_downloads_limit=settings.get("permissions.indexer_downloads_limit"),
        indexer_downloads_period_minutes=settings.get(
            "permissions.indexer_downloads_period_minutes", 1440
        ),
        playback_limit=settings.get("permissions.playback_limit"),
        playback_period_minutes=settings.get(
            "permissions.playback_period_minutes", 1440
        ),
    )


@router.get("/permissions", response_model=PermissionSettingsResponse)
async def get_permission_settings(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get global permission defaults (admin only)."""
    service = SettingsService(session)
    settings = await service.get_all("permissions.")
    return _permission_settings_response(settings)


@router.put("/permissions", response_model=PermissionSettingsResponse)
async def update_permission_settings(
    perm_settings: PermissionSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update global permission defaults (admin only)."""
    service = SettingsService(session)
    updates = perm_settings.model_dump(exclude_none=True)
    for key, value in updates.items():
        await service.set(f"permissions.{key}", value)
    logger.info("Admin %s updated permission settings", current_user.guid)
    await _log_settings_update(session, current_user, "permissions", updates.keys())

    # Return updated state
    settings = await service.get_all("permissions.")
    return _permission_settings_response(settings)


@router.get("/{library_type}")
async def get_library_settings(
    library_type: str,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get settings for a library type including naming schema from plugin"""
    service = SystemSettingsService(session)
    try:
        return await service.get_library_settings_with_schema(library_type)
    except ValueError:
        raise HTTPException(
            status_code=404, detail=f"Unknown library type: {library_type}"
        )


@router.put("/{library_type}")
async def update_library_settings(
    library_type: str,
    settings: LibrarySettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update settings for a library type"""
    service = SystemSettingsService(session)
    try:
        result = await service.update_library_settings(
            library_type, **settings.model_dump(exclude_none=True)
        )
        logger.info("Admin %s updated library settings for %s", current_user.guid, library_type)
        return result
    except ValueError:
        raise HTTPException(
            status_code=404, detail=f"Unknown library type: {library_type}"
        )
