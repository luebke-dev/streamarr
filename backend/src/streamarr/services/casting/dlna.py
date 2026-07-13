"""DLNA (UPnP AVTransport) SOAP control and status."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from html import escape

import httpx
from fastapi import HTTPException

from .common import (
    _cast_mime_type,
    _payload_seconds,
    _seconds_to_dlna_time,
)
from .models import CastTarget, CastTargetStatus


def _dlna_control_url(target: CastTarget) -> str:
    if target.control_url:
        return target.control_url
    if not target.host:
        raise HTTPException(status_code=422, detail="DLNA target host is required")
    port = target.port or 1400
    return f"http://{target.host}:{port}/MediaRenderer/AVTransport/Control"


def _dlna_soap_body(action: str, arguments: dict[str, str] | None = None) -> str:
    args_xml = "".join(
        f"<{name}>{escape(value)}</{name}>" for name, value in (arguments or {}).items()
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      {args_xml}
    </u:{action}>
  </s:Body>
</s:Envelope>"""


def _parse_dlna_response(xml_text: str) -> dict[str, str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    values: dict[str, str] = {}
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"Envelope", "Body"}:
            continue
        text = element.text
        if text is not None:
            values[tag] = text
    return values


async def _post_dlna_action(
    client: httpx.AsyncClient,
    control_url: str,
    action: str,
    arguments: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.post(
        control_url,
        content=_dlna_soap_body(action, arguments),
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
        },
    )


def _dlna_seek_target(payload: dict) -> str:
    raw_target = payload.get("target") or payload.get("position")
    if isinstance(raw_target, str) and raw_target:
        return raw_target
    raw_seconds = payload.get("position_seconds")
    if isinstance(raw_seconds, (int, float)):
        return _seconds_to_dlna_time(int(raw_seconds))
    raise HTTPException(
        status_code=422,
        detail="DLNA seek requires target or position_seconds",
    )


def _dlna_item_class(media_type: str | None) -> str:
    media_type = (media_type or "").lower()
    if media_type in {"audio", "music", "song", "album"}:
        return "object.item.audioItem.musicTrack"
    if media_type in {"image", "photo"}:
        return "object.item.imageItem.photo"
    return "object.item.videoItem"


def _dlna_metadata(payload: dict, media_url: str) -> str:
    raw_metadata = payload.get("metadata")
    if isinstance(raw_metadata, str):
        return raw_metadata
    if isinstance(raw_metadata, dict):
        payload = {**raw_metadata, **payload}

    title = str(payload.get("title") or payload.get("name") or "streamarr media")
    creator = payload.get("creator") or payload.get("artist") or payload.get("album_artist")
    artwork_url = payload.get("artwork_url") or payload.get("poster_url") or payload.get("image_url")
    mime_type = _cast_mime_type({"media_url": media_url, **payload})
    item_class = _dlna_item_class(payload.get("media_type") or payload.get("type"))
    duration_seconds = _payload_seconds(payload, "duration_seconds", "duration")
    duration_attr = (
        f' duration="{escape(_seconds_to_dlna_time(duration_seconds))}"'
        if duration_seconds is not None
        else ""
    )

    optional_parts = []
    if creator:
        optional_parts.append(f"<dc:creator>{escape(str(creator))}</dc:creator>")
    if artwork_url:
        optional_parts.append(f"<upnp:albumArtURI>{escape(str(artwork_url))}</upnp:albumArtURI>")

    return (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        '<item id="streamarr-cast-item" parentID="0" restricted="1">'
        f"<dc:title>{escape(title)}</dc:title>"
        f"{''.join(optional_parts)}"
        f"<upnp:class>{item_class}</upnp:class>"
        f'<res protocolInfo="http-get:*:{escape(mime_type)}:*"{duration_attr}>{escape(media_url)}</res>'
        "</item>"
        "</DIDL-Lite>"
    )


async def _send_dlna_command(target: CastTarget, command: str, payload: dict) -> None:
    command_key = command.lower()
    control_url = _dlna_control_url(target)
    soap_actions: list[tuple[str, dict[str, str] | None]] = []
    if command_key == "play":
        media_url = payload.get("media_url") or payload.get("url")
        if not isinstance(media_url, str) or not media_url:
            raise HTTPException(status_code=422, detail="DLNA play requires media_url")
        soap_actions.append(
            (
                "SetAVTransportURI",
                {
                    "CurrentURI": media_url,
                    "CurrentURIMetaData": _dlna_metadata(payload, media_url),
                },
            )
        )
        soap_actions.append(("Play", {"Speed": "1"}))
    elif command_key == "pause":
        soap_actions.append(("Pause", None))
    elif command_key in {"resume", "playback_resume"}:
        soap_actions.append(("Play", {"Speed": "1"}))
    elif command_key == "stop":
        soap_actions.append(("Stop", None))
    elif command_key == "seek":
        soap_actions.append(
            (
                "Seek",
                {
                    "Unit": str(payload.get("unit") or "REL_TIME"),
                    "Target": _dlna_seek_target(payload),
                },
            )
        )
    else:
        raise HTTPException(
            status_code=422,
            detail="Unsupported DLNA command",
        )

    async with httpx.AsyncClient(timeout=5.0) as client:
        for action, arguments in soap_actions:
            response = await _post_dlna_action(client, control_url, action, arguments)
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=409,
                    detail=f"DLNA command failed with status {response.status_code}",
                )


async def _get_dlna_status(target: CastTarget) -> CastTargetStatus:
    control_url = _dlna_control_url(target)
    raw: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for action in ("GetTransportInfo", "GetPositionInfo"):
            response = await _post_dlna_action(client, control_url, action)
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=409,
                    detail=f"DLNA status failed with status {response.status_code}",
                )
            raw.update(_parse_dlna_response(response.text))

    return CastTargetStatus(
        target_id=target.id,
        protocol=target.protocol,
        transport_state=raw.get("CurrentTransportState"),
        transport_status=raw.get("CurrentTransportStatus"),
        media_url=raw.get("TrackURI") or raw.get("CurrentURI"),
        duration=raw.get("TrackDuration"),
        position=raw.get("RelTime"),
        track_uri=raw.get("TrackURI"),
        raw=raw,
    )
