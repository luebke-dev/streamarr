"""Lightrays cloud gaming service — HTTP client for the Lightrays WebRTC server."""

import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from jose import jwt

from pyrate.utils.http import (
    CONNECT_ONLY_EXCEPTIONS,
    host_key,
    request_with_resilience,
)

logger = logging.getLogger(__name__)


def _breaker_key() -> str:
    """Per-host circuit-breaker key for the Lightrays service."""
    return f"lightrays:{host_key(LIGHTRAYS_URL)}"

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

# Audience the Lightrays server validates tokens against (see Rust fix S-M3).
# Minted on every backend-issued token so they pass the upcoming aud check.
LIGHTRAYS_JWT_AUDIENCE = "lightrays"

# A GOW cold start (image pull + container boot) can take well over the
# default 30s. Give ``/api/launch`` a generous *read* timeout so a slow —
# but succeeding — launch doesn't ReadTimeout into a 502 while Lightrays
# quietly finishes building the session (which would leave it orphaned).
# ``launch`` is non-idempotent, so a large timeout is the right lever here
# rather than a retry. ``connect`` stays short so a dead host fails fast.
LIGHTRAYS_LAUNCH_READ_TIMEOUT_SECS = float(
    os.environ.get("LIGHTRAYS_LAUNCH_READ_TIMEOUT_SECS", "180")
)

# One-shot guard so a missing-secret misconfiguration is logged loudly once
# instead of silently sending unauthenticated requests on every call.
_warned_missing_secret = False


