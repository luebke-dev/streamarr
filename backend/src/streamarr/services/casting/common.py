"""Shared low-level helpers used by more than one cast protocol service."""

from __future__ import annotations

from urllib.parse import urlsplit

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


def _airplay_seconds(value) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return _seconds_to_dlna_time(int(value))


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
