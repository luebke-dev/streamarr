"""Lightrays cloud gaming service — HTTP client for the Lightrays WebRTC server."""

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from jose import jwt

logger = logging.getLogger(__name__)

# Sessions older than this are considered abandoned (e.g. backend crashed
# before it could record the stop). Used to garbage-collect stale entries
# from the per-user active-session set on read.
#
# Reads from ``LIGHTRAYS_SESSION_TIMEOUT_SECS`` so Pyrate's bookkeeping
# ages out on the same schedule as the Lightrays-side idle reaper. A
# small ``GRACE`` is added so Pyrate doesn't prune a session that the
# Lightrays reaper is still finalising. Falls back to one hour (the
# Lightrays default) when the env var is missing.
_LIGHTRAYS_TTL_GRACE_SECS = 60


def _load_session_max_seconds() -> int:
    raw = os.environ.get("LIGHTRAYS_SESSION_TIMEOUT_SECS")
    if raw is None:
        return 3600 + _LIGHTRAYS_TTL_GRACE_SECS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid LIGHTRAYS_SESSION_TIMEOUT_SECS=%r; falling back to 3600", raw
        )
        return 3600 + _LIGHTRAYS_TTL_GRACE_SECS
    return max(value, 0) + _LIGHTRAYS_TTL_GRACE_SECS


LIGHTRAYS_SESSION_MAX_SECONDS = _load_session_max_seconds()

LIGHTRAYS_URL = os.environ.get("LIGHTRAYS_URL", "http://lightrays:8080")
LIGHTRAYS_PUBLIC_URL = os.environ.get("LIGHTRAYS_PUBLIC_URL", "")
LIGHTRAYS_DEFAULT_RUNTIME_PROFILE = os.environ.get(
    "LIGHTRAYS_DEFAULT_RUNTIME_PROFILE", "gow-steam"
)
LIGHTRAYS_JWT_SECRET = os.environ.get("LIGHTRAYS_JWT_SECRET", "")


def create_lightrays_token(
    user_id: str, expires_minutes: int = 30, scope: str | None = None
) -> str:
    """Create a short-lived JWT for authenticating with Lightrays.

    Returns an empty string when no shared secret is configured (auth disabled).
    """
    if not LIGHTRAYS_JWT_SECRET:
        return ""

    payload = {
        "sub": user_id,
        "exp": datetime.now(UTC) + timedelta(minutes=expires_minutes),
        "iat": datetime.now(UTC),
    }
    if scope:
        payload["scope"] = scope
    return jwt.encode(payload, LIGHTRAYS_JWT_SECRET, algorithm="HS256")


def _auth_headers(user_id: str, *, scope: str | None = None) -> dict[str, str]:
    """Return Authorization header for backend→Lightrays API calls."""
    if not LIGHTRAYS_JWT_SECRET:
        return {}
    token = create_lightrays_token(user_id, expires_minutes=5, scope=scope)
    return {"Authorization": f"Bearer {token}"}


async def launch_session(
    *,
    title: str = "Steam (GOW)",
    width: int = 1920,
    height: int = 1080,
    fps: int = 60,
    bitrate_kbps: int = 10000,
    user_id: str | None = None,
    app_id: str | None = None,
    runtime_profile: str | None = None,
    docker_image: str | None = None,
    keyboard_layout: str | None = None,
    mouse_speed: float | None = None,
) -> dict:
    """Launch a streaming session via Lightrays API.

    Returns the raw Lightrays response dict containing at least
    ``session_id`` and ``ws_url``.

    The ``user_id`` is also used as the Lightrays JWT subject so Lightrays can
    bind the session to the authenticated Pyrate user. Capability, device,
    mount, and container-name choices are resolved by Lightrays from a
    server-side ``runtime_profile``. ``docker_image`` is the only optional image
    override and is intended for values already validated by Pyrate.
    """
    if not user_id:
        user_id = "pyrate-backend"

    # Per-user persistent storage: Lightrays derives `apps_state/<app_id>`
    # from the `app_id` field we pass below, and handles both the local
    # mkdir and the bind mount at `/home/retro`. No mount injection needed.

    payload = {
        "title": title,
        "width": width,
        "height": height,
        "fps": fps,
        "bitrate_kbps": bitrate_kbps,
        "runtime_profile": runtime_profile or LIGHTRAYS_DEFAULT_RUNTIME_PROFILE,
        "start_virtual_compositor": True,
        "start_audio_server": True,
    }
    # Per-app state identifier. Defaults to `{user_id}-default` when
    # `app_id` wasn't supplied so each user still gets an isolated
    # `/home/retro` regardless of which game they launch. Callers that want
    # per-game isolation (e.g. separate saves per game) pass an explicit
    # `<user_id>-<game_guid>` style id.
    effective_app_id = app_id or (f"{user_id}-default" if user_id else None)
    if effective_app_id:
        payload["app_id"] = effective_app_id
    if docker_image:
        payload["docker_image"] = docker_image
    if keyboard_layout:
        payload["keyboard_layout"] = keyboard_layout
    if mouse_speed is not None:
        payload["mouse_speed"] = mouse_speed

    logger.info(
        "Launching Lightrays session title=%r profile=%s image=%s resolution=%dx%d",
        title,
        payload["runtime_profile"],
        docker_image or "<default>",
        width,
        height,
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{LIGHTRAYS_URL}/api/launch", json=payload, headers=_auth_headers(user_id)
        )
        resp.raise_for_status()
        data = resp.json()
        ws_url = data.get("ws_url") or f"/api/lightrays-ws/{data.get('session_id', '')}"
        data["websocket_url"] = _browser_websocket_url(ws_url)
        logger.info("Lightrays session launched session_id=%s", data.get("session_id"))
        return data


