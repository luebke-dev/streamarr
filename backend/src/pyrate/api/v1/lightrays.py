"""Lightrays cloud-gaming API — launch / stop / stats for game streaming sessions."""

import logging
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pyrate.api.dependencies import CurrentUser, DatabaseSession, UserPermissionsDep
from pyrate.models.media import MediaType
from pyrate.services.container_profiles import resolve_launch_config
from pyrate.services.lightrays import (
    get_session_record,
    get_stats,
    launch_session,
    release_session,
    release_session_slot,
    reserve_session_slot,
    stop_session,
)
from pyrate.services.media import MediaService
from pyrate.services.media_access import require_media_play_access
from pyrate.services.viewing_history import ViewingHistoryService

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Request / Response schemas ──────────────────────────────────────────────


class LaunchRequest(BaseModel):
    width: int = Field(default=1920, ge=64, le=7680)
    height: int = Field(default=1080, ge=64, le=4320)
    fps: int = Field(default=60, ge=15, le=120)
    bitrate_kbps: int = Field(default=10000, ge=500, le=50000)


class LaunchResponse(BaseModel):
    session_id: str
    websocket_url: str
    ws_ticket: str = ""
    ice_servers: list[dict[str, Any]] = []


class StopRequest(BaseModel):
    session_id: str


def _validate_lightrays_docker_image(value: Any) -> str | None:
    if value is None:
        return None
    image = str(value).strip()
    if not image:
        return None
    allowed = set("._-/:@")
    if (
        len(image) > 255
        or image.startswith(("-", "/", ":"))
        or image.endswith("/")
        or "//" in image
        or ".." in image
        or not all(ch.isascii() and (ch.isalnum() or ch in allowed) for ch in image)
    ):
        raise HTTPException(status_code=400, detail="Invalid Lightrays Docker image")
    return image


async def _safe_release_slot(user_id: str, token: str) -> None:
    """Best-effort release of a reservation slot; never raise into the caller."""
    try:
        await release_session_slot(user_id, token)
    except Exception as exc:
        logger.warning("Failed to release lightrays reservation slot: %s", exc)


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/launch/{media_id}", response_model=LaunchResponse)
async def lightrays_launch(
    media_id: UUID,
    body: LaunchRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
):
    """Launch a Lightrays XFCE desktop session for a game."""
    media_service = MediaService(db)
    media_item = await media_service.get_by_id(media_id)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media not found")

    if media_item.media_type != MediaType.GAMES:
        raise HTTPException(
            status_code=400,
            detail="Lightrays streaming is only available for games",
        )
    require_media_play_access(current_user, permissions, media_item)

    # Enforce permissions.max_game_streams. ``0`` means streaming is fully
    # disabled for this user; a positive cap blocks launches once that
    # many sessions are already running. The actual count→check→reserve is
    # done atomically just before launch (see reserve_session_slot below) to
    # avoid a TOCTOU race between two concurrent launches.
    max_game_streams = permissions.max_game_streams if permissions else 0
    if max_game_streams <= 0:
        raise HTTPException(
            status_code=403,
            detail="Game streaming is not allowed for your account.",
        )

    gaming_prefs = current_user.gaming_preferences or {}
    keyboard_layout = gaming_prefs.get("keyboard_layout")
    if keyboard_layout is not None:
        keyboard_layout = str(keyboard_layout)
        if (
            not keyboard_layout
            or len(keyboard_layout) > 32
            or not all(ch.isalnum() or ch in "-_" for ch in keyboard_layout)
        ):
            raise HTTPException(status_code=400, detail="Invalid keyboard layout")
    mouse_speed = gaming_prefs.get("mouse_speed")
    if mouse_speed is not None:
        try:
            mouse_speed = float(mouse_speed)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid mouse speed") from exc
        if not 0.1 <= mouse_speed <= 5.0:
            raise HTTPException(status_code=400, detail="Invalid mouse speed")

    # Resolve the effective launch config from the game's container profile
    # (extra_data.lightrays.profile) merged with any per-game overrides. When a
    # game references no profile this falls back to the builtin "steam" profile,
    # preserving today's image/runtime_profile behaviour. The resulting Docker
    # image still goes through the same admin-gated validation as before.
    launch_config = await resolve_launch_config(db, media_item)
    docker_image = _validate_lightrays_docker_image(launch_config.get("docker_image"))
    runtime_profile = launch_config.get("runtime_profile")
    app_env = launch_config.get("app_env") or None

    # Atomically reserve a concurrency slot. ``None`` means the user is
    # already at the cap. The reservation counts toward the cap until the
    # real session record replaces it, closing the count→check→launch race.
    reservation = await reserve_session_slot(str(current_user.guid), max_game_streams)
    if reservation is None:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum concurrent game streams reached ({max_game_streams}). Stop another session first.",
        )

    try:
        # Passing ``media_id`` makes launch + Redis bookkeeping atomic inside
        # launch_session: it records the session and rolls the Lightrays
        # launch back if recording fails, so no orphaned GPU session is left
        # behind. This is the single record_session path.
        data = await launch_session(
            title=media_item.title or "Game",
            width=body.width,
            height=body.height,
            fps=body.fps,
            bitrate_kbps=body.bitrate_kbps,
            user_id=str(current_user.guid),
            # Per-user-per-game app_id so each user's Steam profile and
            # installed games are isolated, and concurrent launches from
            # different users don't collide on /home/retro.
            app_id=f"{current_user.guid}-{media_item.guid}",
            docker_image=docker_image,
            runtime_profile=runtime_profile,
            app_env=app_env,
            keyboard_layout=keyboard_layout,
            mouse_speed=mouse_speed,
            media_id=str(media_item.guid),
        )
    except Exception as exc:
        # Free the reserved slot so a failed launch doesn't hold capacity.
        await _safe_release_slot(str(current_user.guid), reservation)
        logger.error("Lightrays launch failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Failed to start game streaming session — is Lightrays running?",
        ) from exc

    # The real session record now holds the slot; drop the placeholder.
    await _safe_release_slot(str(current_user.guid), reservation)

    session_id = data["session_id"]

    # Surface the stream in viewing history so games appear in
    # recently-watched / continue-watching alongside other media.
    try:
        await ViewingHistoryService(db).create_or_update(
            user_guid=current_user.guid,
            media_item_guid=media_item.guid,
            progress_seconds=0.0,
        )
    except Exception as exc:
        logger.warning("Failed to write game stream history: %s", exc)

    return LaunchResponse(
        session_id=session_id,
        websocket_url=data.get("websocket_url") or data.get("ws_url") or "",
        ws_ticket=data.get("ws_ticket") or "",
        ice_servers=data.get("ice_servers", []),
    )


