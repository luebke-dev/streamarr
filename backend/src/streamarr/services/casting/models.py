"""Domain models shared by cast protocol services and the cast router."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CastProtocol = Literal["streamarr", "chromecast", "dlna", "airplay"]


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


class CastDiscoveryTarget(CastTarget):
    discovered: bool = True
    discovery_source: Literal["manual", "active_session", "ssdp", "mdns"] = "manual"
    connection_count: int | None = None
    last_seen_at: str | None = None


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
