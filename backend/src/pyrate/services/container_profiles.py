"""Container-profile service — global CRUD plus launch-config resolution.

Container profiles describe how a "game" (a generic container) is launched
by Lightrays: the Docker image, the server-side ``runtime_profile`` Lightrays
resolves, and a shared, admin-controlled container environment (``env``).

Profiles are global (not per-user). Individual games reference a profile by
name or guid via ``extra_data.lightrays.profile`` and may override the image
(``extra_data.lightrays.docker_image``) or extend the env
(``extra_data.lightrays.env``) per-game.

The default profile is named ``steam`` (seeded as a builtin), so a game that
references no profile launches with the same image and behaviour as before.
"""

import json
import logging
import os
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.container_profile import ContainerProfile
from pyrate.models.media import MediaFile

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_NAME = "steam"


# ── CRUD ────────────────────────────────────────────────────────────────────


async def list_profiles(db: AsyncSession) -> list[ContainerProfile]:
    """Return all container profiles ordered by name."""
    result = await db.execute(
        select(ContainerProfile).order_by(ContainerProfile.name)
    )
    return list(result.scalars().all())


async def get_by_guid(
    db: AsyncSession, guid: str | uuid.UUID
) -> ContainerProfile | None:
    """Return a profile by its guid, or ``None``."""
    if isinstance(guid, str):
        try:
            guid = uuid.UUID(guid)
        except (ValueError, AttributeError):
            return None
    result = await db.execute(
        select(ContainerProfile).where(ContainerProfile.guid == guid)
    )
    return result.scalar_one_or_none()


async def get_by_name(db: AsyncSession, name: str) -> ContainerProfile | None:
    """Return a profile by its unique name, or ``None``."""
    result = await db.execute(
        select(ContainerProfile).where(ContainerProfile.name == name)
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    name: str,
    kind: str,
    docker_image: str,
    runtime_profile: str = "gow-app",
    env: dict[str, str] | None = None,
    is_builtin: bool = False,
    state_scope: str = "game",
) -> ContainerProfile:
    """Create and persist a new container profile."""
    profile = ContainerProfile(
        name=name,
        kind=kind,
        docker_image=docker_image,
        runtime_profile=runtime_profile,
        env=env or {},
        is_builtin=is_builtin,
        state_scope=state_scope,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def update(
    db: AsyncSession, profile: ContainerProfile, **fields: Any
) -> ContainerProfile:
    """Update mutable fields of a profile and persist.

    Only the recognised, mutable attributes are applied; ``guid``,
    ``is_builtin`` and timestamps are ignored.
    """
    mutable = {
        "name",
        "kind",
        "docker_image",
        "runtime_profile",
        "env",
        "state_scope",
    }
    for key, value in fields.items():
        if key in mutable:
            setattr(profile, key, value)
    await db.commit()
    await db.refresh(profile)
    return profile


async def delete(db: AsyncSession, profile: ContainerProfile) -> None:
    """Delete a profile. Builtin profiles cannot be deleted."""
    if profile.is_builtin:
        raise ValueError("Builtin container profiles cannot be deleted")
    await db.delete(profile)
    await db.commit()


# ── Launch-config resolution ─────────────────────────────────────────────────


def _load_lightrays_extra(media_item: Any) -> dict[str, Any]:
    """Return the ``extra_data.lightrays`` dict for a media item (or ``{}``)."""
    raw = getattr(media_item, "extra_data", None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}
    lightrays = raw.get("lightrays")
    return lightrays if isinstance(lightrays, dict) else {}


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_env(value: Any) -> dict[str, str]:
    """Coerce a raw env mapping into a ``str→str`` dict, dropping bad entries."""
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if k is not None}


def _clean_mounts(value: Any) -> list[dict[str, Any]]:
    """Normalise a raw mounts list into validated ``{host,container,ro}`` dicts.

    Each entry must be a dict carrying an absolute host path and an absolute
    container target path. The canonical keys are ``host`` / ``container`` /
    ``ro``; the tolerant aliases ``source`` / ``target`` / ``read_only`` are
    accepted too. ``ro`` defaults to ``False``.

    Entries that aren't dicts, or whose host/container is missing, empty, or not
    an absolute path, are dropped **silently** — Pyrate validates only the
    *shape* of a mount here. The authoritative host-path allowlist (which host
    directories may actually be exposed) is enforced by Lightrays, not here.
    """
    if not isinstance(value, list):
        return []
    mounts: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        host = _clean_str(entry.get("host") if "host" in entry else entry.get("source"))
        container = _clean_str(
            entry.get("container") if "container" in entry else entry.get("target")
        )
        if not host or not container:
            continue
        if not (os.path.isabs(host) and os.path.isabs(container)):
            continue
        if "ro" in entry:
            ro = bool(entry["ro"])
        elif "read_only" in entry:
            ro = bool(entry["read_only"])
        else:
            ro = False
        mounts.append({"host": host, "container": container, "ro": ro})
    return mounts


APP_REF_PLACEHOLDER = "{app_ref}"


