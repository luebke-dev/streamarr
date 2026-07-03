"""AirPlay HTTP control and status."""

from __future__ import annotations

import plistlib

import httpx
from fastapi import HTTPException

from .common import _airplay_seconds, _decimal_seconds, _payload_number
from .models import CastTarget, CastTargetStatus


def _airplay_base_url(target: CastTarget) -> str:
    if target.control_url:
        return target.control_url.rstrip("/")
    if not target.host:
        raise HTTPException(status_code=422, detail="AirPlay target host is required")
    port = target.port or 7000
    return f"http://{target.host}:{port}"


def _airplay_play_payload(media_url: str, payload: dict) -> dict[str, str]:
    start_position = _payload_number(
        payload, "start_position", "start_position_seconds", "position_seconds"
    )
    duration = _payload_number(payload, "duration_seconds", "duration")
    play_payload = {
        "Content-Location": media_url,
        "Start-Position": _decimal_seconds(start_position),
    }
    if duration is not None:
        play_payload["Duration"] = _decimal_seconds(duration)
    metadata_fields = {
        "Title": payload.get("title") or payload.get("name"),
        "Artist": payload.get("artist") or payload.get("creator"),
        "Album": payload.get("album"),
        "Artwork-URL": payload.get("artwork_url") or payload.get("poster_url") or payload.get("image_url"),
    }
    for key, value in metadata_fields.items():
        if value is not None:
            play_payload[key] = str(value)
    return play_payload


async def _send_airplay_command(target: CastTarget, command: str, payload: dict) -> None:
    command_key = command.lower()
    base_url = _airplay_base_url(target)
    requests: list[tuple[str, str, dict | None]] = []
    if command_key == "play":
        media_url = payload.get("media_url") or payload.get("url")
        if not isinstance(media_url, str) or not media_url:
            raise HTTPException(status_code=422, detail="AirPlay play requires media_url")
        requests.append(
            (
                "post",
                f"{base_url}/play",
                _airplay_play_payload(media_url, payload),
            )
        )
    elif command_key == "pause":
        requests.append(("post", f"{base_url}/rate?value=0", None))
    elif command_key in {"resume", "playback_resume"}:
        requests.append(("post", f"{base_url}/rate?value=1", None))
    elif command_key == "stop":
        requests.append(("post", f"{base_url}/stop", None))
    else:
        raise HTTPException(status_code=422, detail="Unsupported AirPlay command")

    async with httpx.AsyncClient(timeout=5.0) as client:
        for method, url, form_data in requests:
            response = await getattr(client, method)(url, data=form_data)
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=409,
                    detail=f"AirPlay command failed with status {response.status_code}",
                )


async def _get_airplay_status(target: CastTarget) -> CastTargetStatus:
    base_url = _airplay_base_url(target)
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{base_url}/playback-info")
    if response.status_code >= 400:
        raise HTTPException(
            status_code=409,
            detail=f"AirPlay status failed with status {response.status_code}",
        )
    try:
        raw_plist = plistlib.loads(response.content)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Invalid AirPlay status response") from exc
    raw = {
        str(key): str(value)
        for key, value in raw_plist.items()
        if value is not None
    }
    rate = raw_plist.get("rate")
    state = "PLAYING" if isinstance(rate, (int, float)) and rate > 0 else "PAUSED"
    return CastTargetStatus(
        target_id=target.id,
        protocol=target.protocol,
        transport_state=state,
        transport_status="OK" if raw_plist else None,
        media_url=raw.get("uuid") or raw.get("Content-Location"),
        duration=_airplay_seconds(raw_plist.get("duration")),
        position=_airplay_seconds(raw_plist.get("position")),
        track_uri=raw.get("uuid"),
        raw=raw,
    )