@router.post("/stop")
async def lightrays_stop(
    body: StopRequest, db: DatabaseSession, current_user: CurrentUser
):
    """Stop an active Lightrays session."""
    try:
        record = await get_session_record(body.session_id)
    except Exception as exc:
        logger.warning("Failed to read lightrays session record: %s", exc)
        record = None
    # Fail closed: an unknown session (no Redis record) is treated as not
    # found rather than proxied to Lightrays, so ownership no longer depends
    # on Lightrays-side auth being active. Superusers may act on any session.
    if not current_user.is_superuser:
        if record is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if record.get("user_id") != str(current_user.guid):
            raise HTTPException(
                status_code=403, detail="Not authorized for this stream"
            )

    try:
        result = await stop_session(
            body.session_id,
            user_id=str(current_user.guid),
            admin=current_user.is_superuser,
        )
    except Exception as exc:
        logger.warning("Lightrays stop failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="Failed to stop streaming session"
        ) from exc

    # Release the Redis tracking entry and capture the start time so we
    # can record final play duration in viewing history.
    meta = None
    try:
        meta = await release_session(body.session_id)
    except Exception as exc:
        logger.warning("Failed to release lightrays session: %s", exc)

    if meta and meta.get("media_id") and meta.get("started_at"):
        try:
            elapsed = max(0.0, time.time() - float(meta["started_at"]))
            await ViewingHistoryService(db).create_or_update(
                user_guid=current_user.guid,
                media_item_guid=UUID(meta["media_id"]),
                progress_seconds=elapsed,
            )
        except Exception as exc:
            logger.warning("Failed to update game stream history on stop: %s", exc)

    return result


@router.get("/stats/{session_id}")
async def lightrays_stats(session_id: str, current_user: CurrentUser):
    """Proxy container stats from Lightrays."""
    try:
        record = await get_session_record(session_id)
    except Exception as exc:
        logger.warning("Failed to read lightrays session record: %s", exc)
        record = None
    # Fail closed on unknown sessions (see stop endpoint). Superusers exempt.
    if not current_user.is_superuser:
        if record is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if record.get("user_id") != str(current_user.guid):
            raise HTTPException(
                status_code=403, detail="Not authorized for this stream"
            )

    try:
        return await get_stats(
            session_id,
            user_id=str(current_user.guid),
            admin=current_user.is_superuser,
        )
    except Exception as exc:
        logger.warning("Lightrays stats failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="Failed to get session stats"
        ) from exc
