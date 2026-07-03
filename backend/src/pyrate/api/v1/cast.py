"""Cast target registry and control helpers."""

from __future__ import annotations

import asyncio
import json
import plistlib
import socket
import ssl
import struct
import xml.etree.ElementTree as ET
from html import escape
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.auth.dependencies import get_current_superuser, get_current_user
from pyrate.database import get_db_session
from pyrate.models.user import User
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.services.activity_log import ActivityLogService
from pyrate.services.settings import SettingsService
from pyrate.services.websocket import RemoteControlError, get_websocket_manager

router = APIRouter()

CastProtocol = Literal["pyrate", "chromecast", "dlna", "airplay"]


class CastTarget(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    protocol: CastProtocol
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    control_url: str | None = Field(default=None, max_length=2048)
    device_id: str | None = Field(default=None, max_length=255)
    supports_remote_control: bool = False
    enabled: bool = True


class CastTargetsUpdate(BaseModel):
    targets: list[CastTarget] = Field(default_factory=list, max_length=100)


class CastDiscoveryTarget(CastTarget):
    discovered: bool = True
    discovery_source: Literal["manual", "active_session", "ssdp", "mdns"] = "manual"
    connection_count: int | None = None
    last_seen_at: str | None = None


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


class CastTargetStatus(BaseModel):
    target_id: str
    protocol: CastProtocol
    transport_state: str | None = None
    transport_status: str | None = None
    media_url: str | None = None
    duration: str | None = None
    position: str | None = None
    track_uri: str | None = None
    raw: dict[str, str] = Field(default_factory=dict)


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


def _parse_ssdp_response(raw_response: bytes) -> dict[str, str]:
    try:
        text = raw_response.decode("utf-8", errors="ignore")
    except Exception:
        return {}
    headers: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


def _discover_dlna_targets(timeout_seconds: float = 1.0) -> list[CastDiscoveryTarget]:
    message = "\r\n".join(
        [
            "M-SEARCH * HTTP/1.1",
            "HOST: 239.255.255.250:1900",
            'MAN: "ssdp:discover"',
            "MX: 1",
            "ST: urn:schemas-upnp-org:device:MediaRenderer:1",
            "",
            "",
        ]
    ).encode("ascii")
    targets: list[CastDiscoveryTarget] = []
    seen: set[str] = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.settimeout(timeout_seconds)
        sock.sendto(message, ("239.255.255.250", 1900))
        while True:
            try:
                raw_response, address = sock.recvfrom(8192)
            except TimeoutError:
                break
            except OSError:
                break
            headers = _parse_ssdp_response(raw_response)
            location = headers.get("location")
            usn = headers.get("usn") or headers.get("usn".upper())
            target_key = usn or location or address[0]
            if not target_key or target_key in seen:
                continue
            seen.add(target_key)
            parsed_location = urlsplit(location or "")
            host = parsed_location.hostname or address[0]
            port = parsed_location.port
            server_name = headers.get("server") or headers.get("st") or "DLNA Renderer"
            targets.append(
                CastDiscoveryTarget(
                    id=f"dlna:{target_key}",
                    name=server_name,
                    protocol="dlna",
                    host=host,
                    port=port,
                    supports_remote_control=False,
                    enabled=True,
                    discovered=True,
                    discovery_source="ssdp",
                )
            )
    return targets


def _encode_dns_name(name: str) -> bytes:
    return b"".join(
        bytes([len(part)]) + part.encode("utf-8")
        for part in name.rstrip(".").split(".")
    ) + b"\x00"


def _read_dns_name(data: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    jumped = False
    original_offset = offset
    seen_offsets: set[int] = set()
    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                break
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if pointer in seen_offsets:
                break
            seen_offsets.add(pointer)
            if not jumped:
                original_offset = offset + 2
            offset = pointer
            jumped = True
            continue
        offset += 1
        labels.append(data[offset : offset + length].decode("utf-8", errors="ignore"))
        offset += length
    return ".".join(label for label in labels if label), original_offset if jumped else offset


def _build_mdns_query(service_name: str) -> bytes:
    header = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
    question = _encode_dns_name(service_name) + struct.pack("!HH", 12, 1)
    return header + question


def _parse_mdns_response(data: bytes) -> list[dict]:
    if len(data) < 12:
        return []
    _, _, qdcount, ancount, nscount, arcount = struct.unpack("!HHHHHH", data[:12])
    offset = 12
    for _ in range(qdcount):
        _, offset = _read_dns_name(data, offset)
        offset += 4

    records = []
    for _ in range(ancount + nscount + arcount):
        name, offset = _read_dns_name(data, offset)
        if offset + 10 > len(data):
            break
        record_type, record_class, ttl, rdlength = struct.unpack(
            "!HHIH", data[offset : offset + 10]
        )
        offset += 10
        rdata_offset = offset
        offset += rdlength
        if offset > len(data):
            break

        value = None
        if record_type in {12, 33}:  # PTR, SRV
            if record_type == 33 and rdata_offset + 6 <= len(data):
                _, _, port = struct.unpack("!HHH", data[rdata_offset : rdata_offset + 6])
                target, _ = _read_dns_name(data, rdata_offset + 6)
                value = {"port": port, "target": target}
            else:
                target, _ = _read_dns_name(data, rdata_offset)
                value = target
        elif record_type == 1 and rdlength == 4:
            value = socket.inet_ntoa(data[rdata_offset:offset])
        elif record_type == 16:
            chunks = []
            cursor = rdata_offset
            while cursor < offset:
                chunk_len = data[cursor]
                cursor += 1
                chunks.append(data[cursor : cursor + chunk_len].decode("utf-8", errors="ignore"))
                cursor += chunk_len
            value = chunks

        records.append(
            {
                "name": name,
                "type": record_type,
                "class": record_class,
                "ttl": ttl,
                "value": value,
            }
        )
    return records


def _discover_mdns_service_targets(
    *,
    service_name: str,
    protocol: Literal["chromecast", "airplay"],
    timeout_seconds: float = 1.0,
) -> list[CastDiscoveryTarget]:
    query = _build_mdns_query(service_name)
    records: list[dict] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.settimeout(timeout_seconds)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(query, ("224.0.0.251", 5353))
        while True:
            try:
                raw_response, _ = sock.recvfrom(9000)
            except TimeoutError:
                break
            except OSError:
                break
            records.extend(_parse_mdns_response(raw_response))

    ptr_names = {
        str(record["value"])
        for record in records
        if record["type"] == 12
        and isinstance(record.get("value"), str)
        and service_name in record["name"]
    }
    srv_records = {
        record["name"]: record["value"]
        for record in records
        if record["type"] == 33 and isinstance(record.get("value"), dict)
    }
    address_records = {
        record["name"]: record["value"]
        for record in records
        if record["type"] == 1 and isinstance(record.get("value"), str)
    }
    txt_records = {
        record["name"]: record["value"]
        for record in records
        if record["type"] == 16 and isinstance(record.get("value"), list)
    }

    targets: list[CastDiscoveryTarget] = []
    for instance_name in sorted(ptr_names):
        srv_value = srv_records.get(instance_name) or {}
        target_host = srv_value.get("target") if isinstance(srv_value, dict) else None
        port = srv_value.get("port") if isinstance(srv_value, dict) else None
        host = address_records.get(target_host) or target_host
        display_name = instance_name.split("._", 1)[0].replace("\\032", " ")
        txt_values = txt_records.get(instance_name) or []
        for item in txt_values:
            if item.startswith("fn=") and item[3:]:
                display_name = item[3:]
                break
        target_id = f"{protocol}:{instance_name}"[:100]
        targets.append(
            CastDiscoveryTarget(
                id=target_id,
                name=display_name or protocol.title(),
                protocol=protocol,
                host=host,
                port=port,
                supports_remote_control=False,
                enabled=True,
                discovered=True,
                discovery_source="mdns",
            )
        )
    return targets


def _discover_mdns_targets(timeout_seconds: float = 1.0) -> list[CastDiscoveryTarget]:
    return [
        *_discover_mdns_service_targets(
            service_name="_googlecast._tcp.local",
            protocol="chromecast",
            timeout_seconds=timeout_seconds,
        ),
        *_discover_mdns_service_targets(
            service_name="_airplay._tcp.local",
            protocol="airplay",
            timeout_seconds=timeout_seconds,
        ),
    ]


def _dlna_control_url(target: CastTarget) -> str:
    if target.control_url:
        return target.control_url
    if not target.host:
        raise HTTPException(status_code=422, detail="DLNA target host is required")
    port = target.port or 1400
    return f"http://{target.host}:{port}/MediaRenderer/AVTransport/Control"


def _airplay_base_url(target: CastTarget) -> str:
    if target.control_url:
        return target.control_url.rstrip("/")
    if not target.host:
        raise HTTPException(status_code=422, detail="AirPlay target host is required")
    port = target.port or 7000
    return f"http://{target.host}:{port}"


def _chromecast_base_url(target: CastTarget) -> str:
    if target.control_url:
        return target.control_url.rstrip("/")
    if not target.host:
        raise HTTPException(status_code=422, detail="Chromecast target host is required")
    port = target.port or 8008
    return f"http://{target.host}:{port}"


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


def _seconds_to_dlna_time(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _payload_seconds(payload: dict, *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return max(0, int(value))
        if isinstance(value, str):
            try:
                return max(0, int(float(value)))
            except ValueError:
                continue
    return None


def _payload_number(payload: dict, *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return max(0.0, float(value))
        if isinstance(value, str):
            try:
                return max(0.0, float(value))
            except ValueError:
                continue
    return None


def _decimal_seconds(value: float | None) -> str:
    if value is None:
        return "0"
    return str(int(value)) if value.is_integer() else str(value)


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


_CONTAINER_MIME_TYPES = {
    "mp4": ("video/mp4", "video"),
    "m4v": ("video/mp4", "video"),
    "mov": ("video/quicktime", "video"),
    "mkv": ("video/x-matroska", "video"),
    "webm": ("video/webm", "video"),
    "mpegts": ("video/mp2t", "video"),
    "ts": ("video/mp2t", "video"),
    "mp3": ("audio/mpeg", "audio"),
    "m4a": ("audio/mp4", "audio"),
    "aac": ("audio/aac", "audio"),
    "flac": ("audio/flac", "audio"),
    "wav": ("audio/wav", "audio"),
    "ogg": ("audio/ogg", "audio"),
    "jpg": ("image/jpeg", "image"),
    "jpeg": ("image/jpeg", "image"),
    "png": ("image/png", "image"),
    "webp": ("image/webp", "image"),
}


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


def _cast_mime_type(payload: dict) -> str:
    explicit = payload.get("mime_type") or payload.get("content_type")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    container = payload.get("container") or payload.get("format")
    if isinstance(container, str):
        normalized = container.strip().lower().lstrip(".")
        if normalized in _CONTAINER_MIME_TYPES:
            return _CONTAINER_MIME_TYPES[normalized][0]
    media_url = payload.get("media_url") or payload.get("url")
    if isinstance(media_url, str) and "." in urlsplit(media_url).path:
        extension = urlsplit(media_url).path.rsplit(".", 1)[-1].lower()
        if extension in _CONTAINER_MIME_TYPES:
            return _CONTAINER_MIME_TYPES[extension][0]
    return "video/mp4"


def _dlna_metadata(payload: dict, media_url: str) -> str:
    raw_metadata = payload.get("metadata")
    if isinstance(raw_metadata, str):
        return raw_metadata
    if isinstance(raw_metadata, dict):
        payload = {**raw_metadata, **payload}

    title = str(payload.get("title") or payload.get("name") or "pyrate media")
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
        '<item id="pyrate-cast-item" parentID="0" restricted="1">'
        f"<dc:title>{escape(title)}</dc:title>"
        f"{''.join(optional_parts)}"
        f"<upnp:class>{item_class}</upnp:class>"
        f'<res protocolInfo="http-get:*:{escape(mime_type)}:*"{duration_attr}>{escape(media_url)}</res>'
        "</item>"
        "</DIDL-Lite>"
    )


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


def _airplay_seconds(value) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return _seconds_to_dlna_time(int(value))


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


def _chromecast_app_id(payload: dict) -> str:
    app_id = payload.get("app_id") or payload.get("application_id")
    if not isinstance(app_id, str) or not app_id:
        raise HTTPException(status_code=422, detail="Chromecast command requires app_id")
    return app_id


def _chromecast_receiver_app_id(payload: dict) -> str:
    app_id = payload.get("chromecast_app_id") or payload.get("app_id") or payload.get("application_id")
    if app_id is None:
        return "CC1AD845"
    if not isinstance(app_id, str) or not app_id:
        raise HTTPException(status_code=422, detail="Chromecast app id must be a non-empty string")
    return app_id


def _protobuf_varint(value: int) -> bytes:
    value = max(0, value)
    chunks = []
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            chunks.append(byte | 0x80)
        else:
            chunks.append(byte)
            break
    return bytes(chunks)


def _protobuf_string(field_number: int, value: str) -> bytes:
    encoded = value.encode("utf-8")
    return _protobuf_varint((field_number << 3) | 2) + _protobuf_varint(len(encoded)) + encoded


def _protobuf_int(field_number: int, value: int) -> bytes:
    return _protobuf_varint((field_number << 3) | 0) + _protobuf_varint(value)


def _cast_message(
    *,
    namespace: str,
    payload: dict,
    destination_id: str,
    source_id: str = "sender-0",
) -> bytes:
    payload_json = json.dumps(payload, separators=(",", ":"))
    message = b"".join(
        [
            _protobuf_int(1, 0),  # CASTV2_1_0
            _protobuf_string(2, source_id),
            _protobuf_string(3, destination_id),
            _protobuf_string(4, namespace),
            _protobuf_int(5, 0),  # STRING
            _protobuf_string(6, payload_json),
        ]
    )
    return struct.pack("!I", len(message)) + message


def _read_protobuf_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    return value, offset


def _parse_cast_message(data: bytes) -> dict[str, str]:
    offset = 0
    parsed: dict[str, str] = {}
    fields = {
        2: "source_id",
        3: "destination_id",
        4: "namespace",
        6: "payload_utf8",
    }
    while offset < len(data):
        tag, offset = _read_protobuf_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:
            _, offset = _read_protobuf_varint(data, offset)
        elif wire_type == 2:
            length, offset = _read_protobuf_varint(data, offset)
            raw_value = data[offset : offset + length]
            offset += length
            if field_number in fields:
                parsed[fields[field_number]] = raw_value.decode("utf-8", errors="ignore")
        else:
            break
    return parsed


def _recv_cast_message(sock: ssl.SSLSocket) -> dict[str, str]:
    header = sock.recv(4)
    if len(header) != 4:
        return {}
    (length,) = struct.unpack("!I", header)
    chunks = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return _parse_cast_message(b"".join(chunks))


def _chromecast_media_url(payload: dict) -> str:
    media_url = payload.get("media_url") or payload.get("url")
    if not isinstance(media_url, str) or not media_url:
        raise HTTPException(status_code=422, detail="Chromecast play requires media_url")
    return media_url


def _chromecast_media_descriptor(payload: dict) -> dict:
    media_url = _chromecast_media_url(payload)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    title = payload.get("title") or payload.get("name") or metadata.get("title") or "pyrate media"
    images = []
    artwork_url = payload.get("artwork_url") or payload.get("poster_url") or payload.get("image_url")
    if artwork_url:
        images.append({"url": str(artwork_url)})
    media = {
        "contentId": media_url,
        "streamType": str(payload.get("stream_type") or "BUFFERED"),
        "contentType": _cast_mime_type(payload),
        "metadata": {
            "metadataType": int(payload.get("metadata_type") or 0),
            "title": str(title),
            **metadata,
        },
    }
    if images:
        media["metadata"]["images"] = images
    return media


def _chromecast_load_payload(payload: dict) -> dict:
    return {
        "type": "LOAD",
        "requestId": 1,
        "media": _chromecast_media_descriptor(payload),
        "autoplay": bool(payload.get("autoplay", True)),
        "currentTime": float(payload.get("start_position") or payload.get("position_seconds") or 0),
    }


def _chromecast_queue_item(payload: dict, index: int) -> dict:
    item = {
        "media": _chromecast_media_descriptor(payload),
        "autoplay": bool(payload.get("autoplay", True)),
        "startTime": float(payload.get("start_position") or payload.get("position_seconds") or 0),
    }
    item_id = payload.get("item_id") or payload.get("queue_item_id")
    if item_id is not None:
        item["itemId"] = int(item_id) if isinstance(item_id, int) else str(item_id)
    preload_time = payload.get("preload_time")
    if isinstance(preload_time, (int, float)):
        item["preloadTime"] = float(preload_time)
    if "itemId" not in item:
        item["itemId"] = index + 1
    return item


def _chromecast_queue_load_payload(payload: dict) -> dict:
    raw_items = payload.get("items") or payload.get("queue")
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(status_code=422, detail="Chromecast queue load requires items")
    queue_items = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise HTTPException(status_code=422, detail="Chromecast queue items must be objects")
        queue_items.append(_chromecast_queue_item({**payload, **raw_item}, index))
    return {
        "type": "QUEUE_LOAD",
        "requestId": 1,
        "items": queue_items,
        "startIndex": int(payload.get("start_index") or 0),
        "repeatMode": str(payload.get("repeat_mode") or "REPEAT_OFF"),
    }


def _chromecast_payload_session_id(payload: dict) -> int | None:
    raw_session_id = payload.get("mediaSessionId") or payload.get("media_session_id")
    if raw_session_id is None:
        return None
    try:
        return int(raw_session_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Chromecast media session id must be numeric")


def _chromecast_volume_level(payload: dict) -> float:
    raw_level = payload.get("level", payload.get("volume"))
    if not isinstance(raw_level, (int, float)):
        raise HTTPException(status_code=422, detail="Chromecast volume command requires level")
    level = float(raw_level)
    if 1 < level <= 100:
        level = level / 100
    if level < 0 or level > 1:
        raise HTTPException(status_code=422, detail="Chromecast volume level must be between 0 and 1")
    return level


def _chromecast_receiver_control_payload(command_key: str, payload: dict) -> dict:
    if command_key in {"volume", "set_volume"}:
        volume: dict[str, float | bool] = {"level": _chromecast_volume_level(payload)}
        if isinstance(payload.get("muted"), bool):
            volume["muted"] = payload["muted"]
    elif command_key in {"mute", "unmute", "set_mute"}:
        muted = payload.get("muted")
        if not isinstance(muted, bool):
            muted = command_key != "unmute"
        volume = {"muted": muted}
    else:
        raise HTTPException(status_code=422, detail="Unsupported Chromecast command")
    return {"type": "SET_VOLUME", "requestId": 1, "volume": volume}


def _chromecast_media_control_payload(command_key: str, payload: dict) -> dict:
    if command_key == "play":
        return _chromecast_load_payload(payload)
    if command_key in {"queue_load", "play_queue", "queue"}:
        return _chromecast_queue_load_payload(payload)
    media_session_id = _chromecast_payload_session_id(payload)
    if command_key == "pause":
        response = {"type": "PAUSE", "requestId": 1}
        if media_session_id is not None:
            response["mediaSessionId"] = media_session_id
        return response
    if command_key in {"resume", "playback_resume"}:
        response = {"type": "PLAY", "requestId": 1}
        if media_session_id is not None:
            response["mediaSessionId"] = media_session_id
        return response
    if command_key == "stop":
        response = {"type": "STOP", "requestId": 1}
        if media_session_id is not None:
            response["mediaSessionId"] = media_session_id
        return response
    if command_key == "seek":
        position = payload.get("position_seconds") or payload.get("position")
        if not isinstance(position, (int, float)):
            raise HTTPException(status_code=422, detail="Chromecast seek requires position_seconds")
        response = {"type": "SEEK", "requestId": 1, "currentTime": float(position)}
        if media_session_id is not None:
            response["mediaSessionId"] = media_session_id
        return response
    raise HTTPException(status_code=422, detail="Unsupported Chromecast command")


def _chromecast_socket_endpoint(target: CastTarget) -> tuple[str, int]:
    if not target.host:
        raise HTTPException(status_code=422, detail="Chromecast target host is required")
    return target.host, target.port or 8009


def _extract_chromecast_transport_id(status_payload: dict) -> str | None:
    applications = status_payload.get("status", {}).get("applications", [])
    if not isinstance(applications, list):
        return None
    for app in applications:
        if isinstance(app, dict) and app.get("transportId"):
            return str(app["transportId"])
    return None


def _connect_chromecast_socket(target: CastTarget) -> ssl.SSLSocket:
    host, port = _chromecast_socket_endpoint(target)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    raw_sock = socket.create_connection((host, port), timeout=5.0)
    sock = context.wrap_socket(raw_sock, server_hostname=host)
    sock.settimeout(5.0)
    return sock


def _chromecast_receiver_transport(
    sock: ssl.SSLSocket,
    *,
    launch_app: bool,
    app_id: str,
) -> str:
    sock.sendall(
        _cast_message(
            namespace="urn:x-cast:com.google.cast.tp.connection",
            destination_id="receiver-0",
            payload={"type": "CONNECT"},
        )
    )
    sock.sendall(
        _cast_message(
            namespace="urn:x-cast:com.google.cast.receiver",
            destination_id="receiver-0",
            payload=(
                {"type": "LAUNCH", "appId": app_id, "requestId": 1}
                if launch_app
                else {"type": "GET_STATUS", "requestId": 1}
            ),
        )
    )
    for _ in range(6):
        message = _recv_cast_message(sock)
        payload_text = message.get("payload_utf8")
        if not payload_text:
            continue
        try:
            payload_json = json.loads(payload_text)
        except ValueError:
            continue
        transport_id = _extract_chromecast_transport_id(payload_json)
        if transport_id:
            return transport_id
    raise HTTPException(status_code=409, detail="Chromecast receiver did not provide a media transport")


def _send_chromecast_cast_v2_payload(
    target: CastTarget,
    media_payload: dict,
    *,
    launch_app: bool,
    app_id: str = "CC1AD845",
) -> None:
    with _connect_chromecast_socket(target) as sock:
        transport_id = _chromecast_receiver_transport(
            sock,
            launch_app=launch_app,
            app_id=app_id,
        )
        sock.sendall(
            _cast_message(
                namespace="urn:x-cast:com.google.cast.tp.connection",
                destination_id=transport_id,
                payload={"type": "CONNECT"},
            )
        )
        sock.sendall(
            _cast_message(
                namespace="urn:x-cast:com.google.cast.media",
                destination_id=transport_id,
                payload=media_payload,
            )
        )


def _send_chromecast_receiver_payload(target: CastTarget, receiver_payload: dict) -> None:
    with _connect_chromecast_socket(target) as sock:
        sock.sendall(
            _cast_message(
                namespace="urn:x-cast:com.google.cast.tp.connection",
                destination_id="receiver-0",
                payload={"type": "CONNECT"},
            )
        )
        sock.sendall(
            _cast_message(
                namespace="urn:x-cast:com.google.cast.receiver",
                destination_id="receiver-0",
                payload=receiver_payload,
            )
        )


def _get_chromecast_receiver_status_payload(target: CastTarget) -> dict | None:
    with _connect_chromecast_socket(target) as sock:
        sock.sendall(
            _cast_message(
                namespace="urn:x-cast:com.google.cast.tp.connection",
                destination_id="receiver-0",
                payload={"type": "CONNECT"},
            )
        )
        sock.sendall(
            _cast_message(
                namespace="urn:x-cast:com.google.cast.receiver",
                destination_id="receiver-0",
                payload={"type": "GET_STATUS", "requestId": 1},
            )
        )
        for _ in range(6):
            message = _recv_cast_message(sock)
            if message.get("namespace") != "urn:x-cast:com.google.cast.receiver":
                continue
            payload_text = message.get("payload_utf8")
            if not payload_text:
                continue
            try:
                payload_json = json.loads(payload_text)
            except ValueError:
                continue
            if payload_json.get("type") in {"RECEIVER_STATUS", "STATUS"}:
                return payload_json
    return None


async def _get_chromecast_receiver_status_payload_async(target: CastTarget) -> dict | None:
    try:
        return await asyncio.to_thread(_get_chromecast_receiver_status_payload, target)
    except (HTTPException, OSError):
        return None


def _get_chromecast_media_status_payload(target: CastTarget) -> dict | None:
    with _connect_chromecast_socket(target) as sock:
        transport_id = _chromecast_receiver_transport(
            sock,
            launch_app=False,
            app_id="CC1AD845",
        )
        sock.sendall(
            _cast_message(
                namespace="urn:x-cast:com.google.cast.tp.connection",
                destination_id=transport_id,
                payload={"type": "CONNECT"},
            )
        )
        sock.sendall(
            _cast_message(
                namespace="urn:x-cast:com.google.cast.media",
                destination_id=transport_id,
                payload={"type": "GET_STATUS", "requestId": 1},
            )
        )
        for _ in range(6):
            message = _recv_cast_message(sock)
            if message.get("namespace") != "urn:x-cast:com.google.cast.media":
                continue
            payload_text = message.get("payload_utf8")
            if not payload_text:
                continue
            try:
                payload_json = json.loads(payload_text)
            except ValueError:
                continue
            if payload_json.get("type") == "MEDIA_STATUS":
                return payload_json
    return None


async def _get_chromecast_media_status_payload_async(target: CastTarget) -> dict | None:
    try:
        return await asyncio.to_thread(_get_chromecast_media_status_payload, target)
    except (HTTPException, OSError):
        return None


def _chromecast_media_session_id(media_payload: dict | None) -> int | None:
    statuses = media_payload.get("status") if isinstance(media_payload, dict) else None
    if not isinstance(statuses, list) or not statuses:
        return None
    status = statuses[0]
    if not isinstance(status, dict):
        return None
    session_id = status.get("mediaSessionId")
    if isinstance(session_id, int):
        return session_id
    if isinstance(session_id, str) and session_id.isdigit():
        return int(session_id)
    return None


def _chromecast_status_from_media_payload(
    target: CastTarget,
    media_payload: dict | None,
    *,
    eureka_raw: dict[str, str],
) -> CastTargetStatus | None:
    statuses = media_payload.get("status") if isinstance(media_payload, dict) else None
    if not isinstance(statuses, list) or not statuses:
        return None
    status = statuses[0]
    if not isinstance(status, dict):
        return None
    media = status.get("media") if isinstance(status.get("media"), dict) else {}
    media_url = media.get("contentId") if isinstance(media.get("contentId"), str) else None
    duration = media.get("duration")
    position = status.get("currentTime")
    raw = {
        **eureka_raw,
        **{
            f"media.{key}": value
            for key, value in _flatten_chromecast_status(media_payload).items()
        },
    }
    return CastTargetStatus(
        target_id=target.id,
        protocol=target.protocol,
        transport_state=str(status.get("playerState") or "UNKNOWN"),
        transport_status=str(status.get("idleReason") or "OK"),
        media_url=media_url,
        duration=_airplay_seconds(duration),
        position=_airplay_seconds(position),
        track_uri=media_url,
        raw=raw,
    )


async def _send_chromecast_media_command(target: CastTarget, command: str, payload: dict) -> None:
    command_key = command.lower()
    media_payload = _chromecast_media_control_payload(command_key, payload)
    launch_app = media_payload.get("type") in {"LOAD", "QUEUE_LOAD"}
    app_id = _chromecast_receiver_app_id(payload)
    if not launch_app and "mediaSessionId" not in media_payload:
        session_id = _chromecast_media_session_id(
            await _get_chromecast_media_status_payload_async(target)
        )
        if session_id is None:
            raise HTTPException(status_code=409, detail="Chromecast media session is not available")
        media_payload["mediaSessionId"] = session_id
    try:
        await asyncio.to_thread(
            _send_chromecast_cast_v2_payload,
            target,
            media_payload,
            launch_app=launch_app,
            app_id=app_id,
        )
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=409, detail=f"Chromecast media command failed: {exc}") from exc


async def _send_chromecast_receiver_command(target: CastTarget, command: str, payload: dict) -> None:
    receiver_payload = _chromecast_receiver_control_payload(command.lower(), payload)
    try:
        await asyncio.to_thread(_send_chromecast_receiver_payload, target, receiver_payload)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=409, detail=f"Chromecast receiver command failed: {exc}") from exc


async def _send_chromecast_command(target: CastTarget, command: str, payload: dict) -> None:
    command_key = command.lower()
    if command_key in {"play", "queue_load", "play_queue", "queue", "pause", "resume", "playback_resume", "stop", "seek"}:
        await _send_chromecast_media_command(target, command_key, payload)
        return
    if command_key in {"volume", "set_volume", "mute", "unmute", "set_mute"}:
        await _send_chromecast_receiver_command(target, command_key, payload)
        return

    base_url = _chromecast_base_url(target)
    async with httpx.AsyncClient(timeout=5.0) as client:
        if command_key in {"launch", "launch_app", "start"}:
            app_id = _chromecast_app_id(payload)
            parameters = payload.get("parameters")
            response = await client.post(
                f"{base_url}/apps/{app_id}",
                data=parameters if isinstance(parameters, dict) else None,
            )
        elif command_key in {"stop", "stop_app"}:
            app_id = _chromecast_app_id(payload)
            response = await client.delete(f"{base_url}/apps/{app_id}/run")
        else:
            raise HTTPException(status_code=422, detail="Unsupported Chromecast command")

    if response.status_code >= 400:
        raise HTTPException(
            status_code=409,
            detail=f"Chromecast command failed with status {response.status_code}",
        )


def _flatten_chromecast_status(value, *, prefix: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        flattened: dict[str, str] = {}
        for key, nested_value in value.items():
            nested_key = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(
                _flatten_chromecast_status(nested_value, prefix=nested_key)
            )
        return flattened
    if isinstance(value, list):
        flattened: dict[str, str] = {}
        for index, item in enumerate(value):
            if item is None:
                continue
            nested_key = f"{prefix}.{index}" if prefix else str(index)
            flattened.update(_flatten_chromecast_status(item, prefix=nested_key))
        return flattened
    if value is None:
        return {}
    return {prefix: str(value)}


async def _get_chromecast_status(target: CastTarget) -> CastTargetStatus:
    base_url = _chromecast_base_url(target)
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{base_url}/setup/eureka_info",
            params={
                "params": ",".join(
                    [
                        "name",
                        "ssdp_udn",
                        "version",
                        "build_version",
                        "cast_build_revision",
                        "device_info",
                    ]
                )
            },
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=409,
            detail=f"Chromecast status failed with status {response.status_code}",
        )
    try:
        raw_json = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Invalid Chromecast status response") from exc
    raw = _flatten_chromecast_status(raw_json)
    receiver_payload = await _get_chromecast_receiver_status_payload_async(target)
    if receiver_payload:
        raw.update(
            {
                f"receiver.{key}": value
                for key, value in _flatten_chromecast_status(receiver_payload).items()
            }
        )
    media_payload = await _get_chromecast_media_status_payload_async(target)
    media_status = _chromecast_status_from_media_payload(
        target,
        media_payload,
        eureka_raw=raw,
    )
    if media_status:
        return media_status
    return CastTargetStatus(
        target_id=target.id,
        protocol=target.protocol,
        transport_state="AVAILABLE",
        transport_status="OK",
        raw=raw,
    )


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