def _apply_app_ref(env: dict[str, str], app_ref: str | None) -> dict[str, str]:
    """Fill the per-game ``{app_ref}`` placeholder in profile/game env values.

    A profile carries its launch template ONCE (e.g.
    ``STEAM_STARTUP_FLAGS="-bigpicture steam://rungameid/{app_ref}"``) so every
    game shares the same env and only supplies its own ``app_ref`` (the Steam
    app id, a ROM path, …). Values whose placeholder can't be filled — no
    ``app_ref`` given — are dropped rather than left as a broken literal, so a
    profile game without a target falls back to the container's default
    behaviour (e.g. Steam Big Picture) instead of a malformed launch command.
    """
    result: dict[str, str] = {}
    for key, val in env.items():
        if APP_REF_PLACEHOLDER in val:
            if app_ref:
                result[key] = val.replace(APP_REF_PLACEHOLDER, app_ref)
            # else: drop this key — nothing to launch
        else:
            result[key] = val
    return result


# ── ROM launch derivation (libretro / retro profile) ─────────────────────────
#
# A retro game's ROM is a plain MediaFile in the games library — there is no
# importer stamping mounts/app_ref. At launch we derive both from the file:
# the ROM is a backend-container path under the games library (e.g.
# ``/library/games/snes/Chrono.sfc``); we rebase it to the real HOST path so
# the Docker daemon can bind-mount it into the sibling game container, mount the
# ROM's *directory* (so ``.cue``/``.bin`` and multi-disc siblings come along)
# read-only at ``/rom``, and set ``app_ref`` to the ROM's in-container path.

# Where the ROM directory is bind-mounted inside the retro container.
RETRO_ROM_CONTAINER_DIR = "/rom"

# The games-library path as the BACKEND sees it (the plugin default).
GAMES_LIBRARY_CONTAINER = os.environ.get(
    "LIGHTRAYS_GAMES_LIBRARY_CONTAINER", "/library/games"
).rstrip("/")


def _games_library_host_root() -> str:
    """Host-side path of the games library (what the Docker daemon resolves).

    Prefers an explicit ``LIGHTRAYS_GAMES_LIBRARY_HOST``; otherwise derives it
    from ``PROJECT_ROOT`` exactly like :func:`computing._data_root` — the games
    library lives at ``{PROJECT_ROOT}/data/library/games`` alongside the other
    media libraries.
    """
    explicit = os.environ.get("LIGHTRAYS_GAMES_LIBRARY_HOST", "").strip()
    if explicit:
        return explicit.rstrip("/")
    project_root = os.environ.get("PROJECT_ROOT", "/root/pyrate.media").rstrip("/")
    return f"{project_root}/data/library/games"


def _translate_library_path_to_host(file_path: str) -> str | None:
    """Rebase a backend games-library path onto the real host path.

    ``/library/games/snes/Chrono.sfc`` → ``{host_root}/snes/Chrono.sfc``.
    Returns ``None`` if ``file_path`` is not under the games-library root, so a
    stray absolute path is never blindly exposed as a bind mount.
    """
    root = GAMES_LIBRARY_CONTAINER
    p = os.path.normpath(file_path)
    if p != root and not p.startswith(root + "/"):
        return None
    return os.path.normpath(
        os.path.join(_games_library_host_root(), os.path.relpath(p, root))
    )


