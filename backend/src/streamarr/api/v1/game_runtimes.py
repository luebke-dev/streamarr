"""Game-runtimes admin API — CRUD for container profiles.

A "game runtime" is a global, admin-controlled :class:`ContainerProfile`: the
Docker image plus the server-side ``runtime_profile`` Lightrays resolves, a
shared container ``env``, and the persistent-state ``state_scope``. Individual
games reference a runtime by name/guid via ``extra_data.lightrays.profile``.

The underlying table is ``container_profile`` — "runtime" is only the
user-facing name in the admin UI. All endpoints require a superuser; runtimes
are a global, security-sensitive resource (they pin the Docker image and env a
game launches with).
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from streamarr.api.dependencies import CurrentSuperuser, DatabaseSession
from streamarr.services import container_profiles as profiles

logger = logging.getLogger(__name__)

router = APIRouter()

# runtime_profile values Lightrays knows how to resolve (see launch.rs
# build_container_config). "gow-app" is the generic, GOW-agnostic launcher.
ALLOWED_RUNTIME_PROFILES = {"none", "gow-steam", "gow-app"}
# Persistent-state scope for the /home/retro mount (see ContainerProfile).
ALLOWED_STATE_SCOPES = {"game", "user"}


# ── Request / Response schemas ──────────────────────────────────────────────


class RuntimeResponse(BaseModel):
    guid: UUID
    name: str
    kind: str
    docker_image: str
    runtime_profile: str
    state_scope: str
    env: dict[str, str] = {}
    is_builtin: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RuntimeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    docker_image: str = Field(min_length=1, max_length=255)
    runtime_profile: str = "gow-app"
    state_scope: str = "game"
    env: dict[str, str] = {}


class RuntimeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    kind: str | None = Field(default=None, min_length=1, max_length=32)
    docker_image: str | None = Field(default=None, min_length=1, max_length=255)
    runtime_profile: str | None = None
    state_scope: str | None = None
    env: dict[str, str] | None = None


def _serialize(profile: Any) -> RuntimeResponse:
    return RuntimeResponse(
        guid=profile.guid,
        name=profile.name,
        kind=profile.kind,
        docker_image=profile.docker_image,
        runtime_profile=profile.runtime_profile,
        state_scope=getattr(profile, "state_scope", "game") or "game",
        env=dict(profile.env or {}),
        is_builtin=profile.is_builtin,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _validate_docker_image(value: str) -> str:
    """Validate a Docker image reference (mirrors the launch-time check)."""
    image = str(value).strip()
    if not image:
        raise HTTPException(status_code=400, detail="Docker image is required")
    allowed = set("._-/:@")
    if (
        len(image) > 255
        or image.startswith(("-", "/", ":"))
        or image.endswith("/")
        or "//" in image
        or ".." in image
        or not all(ch.isascii() and (ch.isalnum() or ch in allowed) for ch in image)
    ):
        raise HTTPException(status_code=400, detail="Invalid Docker image reference")
    return image


def _validate_runtime_profile(value: str) -> str:
    rp = str(value).strip()
    if rp not in ALLOWED_RUNTIME_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"runtime_profile must be one of {sorted(ALLOWED_RUNTIME_PROFILES)}",
        )
    return rp


def _validate_state_scope(value: str) -> str:
    scope = str(value).strip()
    if scope not in ALLOWED_STATE_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"state_scope must be one of {sorted(ALLOWED_STATE_SCOPES)}",
        )
    return scope


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("", response_model=list[RuntimeResponse])
async def list_runtimes(db: DatabaseSession, _admin: CurrentSuperuser):
    """List all game runtimes (container profiles), ordered by name."""
    items = await profiles.list_profiles(db)
    return [_serialize(p) for p in items]


@router.post("", response_model=RuntimeResponse, status_code=201)
async def create_runtime(
    body: RuntimeCreateRequest, db: DatabaseSession, _admin: CurrentSuperuser
):
    """Create a new game runtime."""
    name = body.name.strip()
    if await profiles.get_by_name(db, name):
        raise HTTPException(
            status_code=409, detail=f"A runtime named '{name}' already exists"
        )
    docker_image = _validate_docker_image(body.docker_image)
    runtime_profile = _validate_runtime_profile(body.runtime_profile)
    state_scope = _validate_state_scope(body.state_scope)

    profile = await profiles.create(
        db,
        name=name,
        kind=body.kind.strip(),
        docker_image=docker_image,
        runtime_profile=runtime_profile,
        env=dict(body.env or {}),
        state_scope=state_scope,
    )
    return _serialize(profile)


@router.get("/{guid}", response_model=RuntimeResponse)
async def get_runtime(guid: UUID, db: DatabaseSession, _admin: CurrentSuperuser):
    """Fetch a single game runtime by guid."""
    profile = await profiles.get_by_guid(db, guid)
    if profile is None:
        raise HTTPException(status_code=404, detail="Runtime not found")
    return _serialize(profile)


@router.put("/{guid}", response_model=RuntimeResponse)
async def update_runtime(
    guid: UUID,
    body: RuntimeUpdateRequest,
    db: DatabaseSession,
    _admin: CurrentSuperuser,
):
    """Update a game runtime. Builtins are editable but cannot be renamed."""
    profile = await profiles.get_by_guid(db, guid)
    if profile is None:
        raise HTTPException(status_code=404, detail="Runtime not found")

    fields: dict[str, Any] = {}
    if body.name is not None:
        name = body.name.strip()
        if name != profile.name:
            # Renaming a builtin would break the default-runtime fallback
            # (resolve_launch_config looks the "steam" builtin up by name).
            if profile.is_builtin:
                raise HTTPException(
                    status_code=400, detail="Builtin runtimes cannot be renamed"
                )
            existing = await profiles.get_by_name(db, name)
            if existing and existing.guid != profile.guid:
                raise HTTPException(
                    status_code=409,
                    detail=f"A runtime named '{name}' already exists",
                )
            fields["name"] = name
    if body.kind is not None:
        fields["kind"] = body.kind.strip()
    if body.docker_image is not None:
        fields["docker_image"] = _validate_docker_image(body.docker_image)
    if body.runtime_profile is not None:
        fields["runtime_profile"] = _validate_runtime_profile(body.runtime_profile)
    if body.state_scope is not None:
        fields["state_scope"] = _validate_state_scope(body.state_scope)
    if body.env is not None:
        fields["env"] = dict(body.env)

    updated = await profiles.update(db, profile, **fields)
    return _serialize(updated)


@router.delete("/{guid}", status_code=204)
async def delete_runtime(guid: UUID, db: DatabaseSession, _admin: CurrentSuperuser):
    """Delete a game runtime. Builtin runtimes cannot be deleted."""
    profile = await profiles.get_by_guid(db, guid)
    if profile is None:
        raise HTTPException(status_code=404, detail="Runtime not found")
    try:
        await profiles.delete(db, profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
