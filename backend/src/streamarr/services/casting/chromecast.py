"""Chromecast (DIAL/Eureka + Cast V2 protobuf) control and status."""

from __future__ import annotations

import asyncio
import json
import socket
import ssl
import struct

import httpx
from fastapi import HTTPException

from .common import _airplay_seconds, _cast_mime_type
from .models import CastTarget, CastTargetStatus


def _chromecast_base_url(target: CastTarget) -> str:
    if target.control_url:
        return target.control_url.rstrip("/")
    if not target.host:
        raise HTTPException(status_code=422, detail="Chromecast target host is required")
    port = target.port or 8008
    return f"http://{target.host}:{port}"


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
    title = payload.get("title") or payload.get("name") or metadata.get("title") or "streamarr media"
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
