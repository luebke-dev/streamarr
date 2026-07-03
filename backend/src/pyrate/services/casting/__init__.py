"""Cast protocol services: discovery and control for DLNA, Chromecast, AirPlay.

This package holds the protocol/discovery implementations that back the cast
router (``pyrate.api.v1.cast``). The router only owns HTTP handlers and Pydantic
request/response schemas; everything protocol-specific lives here.
"""

from __future__ import annotations

from .airplay import (
    _airplay_base_url,
    _airplay_play_payload,
    _get_airplay_status,
    _send_airplay_command,
)
from .chromecast import (
    _cast_message,
    _chromecast_base_url,
    _chromecast_load_payload,
    _chromecast_media_control_payload,
    _chromecast_queue_load_payload,
    _chromecast_receiver_control_payload,
    _get_chromecast_media_status_payload_async,
    _get_chromecast_receiver_status_payload_async,
    _get_chromecast_status,
    _parse_cast_message,
    _send_chromecast_cast_v2_payload,
    _send_chromecast_command,
    _send_chromecast_media_command,
    _send_chromecast_receiver_command,
)
from .common import _CONTAINER_MIME_TYPES, _cast_mime_type
from .discovery import _discover_dlna_targets, _discover_mdns_targets
from .dlna import (
    _dlna_metadata,
    _dlna_seek_target,
    _get_dlna_status,
    _send_dlna_command,
)
from .models import (
    CastDiscoveryTarget,
    CastProtocol,
    CastTarget,
    CastTargetStatus,
)

__all__ = [
    "_CONTAINER_MIME_TYPES",
    "CastDiscoveryTarget",
    "CastProtocol",
    "CastTarget",
    "CastTargetStatus",
    "_airplay_base_url",
    "_airplay_play_payload",
    "_cast_message",
    "_cast_mime_type",
    "_chromecast_base_url",
    "_chromecast_load_payload",
    "_chromecast_media_control_payload",
    "_chromecast_queue_load_payload",
    "_chromecast_receiver_control_payload",
    "_discover_dlna_targets",
    "_discover_mdns_targets",
    "_dlna_metadata",
    "_dlna_seek_target",
    "_get_airplay_status",
    "_get_chromecast_media_status_payload_async",
    "_get_chromecast_receiver_status_payload_async",
    "_get_chromecast_status",
    "_get_dlna_status",
    "_parse_cast_message",
    "_send_airplay_command",
    "_send_chromecast_cast_v2_payload",
    "_send_chromecast_command",
    "_send_chromecast_media_command",
    "_send_chromecast_receiver_command",
    "_send_dlna_command",
]
