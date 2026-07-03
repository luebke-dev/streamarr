"""Cast target registry and control endpoints.

Protocol/discovery implementations (SSDP/mDNS discovery, DLNA SOAP,
Chromecast Cast V2, AirPlay) live in :mod:`pyrate.services.casting`. This
module keeps only the HTTP handlers, their request/response schemas, and the
router wiring.
"""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.auth.dependencies import get_current_superuser, get_current_user
from pyrate.database import get_db_session
from pyrate.models.user import User
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.services.activity_log import ActivityLogService
from pyrate.services.casting import (
    _CONTAINER_MIME_TYPES,
    CastDiscoveryTarget,
    CastProtocol,
    CastTarget,
    CastTargetStatus,
    _discover_dlna_targets,
    _discover_mdns_targets,
    _get_airplay_status,
    _get_chromecast_status,
    _get_dlna_status,
    _send_airplay_command,
    _send_chromecast_command,
    _send_dlna_command,
)
from pyrate.services.settings import SettingsService
from pyrate.services.websocket import RemoteControlError, get_websocket_manager

router = APIRouter()


class CastTargetsUpdate(BaseModel):
    targets: list[CastTarget] = Field(default_factory=list, max_length=100)


class CastDiscoveryResponse(BaseModel):
    items: list[CastDiscoveryTarget]
    total: int


class CastContainerProfile(BaseModel):
    container: str
    mime_type: str
    media_type: Literal["audio", "video", "image"]


class CastTranscodingProfile(BaseModel):
    container: str
    video_codec: str | None = None
    audio_codec: str | None = None
    mime_type: str
    protocol: Literal["hls", "http"]


class CastProtocolCapability(BaseModel):
    protocol: CastProtocol
    display_name: str
    discovery_supported: bool
    remote_control_supported: bool
    native_sender_supported: bool
    playback_profile_id: str | None = None
    supported_commands: list[str] = Field(default_factory=list)
    supported_media_types: list[str] = Field(default_factory=list)
    container_profiles: list[CastContainerProfile] = Field(default_factory=list)
    transcoding_profiles: list[CastTranscodingProfile] = Field(default_factory=list)
    supports_volume_control: bool = False
    notes: str | None = None


class CastCommand(BaseModel):
    command: str = Field(min_length=1, max_length=100)
    payload: dict = Field(default_factory=dict)


class CastCommandResponse(BaseModel):
    target_id: str
    status: Literal["sent"]


async def _load_targets(session: AsyncSession) -> list[CastTarget]:
    raw_targets = await SettingsService(session).get("cast.targets", [])
    if not isinstance(raw_targets, list):
        return []
    targets: list[CastTarget] = []
    for raw in raw_targets:
        if not isinstance(raw, dict):
            continue
        try:
            targets.append(CastTarget(**raw))
        except Exception:
            continue
    return targets


def _container_profiles(containers: list[str]) -> list[CastContainerProfile]:
    profiles = []
    for container in containers:
        mime_type, media_type = _CONTAINER_MIME_TYPES.get(
            container,
            ("application/octet-stream", "video"),
        )
        profiles.append(
            CastContainerProfile(
                container=container,
                mime_type=mime_type,
                media_type=media_type,
            )
        )
    return profiles


@router.get("/targets", response_model=list[CastTarget])
async def list_cast_targets(
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
):
    """List manually registered cast targets."""
    return [target for target in await _load_targets(session) if target.enabled]


@router.get("/discover", response_model=CastDiscoveryResponse)
async def discover_cast_targets(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    native: bool = Query(False),
    ssdp_timeout_seconds: float = Query(1.0, ge=0.1, le=5.0),
    mdns_timeout_seconds: float = Query(1.0, ge=0.1, le=5.0),
):
    """Return manual targets plus active pyrate receiver sessions for this user."""
    items: list[CastDiscoveryTarget] = [
        CastDiscoveryTarget(
            **target.model_dump(),
            discovered=False,
            discovery_source="manual",
        )
        for target in await _load_targets(session)
        if target.enabled
    ]

    known_ids = {target.id for target in items}
    manager = get_websocket_manager()
    for active_session in manager.get_active_device_sessions(str(current_user.guid)):
        device_id = active_session.get("device_id")
        if not device_id:
            continue
        target_id = f"pyrate:{device_id}"
        if target_id in known_ids:
            continue
        items.append(
            CastDiscoveryTarget(
                id=target_id,
                name=str(device_id),
                protocol="pyrate",
                device_id=str(device_id),
                supports_remote_control=True,
                enabled=True,
                discovered=True,
                discovery_source="active_session",
                connection_count=active_session.get("connection_count"),
                last_seen_at=(
                    active_session["last_seen_at"].isoformat()
                    if active_session.get("last_seen_at")
                    else None
                ),
            )
        )
        known_ids.add(target_id)

    if native:
        for target in [
            *_discover_dlna_targets(ssdp_timeout_seconds),
            *_discover_mdns_targets(mdns_timeout_seconds),
        ]:
            if target.id in known_ids:
                continue
            items.append(target)
            known_ids.add(target.id)
    return CastDiscoveryResponse(items=items, total=len(items))