async def stop_session(session_id: str, *, user_id: str, admin: bool = False) -> dict:
    """Stop an active Lightrays streaming session."""
    logger.info("Stopping Lightrays session session_id=%s", session_id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{LIGHTRAYS_URL}/api/stop",
            json={"session_id": session_id},
            headers=_auth_headers(user_id, scope="lightrays:admin" if admin else None),
        )
        resp.raise_for_status()
        logger.info("Lightrays session stopped session_id=%s", session_id)
        return resp.json()


async def get_stats(session_id: str, *, user_id: str, admin: bool = False) -> dict:
    """Get container stats for an active Lightrays session."""
    logger.debug("Fetching Lightrays stats for session_id=%s", session_id)
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            f"{LIGHTRAYS_URL}/api/stats/{session_id}",
            headers=_auth_headers(user_id, scope="lightrays:admin" if admin else None),
        )
        resp.raise_for_status()
        return resp.json()


# ── Active-session bookkeeping (Redis) ─────────────────────────────────────
#
# Lightrays itself keeps no per-user state, so the backend tracks active
# sessions to enforce ``permissions.max_game_streams`` and to feed the
# game stream into the user's viewing history.
#
# Layout:
#   pyrate:lightrays:user:{user_id}        (sorted set; score = started_ts,
#                                            member = session_id)
#   pyrate:lightrays:session:{session_id}  (hash; user_id, media_id,
#                                            started_ts) — TTL refreshed
#                                            on writes


def _user_set_key(user_id: str) -> str:
    return f"pyrate:lightrays:user:{user_id}"


def _session_key(session_id: str) -> str:
    return f"pyrate:lightrays:session:{session_id}"


async def count_active_sessions(user_id: str) -> int:
    """Return the number of active lightrays sessions for ``user_id``.

    Stale entries (older than ``LIGHTRAYS_SESSION_MAX_SECONDS``) are pruned
    on read so a crashed backend doesn't cause counters to drift forever.
    """
    from pyrate.services.rate_limiter import _get_redis

    r = await _get_redis()
    key = _user_set_key(user_id)
    cutoff = time.time() - LIGHTRAYS_SESSION_MAX_SECONDS
    await r.zremrangebyscore(key, 0, cutoff)
    return await r.zcard(key)


async def record_session(*, user_id: str, session_id: str, media_id: str) -> float:
    """Record a freshly-launched lightrays session for ``user_id``.

    Returns the start timestamp (epoch seconds) so callers can correlate
    it with viewing-history updates.
    """
    from pyrate.services.rate_limiter import _get_redis

    r = await _get_redis()
    started_at = time.time()
    user_key = _user_set_key(user_id)
    sess_key = _session_key(session_id)

    pipe = r.pipeline()
    pipe.zadd(user_key, {session_id: started_at})
    pipe.expire(user_key, LIGHTRAYS_SESSION_MAX_SECONDS + 60)
    pipe.hset(
        sess_key,
        mapping={
            "user_id": user_id,
            "media_id": media_id,
            "started_at": str(started_at),
        },
    )
    pipe.expire(sess_key, LIGHTRAYS_SESSION_MAX_SECONDS + 60)
    await pipe.execute()
    return started_at


async def release_session(session_id: str) -> dict | None:
    """Remove tracking entries for a stopped session.

    Returns the recorded session metadata (``user_id``, ``media_id``,
    ``started_at``) or ``None`` if no record exists — callers use this
    to update viewing history after the stream ends.
    """
    from pyrate.services.rate_limiter import _get_redis

    r = await _get_redis()
    sess_key = _session_key(session_id)
    data = await r.hgetall(sess_key)
    if not data:
        return None

    user_id = data.get("user_id")
    pipe = r.pipeline()
    if user_id:
        pipe.zrem(_user_set_key(user_id), session_id)
    pipe.delete(sess_key)
    await pipe.execute()

    try:
        started_at = float(data.get("started_at", "0"))
    except ValueError:
        started_at = 0.0
    return {
        "user_id": user_id,
        "media_id": data.get("media_id"),
        "started_at": started_at,
    }


async def get_session_record(session_id: str) -> dict | None:
    """Return Pyrate's Redis metadata for a Lightrays session."""
    from pyrate.services.rate_limiter import _get_redis

    r = await _get_redis()
    data = await r.hgetall(_session_key(session_id))
    return data or None


def _browser_websocket_url(ws_url: str) -> str:
    """Return a browser-usable WebSocket URL or same-origin relative path."""
    if not ws_url:
        return ""
    if ws_url.startswith("ws://") or ws_url.startswith("wss://"):
        return ws_url
    if not LIGHTRAYS_PUBLIC_URL:
        return ws_url

    absolute = urljoin(LIGHTRAYS_PUBLIC_URL.rstrip("/") + "/", ws_url.lstrip("/"))
    parsed = urlparse(absolute)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse(parsed._replace(scheme=scheme))
