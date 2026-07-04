import logging
import math
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from pyrate.api.dependencies import CurrentSuperuser, CurrentUser, DatabaseSession
from pyrate.auth.jwt_handler import jwt_handler
from pyrate.models.library import Library
from pyrate.models.media import MediaItem, MediaType
from pyrate.models.user import User
from pyrate.models.viewing_history import ViewingHistory
from pyrate.schemas.invite import InviteListResponse
from pyrate.schemas.media import MediaItemRead
from pyrate.schemas.user import (
    UserCodecSettings,
    UserCreate,
    UserDisplayPreferences,
    UserGamingPreferences,
    UserLanguageSettings,
    UserLibraryAccessRead,
    UserLibraryAccessResponse,
    UserParentalControl,
    UserPermissionOverride,
    UserPlaybackPreferences,
    UserRead,
    UserUpdate,
)
from pyrate.schemas.viewing_history import (
    PaginatedViewingHistoryResponse,
    UserViewingStats,
    ViewingHistoryWithContent,
)
from pyrate.services.friendship import FriendshipService
from pyrate.services.library import MEDIA_ITEM_LOAD_OPTIONS
from pyrate.services.invite import InviteService
from pyrate.services.permission import MEDIA_TYPE_TO_LIBRARY
from pyrate.services.user import UserService

logger = logging.getLogger(__name__)

router = APIRouter()


class PasswordChangeRequest(BaseModel):
    current_password: str | None = None
    new_password: str