def create_lightrays_token(
    user_id: str, expires_minutes: int = 30, scope: str | None = None
) -> str:
    """Create a short-lived JWT for authenticating with Lightrays.

    Returns an empty string when no shared secret is configured (auth
    disabled). In that case a warning is logged once so an accidentally
    unset ``LIGHTRAYS_JWT_SECRET`` — which would make Lightrays reject every
    request — is visible rather than silent.
    """
    global _warned_missing_secret
    if not LIGHTRAYS_JWT_SECRET:
        if not _warned_missing_secret:
            logger.warning(
                "LIGHTRAYS_JWT_SECRET is not set; sending UNAUTHENTICATED "
                "requests to Lightrays. If Lightrays enforces auth every call "
                "will be rejected — set LIGHTRAYS_JWT_SECRET."
            )
            _warned_missing_secret = True
        return ""

    payload = {
        "sub": user_id,
        "aud": LIGHTRAYS_JWT_AUDIENCE,
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
    app_env: dict[str, str] | None = None,
    app_mounts: list[dict] | None = None,
    keyboard_layout: str | None = None,
    mouse_speed: float | None = None,
    media_id: str | None = None,
) -> dict:
    """Launch a streaming session via Lightrays API.

    Returns the raw Lightrays response dict containing at least
    ``session_id`` and ``ws_url``.

    The ``user_id`` is also used as the Lightrays JWT subject so Lightrays can
    bind the session to the authenticated Pyrate user. Capability, device,
    mount, and container-name choices are resolved by Lightrays from a
    server-side ``runtime_profile``. ``docker_image`` is the only optional image
    override and is intended for values already validated by Pyrate.
    ``app_mounts`` carries sanctioned host→container bind mounts (each a
    ``{"host", "container", "ro"}`` dict) resolved from the admin-controlled
    container profile / per-game config; Lightrays enforces the host-path
    allowlist.

    The launch request goes through the shared resilience wrapper (retry +
    backoff on transient connect failures / 5xx, plus a per-host circuit
    breaker). Because ``/api/launch`` is **not** idempotent, retries are
    restricted to connection-level failures where the server cannot have
    processed the request, so a retry never spawns a duplicate session.

    When ``media_id`` is provided, launch and Redis bookkeeping are performed
    atomically: the freshly-launched session is recorded, and if recording
    fails the launch is rolled back (the orphaned Lightrays session is stopped
    and any partial Redis record released) before the error propagates — no
    verwaiste Session is left behind. When ``media_id`` is ``None`` the caller
    is responsible for bookkeeping (see :func:`record_session`) and behaviour
    is unchanged.
    """
    if not user_id:
        user_id = "pyrate-backend"

    # Fail closed on the security-sensitive launch shape. A launch carrying an
    # admin-vetted ``docker_image`` / ``app_mounts`` proves that vetting to
    # Lightrays via the ``lightrays:image`` scope in a *signed* token. With no
    # ``LIGHTRAYS_JWT_SECRET`` the request would go out UNAUTHENTICATED and that
    # scope claim would be meaningless — anything that can reach the Lightrays
    # host could then drive container image/mount selection. Refuse rather than
    # send an unauthenticated image/mount-bearing request. (A default-profile
    # launch without image/mounts still works in local dev without a secret.)
    if (docker_image or app_mounts) and not LIGHTRAYS_JWT_SECRET:
        raise RuntimeError(
            "Refusing to launch a container with a custom docker_image/app_mounts "
            "while LIGHTRAYS_JWT_SECRET is unset: the request would be "
            "unauthenticated and the lightrays:image scope meaningless. "
            "Set LIGHTRAYS_JWT_SECRET."
        )

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
    # Merged profile + per-game container env (admin-controlled). Sent as the
    # new ``app_env`` field only when non-empty; the deprecated raw ``env``
    # field is intentionally not used. System-level env is set by Lightrays.
    if app_env:
        payload["app_env"] = app_env
    # Sanctioned per-game/profile host→container bind mounts (e.g. a Wine game
    # folder), resolved from the container profile + extra_data.lightrays.mounts.
    # Sent as the new ``app_mounts`` field only when non-empty; the deprecated
    # raw ``mounts`` field is intentionally not used. Each entry is a
    # ``{"host": str, "container": str, "ro": bool}`` dict. Like ``docker_image``
    # these are admin-mediated (profiles/extra_data are admin/superuser-set), so
    # they ride the same ``lightrays:image`` scope; Lightrays enforces the
    # authoritative host-path allowlist.
    if app_mounts:
        payload["app_mounts"] = app_mounts
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
    launch_timeout = httpx.Timeout(
        connect=10.0,
        read=LIGHTRAYS_LAUNCH_READ_TIMEOUT_SECS,
        write=10.0,
        pool=10.0,
    )
    async with httpx.AsyncClient(timeout=launch_timeout) as client:
        resp = await request_with_resilience(
            lambda: client.post(
                f"{LIGHTRAYS_URL}/api/launch",
                json=payload,
                # `lightrays:image` marks the backend as having vetted the
                # container image server-side (it always comes from an
                # admin-managed container profile or a superuser-set per-game
                # override, never from the end user), which the Lightrays S-C1
                # gate requires for any `docker_image`.
                headers=_auth_headers(user_id, scope="lightrays:image"),
            ),
            breaker_key=_breaker_key(),
            # Non-idempotent POST: only retry when the request provably never
            # reached the server, so we never launch a duplicate session.
            retry_exceptions=CONNECT_ONLY_EXCEPTIONS,
            # ...and never replay a 5xx response either: the server may have
            # already spawned the session, so a retry could duplicate it.
            retry_on_server_error=False,
        )
        resp.raise_for_status()
        data = resp.json()
        ws_url = data.get("ws_url") or f"/api/lightrays-ws/{data.get('session_id', '')}"
        data["websocket_url"] = _browser_websocket_url(ws_url)
        logger.info("Lightrays session launched session_id=%s", data.get("session_id"))

    # Optional atomic bookkeeping: record the session and roll back the launch
    # if recording fails, so a Lightrays-side session is never left orphaned.
    if media_id is not None:
        session_id = data.get("session_id")
        try:
            await record_session(
                user_id=user_id, session_id=session_id, media_id=media_id
            )
        except Exception as exc:
            logger.error(
                "Lightrays bookkeeping failed for session_id=%s; rolling back: %s",
                session_id,
                exc,
            )
            await _rollback_launch(session_id, user_id=user_id)
            raise

    return data


