"""Lightrays cloud-gaming API — launch / stop / stats for game streaming sessions."""

import logging
import os
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pyrate.api.dependencies import CurrentUser, DatabaseSession, UserPermissionsDep
from pyrate.models.media import MediaType
from pyrate.services.container_profiles import (
    available_platforms,
    compute_app_id,
    resolve_launch_config,
)
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
from pyrate.services.steam_import import import_steam_games
from pyrate.services.steam_library import read_steam_library
from pyrate.services.viewing_history import ViewingHistoryService

logger = logging.getLogger(__name__)

router = APIRouter()

# Root of the Lightrays persistent-state dir, mounted (read-only) into the
# backend by the compose stack. Lightrays lays out per-app state under
# ``{LIGHTRAYS_STATE_DIR}/apps_state/<app_id>`` and mounts each as the
# container's ``/home/retro``. The user-scoped ``steam`` profile shares one
# app_id per user (``<user_guid>-steam``; see
# :func:`container_profiles.compute_app_id`), so that dir holds the user's
# single Steam install + login we read the library from. Override with the
# ``LIGHTRAYS_STATE_DIR`` env var; the default mirrors the compose value.
LIGHTRAYS_STATE_DIR = os.environ.get("LIGHTRAYS_STATE_DIR", "/state/lightrays")


def _user_steam_state_dir(user_guid: str) -> str:
    """Resolve the on-disk Steam persistent-state dir for a user.

    Mirrors the ``<user_guid>-steam`` app_id the user-scoped steam profile
    launches with, so the import reads exactly the state a launched Steam
    session persisted.
    """
    return os.path.join(LIGHTRAYS_STATE_DIR, "apps_state", f"{user_guid}-steam")


def _steam_dir_exists(path: str) -> bool:
    """Whether the resolved Steam state dir exists (isolated for testability)."""
    return os.path.isdir(path)


# ── Request / Response schemas ──────────────────────────────────────────────


class LaunchRequest(BaseModel):
    width: int = Field(default=1920, ge=64, le=7680)
    height: int = Field(default=1080, ge=64, le=4320)
    fps: int = Field(default=60, ge=15, le=120)
    bitrate_kbps: int = Field(default=10000, ge=500, le=50000)
    # Player-chosen platform slug (n64/snes/pc/…). Decides the runtime + which
    # per-platform file is launched. None = auto-derive from the game.
    platform: str | None = Field(default=None, max_length=32)


class GamePlatform(BaseModel):
    platform: str
    label: str
    runtime: str
    downloaded: bool
    release_available: bool


class LaunchResponse(BaseModel):
    session_id: str
    websocket_url: str
    ws_ticket: str = ""
    ice_servers: list[dict[str, Any]] = []


class StopRequest(BaseModel):
    session_id: str


class SteamImportResponse(BaseModel):
    created: int
    updated: int
    skipped: int
    read: int
    items: list[str] = []


class SteamStatusResponse(BaseModel):
    linked: bool
    games: int


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


# D-pad mode → RetroArch input_playerN_analog_dpad_mode value.
_DPAD_MODE_TO_RETROARCH = {"dpad": "0", "left_analog": "1", "right_analog": "2"}


def _controller_env(gaming_prefs: dict[str, Any]) -> dict[str, str]:
    """Translate a user's controller prefs into RETRO_* container env.

    Only well-formed values are emitted; the retro container turns these into a
    RetroArch input override (deadzone + D-pad mode). Non-retro images ignore
    them. Returns an empty dict when nothing is configured.
    """
    env: dict[str, str] = {}
    deadzone = gaming_prefs.get("analog_deadzone")
    if deadzone is not None:
        try:
            dz = float(deadzone)
        except (TypeError, ValueError):
            dz = None
        if dz is not None and 0.0 <= dz <= 0.5:
            env["RETRO_ANALOG_DEADZONE"] = f"{dz:.2f}"
    dpad = gaming_prefs.get("dpad_mode")
    if dpad in _DPAD_MODE_TO_RETROARCH:
        env["RETRO_DPAD_MODE"] = _DPAD_MODE_TO_RETROARCH[dpad]
    return env


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
    launch_config = await resolve_launch_config(db, media_item, body.platform)
    docker_image = _validate_lightrays_docker_image(launch_config.get("docker_image"))
    runtime_profile = launch_config.get("runtime_profile")
    app_env = launch_config.get("app_env") or None

    # A retro game with no ROM for the chosen platform can't launch — the ROM
    # isn't downloaded yet. Kick off the acquisition and tell the player to
    # retry, instead of booting an empty emulator.
    if launch_config.get("profile_name") == "retro" and not (app_env or {}).get(
        "RETRO_ROM"
    ):
        # Acquire a release for the chosen platform specifically (so a
        # multi-platform title grabs the N64 ROM, not the 3DS remake / PC port).
        dl_platform = body.platform
        if not dl_platform:
            retro = [
                p["platform"]
                for p in await available_platforms(db, media_item)
                if p["runtime"] == "retro"
            ]
            dl_platform = retro[0] if retro else None
        try:
            from pyrate.worker import auto_download_media_item

            await auto_download_media_item.kiq(
                str(media_item.guid),
                None,
                str(current_user.guid),
                platform=dl_platform,
            )
        except Exception as exc:
            logger.warning("Failed to enqueue game download for %s: %s", media_id, exc)
        raise HTTPException(
            status_code=409,
            detail="Game is being downloaded — try Play again shortly.",
        )
    # Per-user controller settings (retro container reads RETRO_* to build a
    # RetroArch input override). Harmless to non-retro images, which ignore them.
    controller_env = _controller_env(gaming_prefs)
    if controller_env:
        app_env = {**(app_env or {}), **controller_env}
    # Sanctioned host→container bind mounts merged from the container profile +
    # per-game config. Already normalised/validated to {host,container,ro} by
    # resolve_launch_config; Lightrays enforces the host-path allowlist.
    app_mounts = launch_config.get("app_mounts") or None

    # Derive the persistent-state key (mounted as /home/retro). A "user"-scoped
    # profile (e.g. steam) shares ONE state per user across all of that user's
    # games — a single Steam login + one shared library — while a "game"-scoped
    # profile keeps the legacy per-user-per-game isolation.
    app_id = compute_app_id(
        user_guid=str(current_user.guid),
        game_guid=str(media_item.guid),
        state_scope=launch_config.get("state_scope") or "game",
        profile_name=launch_config.get("profile_name"),
    )

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
            # Per-profile state scope (see compute_app_id above): user-scoped
            # profiles share one /home/retro per user (single Steam login +
            # shared library); game-scoped profiles stay per-user-per-game.
            # Concurrent launches from different users never collide either way.
            app_id=app_id,
            docker_image=docker_image,
            runtime_profile=runtime_profile,
            app_env=app_env,
            app_mounts=app_mounts,
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