@router.get("", response_model=list[UserRead])
async def list_users(
    db: DatabaseSession,
    _: CurrentSuperuser,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    skip = (page - 1) * per_page
    service = UserService(db)
    return await service.list_users(skip=skip, limit=per_page)


@router.get("/online")
async def list_online_users(_: CurrentSuperuser) -> dict:
    """Return the set of users that currently have an active WebSocket."""
    from pyrate.services.websocket import get_websocket_manager

    manager = get_websocket_manager()
    online_ids = manager.get_online_user_ids()
    return {"count": len(online_ids), "user_ids": sorted(online_ids)}


@router.post("", response_model=UserRead)
async def create_user(db: DatabaseSession, user: UserCreate, _: CurrentSuperuser):
    service = UserService(db)
    new_user = await service.create_user(user)
    logger.info("User %s created user %s", _.guid, new_user.guid)
    return new_user


@router.get("/me/permissions")
async def get_my_permissions(
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Get the effective permissions for the current user (resolved from groups + overrides)."""
    from pyrate.services.permission import PermissionService

    service = PermissionService(db)
    permissions = await service.resolve_user_permissions(current_user.guid)
    return permissions


def _library_permission_key(library_type: str) -> str:
    return MEDIA_TYPE_TO_LIBRARY.get(library_type.upper(), library_type.lower())


async def _user_library_access_response(
    db: DatabaseSession,
    user_id: uuid.UUID,
) -> UserLibraryAccessResponse:
    from pyrate.services.permission import PermissionService

    service = PermissionService(db)
    permissions = await service.resolve_user_permissions(user_id)
    libraries = (
        await db.execute(select(Library).order_by(Library.name.asc()))
    ).scalars().all()
    allowed_keys = set(permissions.allowed_libraries)
    items = []
    for library in libraries:
        permission_key = _library_permission_key(library.type)
        items.append(
            UserLibraryAccessRead(
                library_guid=library.guid,
                library_name=library.name,
                library_type=library.type,
                permission_key=permission_key,
                enabled=library.enabled,
                allowed=library.enabled and permission_key in allowed_keys,
            )
        )
    return UserLibraryAccessResponse(user_id=user_id, items=items, total=len(items))


@router.get("/me/library-access", response_model=UserLibraryAccessResponse)
async def get_my_library_access(
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Return effective access for each configured library for the current user."""
    return await _user_library_access_response(db, current_user.guid)


@router.get("/{user_guid}/library-access", response_model=UserLibraryAccessResponse)
async def get_user_library_access(
    user_guid: uuid.UUID,
    db: DatabaseSession,
    _: CurrentSuperuser,
):
    """Return effective access for each configured library for a user."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return await _user_library_access_response(db, user_guid)


@router.get("/{user_guid}", response_model=UserRead)
async def get_user(
    user_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    # Users may only fetch their own data (admins exempt).
    if user_guid != current_user.guid and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    service = UserService(db)
    user = await service.get_by_guid(user_guid)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    return user


@router.put("/{user_guid}", response_model=UserRead)
async def update_user(
    user_guid: uuid.UUID,
    user_update: UserUpdate,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    # Users may only update their own data (admins exempt).
    if user_guid != current_user.guid and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    service = UserService(db)
    user = await service.get_by_guid(user_guid)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # Only superusers may change privileged flags; strip them otherwise so a
    # user cannot escalate their own account via a self-update.
    if not current_user.is_superuser:
        privileged = user_update.model_dump(exclude_unset=True)
        privileged.pop("is_superuser", None)
        privileged.pop("is_active", None)
        user_update = UserUpdate(**privileged)

    # OIDC users cannot change their email.
    update_data = user_update.model_dump(exclude_unset=True)
    if user.oidc_sub and "email" in update_data:
        if update_data["email"] != user.email and user_guid == current_user.guid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OIDC users cannot change their email address",
            )

    updated = await service.update_user(user, user_update)
    logger.info("User %s updated user %s", current_user.guid, user_guid)
    return updated


@router.put("/{user_guid}/password")
async def change_password(
    user_guid: uuid.UUID,
    password_change: PasswordChangeRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    # Users may only change their own password (admins exempt).
    if user_guid != current_user.guid and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    service = UserService(db)
    user = await service.get_by_guid(user_guid)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no password set",
        )

    # OIDC users cannot change their password.
    if user.oidc_sub:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OIDC users cannot change their password",
        )

    # Admins can change another user's password without supplying the current one.
    is_admin_changing_other = (
        current_user.is_superuser and user_guid != current_user.guid
    )

    if not is_admin_changing_other:
        # Verify current password.
        if not password_change.current_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is required",
            )

        if not jwt_handler.verify_password(
            password_change.current_password, user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

    # Hash and persist the new password.
    await service.change_password(user, password_change.new_password)
    logger.info("User %s changed password for user %s", current_user.guid, user_guid)

    return {"message": "Password updated successfully"}


@router.delete("/{user_guid}")
async def delete_user(
    user_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    # Users may only delete their own account (admins exempt).
    if user_guid != current_user.guid and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions"
        )

    service = UserService(db)
    user = await service.get_by_guid(user_guid)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    await service.delete_user(user)
    logger.info("User %s deleted user %s", current_user.guid, user_guid)

    return {"message": "User deleted successfully"}


@router.get("/me/language-settings", response_model=UserLanguageSettings)
async def get_my_language_settings(
    current_user: CurrentUser,
):
    """Get the current user's language settings"""
    return UserLanguageSettings(
        ui_language=current_user.ui_language,
        audio_language=(current_user.audio_languages or [None])[0],
        audio_languages=current_user.audio_languages,
        subtitle_language=current_user.subtitle_language,
    )


@router.put("/me/language-settings", response_model=UserLanguageSettings)
async def update_my_language_settings(
    language_settings: UserLanguageSettings,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Update the current user's language settings"""
    service = UserService(db)
    update_data = language_settings.model_dump(exclude_unset=True)
    if "audio_language" in update_data:
        audio_language = update_data.pop("audio_language")
        update_data["audio_languages"] = [audio_language] if audio_language else []
    updated_user = await service.update_language_settings(current_user, update_data)

    return UserLanguageSettings(
        ui_language=updated_user.ui_language,
        audio_language=(updated_user.audio_languages or [None])[0],
        audio_languages=updated_user.audio_languages,
        subtitle_language=updated_user.subtitle_language,
    )


@router.get("/me/parental-control", response_model=UserParentalControl)
async def get_my_parental_control(current_user: CurrentUser) -> UserParentalControl:
    """Return the current user's parental-control setting."""
    return UserParentalControl(parental_max_age=current_user.parental_max_age)


@router.put("/me/parental-control", response_model=UserParentalControl)
async def update_my_parental_control(
    settings: UserParentalControl,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> UserParentalControl:
    """Update the current user's parental-control max_age.

    Only superusers should realistically tighten this for other users; self-
    service here exists so an adult can opt themselves in (e.g. shared-device
    hygiene). Admin override lives in ``PUT /users/{user_id}/parental-control``.
    """
    current_user.parental_max_age = settings.parental_max_age
    await db.commit()
    await db.refresh(current_user)
    return UserParentalControl(parental_max_age=current_user.parental_max_age)


@router.get("/me/codec-settings", response_model=UserCodecSettings)
async def get_my_codec_settings(
    current_user: CurrentUser,
) -> UserCodecSettings:
    """Get the current user's codec compatibility preferences."""
    qp = current_user.quality_preferences or {}
    return UserCodecSettings(
        supported_video_codecs=qp.get("supported_video_codecs", []),
        supported_audio_codecs=qp.get("supported_audio_codecs", []),
        codec_match_bonus=qp.get("codec_match_bonus", 0),
        codec_mismatch_penalty=qp.get("codec_mismatch_penalty", 0),
    )


@router.put("/me/codec-settings", response_model=UserCodecSettings)
async def update_my_codec_settings(
    codec_settings: UserCodecSettings,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> UserCodecSettings:
    """Update the current user's codec compatibility preferences."""
    service = UserService(db)
    codec_data = {
        "supported_video_codecs": codec_settings.supported_video_codecs,
        "supported_audio_codecs": codec_settings.supported_audio_codecs,
        "codec_match_bonus": codec_settings.codec_match_bonus,
        "codec_mismatch_penalty": codec_settings.codec_mismatch_penalty,
    }
    updated_user = await service.update_codec_settings(current_user, codec_data)

    qp2 = updated_user.quality_preferences or {}
    return UserCodecSettings(
        supported_video_codecs=qp2.get("supported_video_codecs", []),
        supported_audio_codecs=qp2.get("supported_audio_codecs", []),
        codec_match_bonus=qp2.get("codec_match_bonus", 0),
        codec_mismatch_penalty=qp2.get("codec_mismatch_penalty", 0),
    )


@router.get("/me/playback-preferences", response_model=UserPlaybackPreferences)
async def get_my_playback_preferences(
    current_user: CurrentUser,
) -> UserPlaybackPreferences:
    """Get the current user's playback preferences (skip behavior)."""
    prefs = current_user.playback_preferences or {}
    return UserPlaybackPreferences(
        skip_intro_mode=prefs.get("skip_intro_mode", "button"),
        skip_outro_mode=prefs.get("skip_outro_mode", "button"),
        skip_credits_mode=prefs.get("skip_credits_mode", "button"),
    )


@router.put("/me/playback-preferences", response_model=UserPlaybackPreferences)
async def update_my_playback_preferences(
    prefs: UserPlaybackPreferences,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> UserPlaybackPreferences:
    """Update the current user's playback preferences (skip behavior)."""
    service = UserService(db)
    updated_user = await service.update_playback_preferences(
        current_user, prefs.model_dump()
    )
    p = updated_user.playback_preferences or {}
    return UserPlaybackPreferences(
        skip_intro_mode=p.get("skip_intro_mode", "button"),
        skip_outro_mode=p.get("skip_outro_mode", "button"),
        skip_credits_mode=p.get("skip_credits_mode", "button"),
    )


def _gaming_prefs_from(user) -> UserGamingPreferences:
    prefs = user.gaming_preferences or {}
    return UserGamingPreferences(
        keyboard_layout=prefs.get("keyboard_layout", "us"),
        mouse_speed=prefs.get("mouse_speed", 1.0),
        analog_deadzone=prefs.get("analog_deadzone", 0.15),
        dpad_mode=prefs.get("dpad_mode", "dpad"),
    )


def _display_preference_key(preference_id: str, client: str) -> str:
    return f"{client}:{preference_id}"


def _display_prefs_from(
    user,
    preference_id: str,
    client: str,
) -> UserDisplayPreferences:
    preferences = user.display_preferences or {}
    raw = preferences.get(_display_preference_key(preference_id, client), {})
    if not isinstance(raw, dict):
        raw = {}
    return UserDisplayPreferences(
        preference_id=preference_id,
        client=client,
        view_type=raw.get("view_type", "poster"),
        sort_by=raw.get("sort_by", "name"),
        sort_order=raw.get("sort_order", "ascending"),
        index_by=raw.get("index_by"),
        remember_indexing=raw.get("remember_indexing", False),
        show_backdrops=raw.get("show_backdrops", True),
        show_sidebar=raw.get("show_sidebar", True),
        enable_theme_songs=raw.get("enable_theme_songs", False),
        enable_theme_videos=raw.get("enable_theme_videos", False),
        chromecast_version=raw.get("chromecast_version"),
        custom=raw.get("custom", {}),
    )


@router.get("/me/gaming-preferences", response_model=UserGamingPreferences)
async def get_my_gaming_preferences(
    current_user: CurrentUser,
) -> UserGamingPreferences:
    """Get the current user's Lightrays/GOW streaming preferences."""
    return _gaming_prefs_from(current_user)


@router.put("/me/gaming-preferences", response_model=UserGamingPreferences)
async def update_my_gaming_preferences(
    prefs: UserGamingPreferences,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> UserGamingPreferences:
    """Update the current user's Lightrays/GOW streaming preferences.

    Applied on the next `/lightrays/launch` call — the keyboard layout is
    injected as `XKB_DEFAULT_LAYOUT` into the container env and the mouse
    speed is forwarded to Wolf via the payload.
    """
    service = UserService(db)
    updated_user = await service.update_gaming_preferences(
        current_user, prefs.model_dump()
    )
    return _gaming_prefs_from(updated_user)


@router.get(
    "/me/display-preferences/{preference_id}",
    response_model=UserDisplayPreferences,
)
async def get_my_display_preferences(
    preference_id: str,
    current_user: CurrentUser,
    client: str = Query("web", min_length=1, max_length=80),
) -> UserDisplayPreferences:
    """Get the current user's display preferences for a client/view id."""
    return _display_prefs_from(current_user, preference_id, client)


@router.put(
    "/me/display-preferences/{preference_id}",
    response_model=UserDisplayPreferences,
)
async def update_my_display_preferences(
    preference_id: str,
    prefs: UserDisplayPreferences,
    db: DatabaseSession,
    current_user: CurrentUser,
    client: str = Query("web", min_length=1, max_length=80),
) -> UserDisplayPreferences:
    """Update the current user's display preferences for a client/view id."""
    preference_data = prefs.model_dump()
    preference_data["preference_id"] = preference_id
    preference_data["client"] = client
    service = UserService(db)
    updated_user = await service.update_display_preferences(
        current_user,
        _display_preference_key(preference_id, client),
        preference_data,
    )
    return _display_prefs_from(updated_user, preference_id, client)


@router.get("/{user_guid}/permission-overrides", response_model=UserPermissionOverride)
async def get_user_permission_overrides(
    user_guid: uuid.UUID,
    db: DatabaseSession,
    _: CurrentSuperuser,
):
    """Get permission overrides for a user. Superuser only."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return UserPermissionOverride(
        allowed_libraries=user.allowed_libraries,
        max_concurrent_streams=user.max_concurrent_streams,
        max_game_streams=user.max_game_streams,
        max_video_quality=user.max_video_quality,
        max_audio_quality=user.max_audio_quality,
        max_concurrent_transcodings=user.max_concurrent_transcodings,
        offline_download_limit=user.offline_download_limit,
        offline_download_period_minutes=user.offline_download_period_minutes,
        prefetch_limit=user.prefetch_limit,
        prefetch_period_minutes=user.prefetch_period_minutes,
        on_demand_fetch_limit=user.on_demand_fetch_limit,
        on_demand_fetch_period_minutes=user.on_demand_fetch_period_minutes,
        indexer_api_requests_limit=user.indexer_api_requests_limit,
        indexer_api_requests_period_minutes=user.indexer_api_requests_period_minutes,
        indexer_downloads_limit=user.indexer_downloads_limit,
        indexer_downloads_period_minutes=user.indexer_downloads_period_minutes,
        playback_limit=user.playback_limit,
        playback_period_minutes=user.playback_period_minutes,
        favorites_permanent=user.favorites_permanent,
        remote_access_enabled=user.remote_access_enabled,
        access_schedules=user.access_schedules,
    )


@router.put("/{user_guid}/permission-overrides", response_model=UserPermissionOverride)
async def update_user_permission_overrides(
    user_guid: uuid.UUID,
    overrides: UserPermissionOverride,
    db: DatabaseSession,
    _: CurrentSuperuser,
):
    """Set permission overrides for a user. Superuser only. Set fields to null to inherit."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    updated_user = await service.update_permission_overrides(
        user, overrides.model_dump()
    )
    logger.info("User %s updated permission overrides for user %s", _.guid, user_guid)

    return UserPermissionOverride(
        allowed_libraries=updated_user.allowed_libraries,
        max_concurrent_streams=updated_user.max_concurrent_streams,
        max_game_streams=updated_user.max_game_streams,
        max_video_quality=updated_user.max_video_quality,
        max_audio_quality=updated_user.max_audio_quality,
        max_concurrent_transcodings=updated_user.max_concurrent_transcodings,
        offline_download_limit=updated_user.offline_download_limit,
        offline_download_period_minutes=updated_user.offline_download_period_minutes,
        prefetch_limit=updated_user.prefetch_limit,
        prefetch_period_minutes=updated_user.prefetch_period_minutes,
        on_demand_fetch_limit=updated_user.on_demand_fetch_limit,
        on_demand_fetch_period_minutes=updated_user.on_demand_fetch_period_minutes,
        indexer_api_requests_limit=updated_user.indexer_api_requests_limit,
        indexer_api_requests_period_minutes=updated_user.indexer_api_requests_period_minutes,
        indexer_downloads_limit=updated_user.indexer_downloads_limit,
        indexer_downloads_period_minutes=updated_user.indexer_downloads_period_minutes,
        playback_limit=updated_user.playback_limit,
        playback_period_minutes=updated_user.playback_period_minutes,
        favorites_permanent=updated_user.favorites_permanent,
        remote_access_enabled=updated_user.remote_access_enabled,
        access_schedules=updated_user.access_schedules,
    )


@router.get("/{user_guid}/playback-preferences", response_model=UserPlaybackPreferences)
async def get_user_playback_preferences(
    user_guid: uuid.UUID,
    db: DatabaseSession,
    _: CurrentSuperuser,
):
    """Get playback preferences for a user. Superuser only."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    prefs = user.playback_preferences or {}
    return UserPlaybackPreferences(
        skip_intro_mode=prefs.get("skip_intro_mode", "button"),
        skip_outro_mode=prefs.get("skip_outro_mode", "button"),
        skip_credits_mode=prefs.get("skip_credits_mode", "button"),
    )


@router.put("/{user_guid}/playback-preferences", response_model=UserPlaybackPreferences)
async def update_user_playback_preferences(
    user_guid: uuid.UUID,
    prefs: UserPlaybackPreferences,
    db: DatabaseSession,
    _: CurrentSuperuser,
):
    """Set playback preferences for a user. Superuser only."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    updated_user = await service.update_playback_preferences(
        user, prefs.model_dump()
    )
    p = updated_user.playback_preferences or {}
    return UserPlaybackPreferences(
        skip_intro_mode=p.get("skip_intro_mode", "button"),
        skip_outro_mode=p.get("skip_outro_mode", "button"),
        skip_credits_mode=p.get("skip_credits_mode", "button"),
    )


@router.get(
    "/{user_guid}/display-preferences/{preference_id}",
    response_model=UserDisplayPreferences,
)
async def get_user_display_preferences(
    user_guid: uuid.UUID,
    preference_id: str,
    db: DatabaseSession,
    _: CurrentSuperuser,
    client: str = Query("web", min_length=1, max_length=80),
):
    """Get display preferences for a user. Superuser only."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return _display_prefs_from(user, preference_id, client)


@router.put(
    "/{user_guid}/display-preferences/{preference_id}",
    response_model=UserDisplayPreferences,
)
async def update_user_display_preferences(
    user_guid: uuid.UUID,
    preference_id: str,
    prefs: UserDisplayPreferences,
    db: DatabaseSession,
    _: CurrentSuperuser,
    client: str = Query("web", min_length=1, max_length=80),
):
    """Set display preferences for a user. Superuser only."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    preference_data = prefs.model_dump()
    preference_data["preference_id"] = preference_id
    preference_data["client"] = client
    updated_user = await service.update_display_preferences(
        user,
        _display_preference_key(preference_id, client),
        preference_data,
    )
    return _display_prefs_from(updated_user, preference_id, client)


@router.put("/{user_guid}/parental-control", response_model=UserParentalControl)
async def update_user_parental_control(
    user_guid: uuid.UUID,
    settings: UserParentalControl,
    db: DatabaseSession,
    _: CurrentSuperuser,
):
    """Set parental-control max_age for another user. Superuser only."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    user.parental_max_age = settings.parental_max_age
    await db.commit()
    await db.refresh(user)
    return UserParentalControl(parental_max_age=user.parental_max_age)


@router.get("/{user_guid}/stats", response_model=UserViewingStats)
async def get_user_stats(
    user_guid: uuid.UUID,
    db: DatabaseSession,
    _: CurrentSuperuser,
):
    """Get viewing statistics for a specific user. Superuser only."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    stats = await service.get_user_stats(user_guid)
    return UserViewingStats(**stats)


@router.get(
    "/{user_guid}/viewing-history", response_model=PaginatedViewingHistoryResponse
)
async def get_user_viewing_history(
    user_guid: uuid.UUID,
    db: DatabaseSession,
    _: CurrentSuperuser,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Get full viewing history for a specific user. Superuser only."""
    # Verify user exists
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    skip = (page - 1) * per_page

    query = (
        select(ViewingHistory)
        .where(ViewingHistory.user_guid == user_guid)
        .options(
            selectinload(ViewingHistory.media_item).options(*MEDIA_ITEM_LOAD_OPTIONS),
            selectinload(ViewingHistory.media_item)
            .selectinload(MediaItem.parent)
            .selectinload(MediaItem.parent),
        )
        .order_by(ViewingHistory.last_watched_at.desc())
    )

    count_query = select(func.count(ViewingHistory.guid)).where(
        ViewingHistory.user_guid == user_guid
    )
    total = await db.scalar(count_query) or 0
    total_pages = math.ceil(total / per_page) if total > 0 else 1

    query = query.offset(skip).limit(per_page)
    result = await db.execute(query)
    history_items = result.scalars().all()

    items = []
    for item in history_items:
        media_item_data = None
        if item.media_item:
            media_item_data = MediaItemRead.model_validate(item.media_item)

        content_type_str = "movie"
        movie_guid = None
        episode_guid = None
        show_title = None
        season_number = None
        episode_number = None

        if item.media_item:
            if item.media_item.media_type == MediaType.MOVIES:
                content_type_str = "movie"
                movie_guid = item.media_item_guid
            elif item.media_item.media_type == MediaType.SHOWS:
                if item.media_item.parent_guid:
                    content_type_str = "episode"
                    episode_guid = item.media_item_guid
                    episode_number = item.media_item.sequence_number
                    season = item.media_item.parent
                    if season:
                        season_number = season.sequence_number
                        show = season.parent
                        if show:
                            show_title = show.title
                else:
                    content_type_str = "show"
                    movie_guid = item.media_item_guid
            else:
                content_type_str = item.media_item.media_type.value.lower()
                movie_guid = item.media_item_guid

        items.append(
            ViewingHistoryWithContent(
                guid=item.guid,
                user_guid=item.user_guid,
                content_type=content_type_str,
                movie_guid=movie_guid,
                episode_guid=episode_guid,
                progress_seconds=item.progress_seconds,
                duration_seconds=item.duration_seconds,
                progress_percentage=item.progress_percentage,
                is_completed=item.is_completed,
                created_at=item.created_at,
                updated_at=item.updated_at,
                last_watched_at=item.last_watched_at,
                media_item=media_item_data,
                show_title=show_title,
                season_number=season_number,
                episode_number=episode_number,
            )
        )

    return PaginatedViewingHistoryResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/{user_guid}/invites", response_model=list[InviteListResponse])
async def get_user_invites(
    user_guid: uuid.UUID,
    db: DatabaseSession,
    _: CurrentSuperuser,
):
    """Get invites created by a specific user. Superuser only."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    invites, _ = await InviteService(db).get_by_user_paginated(
        user_id=user_guid, skip=0, limit=100
    )
    return [InviteListResponse.model_validate(i) for i in invites]


@router.get("/{user_guid}/friendships")
async def get_user_friendships(
    user_guid: uuid.UUID,
    db: DatabaseSession,
    _: CurrentSuperuser,
):
    """Get all friendships for a specific user. Superuser only."""
    service = UserService(db)
    user = await service.get_by_guid(user_guid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    from pyrate.api.v1.friends import FriendshipRead

    friendship_service = FriendshipService(db)
    accepted = await friendship_service.get_friends(user_guid)
    pending_in = await friendship_service.get_pending_received(user_guid)
    pending_out = await friendship_service.get_pending_sent(user_guid)

    all_friendships = accepted + pending_in + pending_out
    return [FriendshipRead.model_validate(f) for f in all_friendships]