async def _rollback_launch(session_id: str | None, *, user_id: str) -> None:
    """Best-effort cleanup of a launched-but-unrecorded Lightrays session.

    Releases any partial Redis bookkeeping and asks Lightrays to tear down the
    container so a failed bookkeeping step doesn't leave a verwaiste Session.
    Both steps are best-effort — rollback must never mask the original error.
    """
    if not session_id:
        return
    try:
        await release_session(session_id)
    except Exception:
        logger.warning(
            "rollback: failed to release redis record for session_id=%s",
            session_id,
            exc_info=True,
        )
    try:
        await stop_session(session_id, user_id=user_id)
    except Exception:
        logger.warning(
            "rollback: failed to stop orphaned lightrays session_id=%s",
            session_id,
            exc_info=True,
        )


async def stop_session(session_id: str, *, user_id: str, admin: bool = False) -> dict:
    """Stop an active Lightrays streaming session."""
    logger.info("Stopping Lightrays session session_id=%s", session_id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await request_with_resilience(
            lambda: client.post(
                f"{LIGHTRAYS_URL}/api/stop",
                json={"session_id": session_id},
                headers=_auth_headers(
                    user_id, scope="lightrays:admin" if admin else None
                ),
            ),
            breaker_key=_breaker_key(),
        )
        resp.raise_for_status()
        logger.info("Lightrays session stopped session_id=%s", session_id)
        return resp.json()


async def get_stats(session_id: str, *, user_id: str, admin: bool = False) -> dict:
    """Get container stats for an active Lightrays session."""
    logger.debug("Fetching Lightrays stats for session_id=%s", session_id)
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await request_with_resilience(
            lambda: client.get(
                f"{LIGHTRAYS_URL}/api/stats/{session_id}",
                headers=_auth_headers(
                    user_id, scope="lightrays:admin" if admin else None
                ),
            ),
            breaker_key=_breaker_key(),
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


# Atomic reserve-a-slot: prune stale entries, and only if the user is still
# below the cap, add a short-lived reservation placeholder to the active-set
# and return the (post-prune, pre-reserve) count. Returns -1 when the cap is
# already reached. Doing the prune+check+add in a single Lua script closes the
# TOCTOU window between counting and launching two concurrent sessions.
_RESERVE_SLOT_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1])
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[2]) then
    return -1
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return count
"""


async def reserve_session_slot(user_id: str, max_streams: int) -> str | None:
    """Atomically reserve a concurrency slot for a new session.

    Returns a reservation token that counts toward ``max_game_streams`` until
    it is either superseded by the real :func:`record_session` entry or freed
    with :func:`release_session_slot`. Returns ``None`` when the user is
    already at the cap, so the caller can reject the launch before starting a
    Lightrays session. This closes the count→check→launch TOCTOU gap.
    """
    from pyrate.services.rate_limiter import _get_redis

    r = await _get_redis()
    now = time.time()
    token = f"reserve:{uuid.uuid4().hex}"
    result = await r.eval(
        _RESERVE_SLOT_LUA,
        1,
        _user_set_key(user_id),
        now - LIGHTRAYS_SESSION_MAX_SECONDS,
        max_streams,
        now,
        token,
        LIGHTRAYS_SESSION_MAX_SECONDS + 60,
    )
    if int(result) < 0:
        return None
    return token


async def release_session_slot(user_id: str, token: str) -> None:
    """Free a reservation placeholder created by :func:`reserve_session_slot`."""
    if not token:
        return
    from pyrate.services.rate_limiter import _get_redis

    r = await _get_redis()
    await r.zrem(_user_set_key(user_id), token)


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