@router.get("/protocols", response_model=list[CastProtocolCapability])
async def list_cast_protocol_capabilities(
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """Return cast protocol capabilities exposed by this server."""
    return [
        CastProtocolCapability(
            protocol="pyrate",
            display_name="pyrate receiver",
            discovery_supported=True,
            remote_control_supported=True,
            native_sender_supported=True,
            playback_profile_id="browser",
            supported_commands=[
                "play",
                "pause",
                "resume",
                "stop",
                "seek",
                "play_queue",
            ],
            supported_media_types=["video", "audio", "image"],
            container_profiles=_container_profiles(["mp4", "webm", "m4a", "mp3", "flac", "jpg", "png"]),
            transcoding_profiles=[
                CastTranscodingProfile(
                    container="mpegts",
                    video_codec="h264",
                    audio_codec="aac",
                    mime_type="application/vnd.apple.mpegurl",
                    protocol="hls",
                )
            ],
            notes="Active pyrate WebSocket receiver sessions can be discovered and controlled.",
        ),
        CastProtocolCapability(
            protocol="chromecast",
            display_name="Chromecast",
            discovery_supported=True,
            remote_control_supported=True,
            native_sender_supported=True,
            playback_profile_id="chromecast",
            supported_commands=[
                "play",
                "pause",
                "resume",
                "stop",
                "seek",
                "queue_load",
                "volume",
                "mute",
                "unmute",
            ],
            supports_volume_control=True,
            supported_media_types=["video", "audio", "image"],
            container_profiles=_container_profiles(["mp4", "webm", "mkv", "mp3", "m4a", "flac"]),
            transcoding_profiles=[
                CastTranscodingProfile(
                    container="mp4",
                    video_codec="h264",
                    audio_codec="aac",
                    mime_type="video/mp4",
                    protocol="http",
                ),
                CastTranscodingProfile(
                    container="webm",
                    video_codec="vp9",
                    audio_codec="opus",
                    mime_type="video/webm",
                    protocol="http",
                ),
            ],
            notes="Native mDNS discovery plus DIAL/Eureka app launch, stop, status, and basic Cast V2 media play/pause/resume/stop/seek support are available for configured receivers.",
        ),
        CastProtocolCapability(
            protocol="dlna",
            display_name="DLNA",
            discovery_supported=True,
            remote_control_supported=True,
            native_sender_supported=False,
            playback_profile_id="dlna_generic",
            supported_commands=["play", "pause", "resume", "stop", "seek"],
            supported_media_types=["video", "audio", "image"],
            container_profiles=_container_profiles(["mp4", "mpegts", "ts", "mp3", "jpg", "png"]),
            transcoding_profiles=[
                CastTranscodingProfile(
                    container="mpegts",
                    video_codec="h264",
                    audio_codec="aac",
                    mime_type="video/mp2t",
                    protocol="http",
                )
            ],
            notes="Native SSDP discovery plus AVTransport play/pause/stop/seek/status support are available for configured renderers.",
        ),
        CastProtocolCapability(
            protocol="airplay",
            display_name="AirPlay",
            discovery_supported=True,
            remote_control_supported=True,
            native_sender_supported=False,
            playback_profile_id="browser",
            supported_commands=["play", "pause", "resume", "stop"],
            supported_media_types=["video", "audio", "image"],
            container_profiles=_container_profiles(["mp4", "mov", "m4a", "mp3", "jpg", "png"]),
            transcoding_profiles=[
                CastTranscodingProfile(
                    container="mp4",
                    video_codec="h264",
                    audio_codec="aac",
                    mime_type="video/mp4",
                    protocol="http",
                )
            ],
            notes="Native mDNS discovery plus basic HTTP play/pause/resume/stop/status support are available for configured receivers.",
        ),
    ]


@router.put("/targets", response_model=list[CastTarget])
async def update_cast_targets(
    update: CastTargetsUpdate,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Replace manually registered cast targets."""
    await SettingsService(session).set(
        "cast.targets",
        [target.model_dump(exclude_none=True) for target in update.targets],
    )
    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type="cast.targets_update",
            message=f"Updated {len(update.targets)} cast targets",
            entity_type="cast",
            extra_data=json.dumps({"count": len(update.targets)}, sort_keys=True),
        ),
        actor_guid=current_user.guid,
    )
    return update.targets


@router.get("/targets/{target_id}/status", response_model=CastTargetStatus)
async def get_cast_target_status(
    target_id: str,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
):
    """Return protocol status for a configured cast target when supported."""
    target = next(
        (
            target
            for target in await _load_targets(session)
            if target.id == target_id and target.enabled
        ),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Cast target not found")
    if target.protocol == "dlna":
        return await _get_dlna_status(target)
    if target.protocol == "airplay":
        return await _get_airplay_status(target)
    if target.protocol == "chromecast":
        return await _get_chromecast_status(target)
    raise HTTPException(
        status_code=422,
        detail="Status is only supported for Chromecast, DLNA, and AirPlay targets",
    )


@router.post("/targets/{target_id}/commands", response_model=CastCommandResponse)
async def send_cast_target_command(
    target_id: str,
    body: CastCommand,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Send a command to a cast target backed by a connected pyrate device."""
    target = next(
        (
            target
            for target in await _load_targets(session)
            if target.id == target_id and target.enabled
        ),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Cast target not found")
    if target.protocol == "dlna":
        await _send_dlna_command(target, body.command, body.payload)
    elif target.protocol == "chromecast":
        await _send_chromecast_command(target, body.command, body.payload)
    elif target.protocol == "airplay":
        await _send_airplay_command(target, body.command, body.payload)
    elif target.protocol == "pyrate" and target.device_id:
        try:
            await get_websocket_manager().send_remote_control_command(
                user_id=str(current_user.guid),
                target_device_id=target.device_id,
                command=body.command,
                payload=body.payload,
                actor_user_id=str(current_user.guid),
            )
        except RemoteControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    else:
        raise HTTPException(
            status_code=422,
            detail="This cast target is registered for discovery only",
        )

    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type="cast.command",
            message=f"Sent cast command {body.command} to {target.name}",
            entity_type="cast",
            extra_data=json.dumps(
                {
                    "target_id": target.id,
                    "protocol": target.protocol,
                    "command": body.command,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )
    return CastCommandResponse(target_id=target.id, status="sent")
