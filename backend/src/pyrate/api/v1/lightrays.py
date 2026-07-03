"""Lightrays cloud-gaming API — launch / stop / stats for game streaming sessions."""

import json
import logging
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pyrate.api.dependencies import CurrentUser, DatabaseSession, UserPermissionsDep
from pyrate.models.media import MediaType
from pyrate.services.lightrays import (
    count_active_sessions,
    get_session_record,
    get_stats,
    launch_session,
    record_session,
    release_session,
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


def _load_media_extra_data(media_item: Any) -> dict[str, Any]:
    raw = getattr(media_item, "extra_data", None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


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


def _game_lightrays_docker_image(media_item: Any) -> str | None:
    extra_data = _load_media_extra_data(media_item)
    lightrays_data = extra_data.get("lightrays")
    if isinstance(lightrays_data, dict):
        return _validate_lightrays_docker_image(lightrays_data.get("docker_image"))
    return _validate_lightrays_docker_image(extra_data.get("lightrays_docker_image"))


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
    # many sessions are already running.
    max_game_streams = permissions.max_game_streams if permissions else 0
    if max_game_streams <= 0:
        raise HTTPException(
            status_code=403,
            detail="Game streaming is not allowed for your account.",
        )
    active = await count_active_sessions(str(current_user.guid))
    if active >= max_game_streams:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum concurrent game streams reached ({max_game_streams}). Stop another session first.",
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

    docker_image = _game_lightrays_docker_image(media_item)
    try:
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
            keyboard_layout=keyboard_layout,
            mouse_speed=mouse_speed,
        )
    except Exception as exc:
        logger.error("Lightrays launch failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Failed to start game streaming session — is Lightrays running?",
        ) from exc

    session_id = data["session_id"]

    # Track the active session so the limit check above can see it, and so
    # the stop endpoint can later attribute the stream back to this user.
    try:
        await record_session(
            user_id=str(current_user.guid),
            session_id=session_id,
            media_id=str(media_item.guid),
        )
    except Exception as exc:
        # Limit-tracking is best-effort — never let Redis hiccups block a
        # successful launch. The stale entry (if any) will time out.
        logger.warning("Failed to record lightrays session in redis: %s", exc)

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
    if (
        record
        and record.get("user_id") != str(current_user.guid)
        and not current_user.is_superuser
    ):
        raise HTTPException(status_code=403, detail="Not authorized for this stream")

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
    if (
        record
        and record.get("user_id") != str(current_user.guid)
        and not current_user.is_superuser
    ):
        raise HTTPException(status_code=403, detail="Not authorized for this stream")

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