@router.get("/platforms/{media_id}", response_model=list[GamePlatform])
async def lightrays_platforms(
    media_id: UUID, db: DatabaseSession, current_user: CurrentUser
):
    """List the platforms a game can be played on (for the player's picker).

    Each entry says whether that platform is already downloaded and whether a
    release is available to acquire, so the UI can offer "Play" vs "Download".
    """
    media_service = MediaService(db)
    media_item = await media_service.get_by_id(media_id)
    if not media_item or media_item.media_type != MediaType.GAMES:
        raise HTTPException(status_code=404, detail="Game not found")
    plats = await available_platforms(db, media_item)
    return [GamePlatform(**p) for p in plats]


# ── Steam library link / import ──────────────────────────────────────────────


@router.post("/steam/import", response_model=SteamImportResponse)
async def lightrays_steam_import(
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Import the current user's Steam library into GAMES media items.

    Reads the on-disk Steam state a launched Steam session persisted (the
    user-scoped ``<user_guid>-steam`` app dir mounted read-only from the
    Lightrays state dir), then upserts each owned/installed app as a game.

    Scoped to the authenticated user's own Steam state — a superuser importing
    their own library is fine, but there is no cross-user import path. Degrades
    gracefully: a missing dir, an empty library or a read/parse error surfaces
    as a clear 4xx (never a 500) so the UI can prompt the user to launch and
    log into Steam first.
    """
    steam_dir = _user_steam_state_dir(str(current_user.guid))
    if not _steam_dir_exists(steam_dir):
        raise HTTPException(
            status_code=409,
            detail="No Steam data found — launch and log into Steam first.",
        )

    try:
        games = read_steam_library(steam_dir)
    except Exception as exc:  # noqa: BLE001 — defensive: never surface a 500
        logger.warning(
            "Failed to read Steam library for user %s: %s", current_user.guid, exc
        )
        raise HTTPException(
            status_code=400,
            detail="Could not read Steam library — the data may be incomplete "
            "or corrupt.",
        ) from exc

    if not games:
        raise HTTPException(
            status_code=409,
            detail="No Steam games found — launch and log into Steam first.",
        )

    result = await import_steam_games(db, games)
    return SteamImportResponse(
        created=int(result.get("created", 0)),
        updated=int(result.get("updated", 0)),
        skipped=int(result.get("skipped", 0)),
        read=len(games),
        items=list(result.get("items", [])),
    )


@router.get("/steam/status", response_model=SteamStatusResponse)
async def lightrays_steam_status(current_user: CurrentUser):
    """Report whether the user's Steam state is linked and how many games read.

    Lets the UI show a "linked / N games" indicator without mutating anything.
    Never raises on a missing dir or a read error — reports ``linked=False`` /
    ``games=0`` instead.
    """
    steam_dir = _user_steam_state_dir(str(current_user.guid))
    if not _steam_dir_exists(steam_dir):
        return SteamStatusResponse(linked=False, games=0)
    try:
        games = read_steam_library(steam_dir)
    except Exception as exc:  # noqa: BLE001 — status must never 500
        logger.warning(
            "Failed to read Steam library for user %s: %s", current_user.guid, exc
        )
        return SteamStatusResponse(linked=True, games=0)
    return SteamStatusResponse(linked=True, games=len(games))