async def _derive_rom_launch(
    db: AsyncSession, media_item: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """Derive ``(rom_mount, app_ref)`` from a game's primary ROM MediaFile.

    Returns ``(None, None)`` when the item has no readable ROM file under the
    games library, so the caller falls back to no ROM (the container then
    reports a missing ``RETRO_ROM`` rather than launching something wrong).
    """
    guid = getattr(media_item, "guid", None)
    if guid is None:
        return None, None
    result = await db.execute(
        select(MediaFile).where(MediaFile.media_item_guid == guid).limit(1)
    )
    media_file = result.scalars().first()
    file_path = _clean_str(getattr(media_file, "file_path", None)) if media_file else None
    if not file_path:
        return None, None
    host_path = _translate_library_path_to_host(file_path)
    if not host_path:
        return None, None
    mount = {
        "host": os.path.dirname(host_path),
        "container": RETRO_ROM_CONTAINER_DIR,
        "ro": True,
    }
    app_ref = f"{RETRO_ROM_CONTAINER_DIR}/{os.path.basename(host_path)}"
    return mount, app_ref


async def resolve_launch_config(
    db: AsyncSession, media_item: Any
) -> dict[str, Any]:
    """Resolve the effective launch config for a game.

    Returns
    ``{"docker_image", "runtime_profile", "app_env", "app_mounts",
    "state_scope", "profile_name"}`` where:

    - The profile is chosen from ``extra_data.lightrays.profile`` (name OR
      guid); falling back to the default ``steam`` profile by name. If no
      matching profile exists, degrades gracefully (image from per-game
      override or ``None``, ``runtime_profile`` ``None`` so the caller's
      default applies).
    - ``docker_image`` = per-game override (``extra_data.lightrays.docker_image``)
      OR ``profile.docker_image``.
    - ``runtime_profile`` = ``profile.runtime_profile`` (or ``None`` when no
      profile resolved).
    - ``app_env`` = ``{**profile.env, **per_game_env}`` (per-game wins).
      Only profile + game env are merged here; the system layer is set by
      the Lightrays service itself.
    - ``app_mounts`` = profile-level mounts (read from ``profile.mounts`` via
      ``getattr`` if the model ever grows the field; empty otherwise) followed
      by per-game mounts (``extra_data.lightrays.mounts``). Each entry is
      normalised/validated to ``{"host", "container", "ro"}`` (absolute paths
      required, invalid entries dropped silently). Sanctioned host→container
      binds (e.g. a Wine game folder); the real host-path allowlist is enforced
      by Lightrays.
    - ``state_scope`` = the resolved profile's persistent-state scope
      (``"game"`` or ``"user"``); ``"game"`` when no profile resolved. The
      caller uses it to derive the ``/home/retro`` mount key so a
      user-scoped profile (e.g. ``steam``) shares one state across all of a
      user's games.
    - ``profile_name`` = the resolved profile's canonical name (or ``None``
      when no profile resolved). Used with ``state_scope == "user"`` to build
      a stable per-user state key (see :func:`compute_app_id`), so every game
      resolving to the same profile — whether it referenced it by name or by
      guid — shares one key.
    """
    lr = _load_lightrays_extra(media_item)

    per_game_image = _clean_str(lr.get("docker_image"))
    per_game_env = _clean_env(lr.get("env"))
    # Sanctioned per-game host→container mounts (e.g. a Wine game folder).
    per_game_mounts = _clean_mounts(lr.get("mounts"))
    # Per-game launch target (e.g. Steam app id) substituted into the
    # profile's `{app_ref}` launch template so the profile holds the launch
    # command once and each game supplies only its own id.
    app_ref = _clean_str(lr.get("app_ref"))

    profile: ContainerProfile | None = None
    ref = _clean_str(lr.get("profile"))
    if ref:
        profile = await get_by_name(db, ref)
        if profile is None:
            profile = await get_by_guid(db, ref)
    else:
        profile = await get_by_name(db, DEFAULT_PROFILE_NAME)

    if profile is None:
        # No profile resolved: preserve legacy behaviour — image is whatever
        # the per-game override says (possibly None), runtime_profile falls to
        # the caller's default, and only the per-game env applies.
        return {
            "docker_image": per_game_image,
            "runtime_profile": None,
            "app_env": _apply_app_ref(per_game_env, app_ref),
            "app_mounts": per_game_mounts,
            "state_scope": "game",
            "profile_name": None,
        }

    profile_env = _clean_env(profile.env)
    # Profile-level mounts (optional; the ContainerProfile model may not carry
    # the field yet). Profile mounts come first, per-game mounts after.
    profile_mounts = _clean_mounts(getattr(profile, "mounts", None))
    state_scope = _clean_str(getattr(profile, "state_scope", None)) or "game"

    # libretro (retro) games carry no importer-stamped app_ref/mounts — the ROM
    # is a plain MediaFile in the games library. Derive the ROM bind mount + the
    # in-container ROM path (app_ref) from the file itself, unless the game
    # already supplies an explicit app_ref (manual override).
    derived_mounts: list[dict[str, Any]] = []
    if _clean_str(getattr(profile, "kind", None)) == "libretro" and not app_ref:
        rom_mount, rom_app_ref = await _derive_rom_launch(db, media_item)
        if rom_app_ref:
            app_ref = rom_app_ref
            derived_mounts = [rom_mount]

    return {
        "docker_image": per_game_image or profile.docker_image,
        "runtime_profile": profile.runtime_profile,
        "app_env": _apply_app_ref({**profile_env, **per_game_env}, app_ref),
        "app_mounts": [*profile_mounts, *derived_mounts, *per_game_mounts],
        "state_scope": state_scope,
        "profile_name": profile.name,
    }


# ── App-id (persistent-state key) computation ────────────────────────────────

# Characters allowed in the user-scoped key's profile-name suffix. Profile
# names are admin-authored free text, so we slug them down to an ascii-safe,
# deterministic token before using them in a container/mount key.
_APP_ID_NAME_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def compute_app_id(
    user_guid: str,
    game_guid: str,
    state_scope: str,
    profile_name: str | None = None,
) -> str:
    """Derive the persistent-state key mounted as ``/home/retro`` at launch.

    - ``state_scope == "user"``: a stable per-user key that OMITS the game
      guid, so every game a user launches on this profile shares one state
      (a single Steam login + one shared library). The key is
      ``f"{user_guid}-{slug(profile_name)}"``; the profile name is slugged to
      an ascii-safe token (fallback ``"app"``) so it's safe as a mount key.
    - any other scope (``"game"``): the legacy per-user-per-game key
      ``f"{user_guid}-{game_guid}"``, keeping each game's state isolated.

    Pure and deterministic; ``user_guid``/``game_guid`` are guids (already
    ascii-safe).
    """
    if state_scope == "user":
        slug = "".join(ch for ch in (profile_name or "") if ch in _APP_ID_NAME_ALLOWED)
        return f"{user_guid}-{slug or 'app'}"
    return f"{user_guid}-{game_guid}"
