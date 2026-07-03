"""Device schemas for API request/response validation"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from pyrate.schemas.base import BaseSchema


class DeviceBase(BaseSchema):
    """Base device schema"""

    device_id: str
    name: str | None = None
    browser: str | None = None
    platform: str | None = None
    language: str | None = None


class DeviceCreate(BaseModel):
    """Schema for device creation (internal use)"""

    device_id: str
    device_info: dict | None = None


class DeviceUpdate(BaseModel):
    """Schema for updating device properties"""

    name: str | None = None
    is_trusted: bool | None = None


class DeviceRead(DeviceBase):
    """Schema for reading device data"""

    guid: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    last_activity: datetime
    last_ip_address: str | None = None
    user_agent: str | None = None
    device_info: dict | None = None
    is_active: bool
    is_trusted: bool

    # Indicates whether this device currently has an active WebSocket connection
    is_ws_connected: bool = False

    # Playback status fields
    is_playing: bool = False
    current_media_type: str | None = None
    current_media_guid: uuid.UUID | None = None
    current_media_title: str | None = None
    current_playback_position: int = 0
    current_playback_duration: int = 0
    playback_updated_at: datetime | None = None


class DeviceReadWithUser(DeviceRead):
    """Device with user information"""

    user_email: str | None = None
    user_name: str | None = None


class DeviceListResponse(BaseModel):
    """Response for device list endpoints"""

    items: list[DeviceRead]
    total: int
    page: int
    page_size: int


class DeviceAdminListResponse(BaseModel):
    """Response for admin device list with user info"""

    items: list[DeviceReadWithUser]
    total: int
    page: int
    page_size: int


RemoteControlCommand = Literal[
    "play",
    "pause",
    "resume",
    "stop",
    "seek",
    "volume",
    "mute",
    "next",
    "previous",
    "skip_forward",
    "skip_backward",
    "play_media",
    "play_command",
    "play_queue",
    "message",
    "browse",
]

DeviceSessionPlayCommand = Literal[
    "play_now",
    "play_next",
    "play_last",
    "play_instant_mix",
    "play_shuffle",
]


class DeviceCommandCreate(BaseModel):
    """Remote-control command to send to a connected device."""

    command: RemoteControlCommand
    payload: dict[str, Any] = Field(default_factory=dict)
    from_device_id: str | None = Field(default=None, max_length=255)


class DeviceSessionMessageCreate(BaseModel):
    """Display message to send to a connected device session."""

    title: str | None = Field(default=None, max_length=100)
    text: str = Field(min_length=1, max_length=500)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    from_device_id: str | None = Field(default=None, max_length=255)


class DeviceSessionPlayMediaCreate(BaseModel):
    """Media playback request for a connected device session."""

    media_guid: uuid.UUID
    media_type: str | None = Field(default=None, max_length=50)
    media_title: str | None = Field(default=None, max_length=200)
    file_guid: uuid.UUID | None = None
    from_device_id: str | None = Field(default=None, max_length=255)


class DeviceSessionPlayQueueItem(BaseModel):
    """One item in a remote play queue command."""

    media_guid: uuid.UUID
    media_type: str | None = Field(default=None, max_length=50)
    media_title: str | None = Field(default=None, max_length=200)
    file_guid: uuid.UUID | None = None


class DeviceSessionPlayQueueCreate(BaseModel):
    """Ordered playback queue request for a connected device session."""

    items: list[DeviceSessionPlayQueueItem] = Field(min_length=1, max_length=500)
    start_index: int = Field(default=0, ge=0)
    start_position_seconds: int | None = Field(default=None, ge=0)
    from_device_id: str | None = Field(default=None, max_length=255)


class DeviceSessionPlayCommandCreate(BaseModel):
    """Compatible play instruction for a connected device session."""

    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    play_command: DeviceSessionPlayCommand = "play_now"
    start_position_seconds: int | None = Field(default=None, ge=0)
    start_position_ticks: int | None = Field(default=None, ge=0)
    media_source_id: str | None = Field(default=None, max_length=255)
    audio_stream_index: int | None = Field(default=None, ge=0)
    subtitle_stream_index: int | None = Field(default=None, ge=0)
    start_index: int | None = Field(default=None, ge=0)
    from_device_id: str | None = Field(default=None, max_length=255)


class DeviceCommandResponse(BaseModel):
    """Remote-control command delivery result."""

    target_device_id: str
    command: RemoteControlCommand
    status: Literal["sent"]
    timestamp: str


class DeviceCommandHistoryResponse(BaseModel):
    """Recent remote-control command history for a device."""

    items: list["ActivityLogRead"]
    total: int
    page: int
    per_page: int
    total_pages: int


class DeviceSessionUserAdd(BaseModel):
    """User to attach to a device session."""

    user_guid: uuid.UUID


class DeviceSessionUserRead(BaseModel):
    """User attached to a device session."""

    guid: uuid.UUID
    email: str
    name: str


class DeviceSessionUsersResponse(BaseModel):
    """Users explicitly attached to a device session."""

    items: list[DeviceSessionUserRead]
    total: int


class DeviceActiveSessionRead(BaseModel):
    """Live WebSocket-backed client session summary."""

    user_id: uuid.UUID
    user_email: str | None = None
    user_name: str | None = None
    device_guid: uuid.UUID | None = None
    device_id: str
    device_name: str | None = None
    browser: str | None = None
    platform: str | None = None
    connection_count: int
    subscription_count: int
    connected_at: datetime
    last_seen_at: datetime
    playback_state: Literal["idle", "playing", "paused"] = "idle"
    is_playing: bool = False
    current_media_type: str | None = None
    current_media_guid: uuid.UUID | None = None
    current_media_title: str | None = None
    current_playback_position: int = 0
    current_playback_duration: int = 0
    progress_percentage: float | None = None


class DeviceActiveSessionsResponse(BaseModel):
    """Live client sessions."""

    items: list[DeviceActiveSessionRead]
    total: int


class DeviceNowPlayingRead(BaseModel):
    """Normalized now-playing state for a device session."""

    media_guid: uuid.UUID | None = None
    media_type: str | None = None
    media_title: str | None = None
    position_seconds: int = 0
    duration_seconds: int = 0
    is_playing: bool = False
    playback_state: Literal["idle", "playing", "paused"] = "idle"
    progress_percentage: float | None = None
    updated_at: datetime | None = None


class DeviceSessionQueueState(BaseModel):
    """Queue state last advertised or commanded for a device session."""

    items: list[dict[str, Any]] = []
    start_index: int = 0
    current_index: int | None = None
    repeat_mode: str | None = None
    shuffle: bool | None = None
    updated_at: datetime | None = None


class DeviceSessionContractResponse(BaseModel):
    """Pyrate-native session contract for connected and recently active clients."""

    device: DeviceRead
    active_session: DeviceActiveSessionRead | None = None
    capabilities: "DeviceCapabilitiesResponse"
    now_playing: DeviceNowPlayingRead | None = None
    queue_state: DeviceSessionQueueState = Field(
        default_factory=DeviceSessionQueueState
    )
    recent_commands: list["ActivityLogRead"] = []


OfflineItemStatus = Literal[
    "queued",
    "downloading",
    "ready",
    "failed",
    "removed",
]


class DeviceOfflineItemUpdate(BaseModel):
    """Offline sync state for one media item on a device."""

    media_guid: uuid.UUID
    file_guid: uuid.UUID | None = None
    status: OfflineItemStatus = "queued"
    progress: float = Field(default=0, ge=0, le=100)
    downloaded_bytes: int | None = Field(default=None, ge=0)
    total_bytes: int | None = Field(default=None, ge=0)
    error_message: str | None = Field(default=None, max_length=1000)
    downloaded_at: datetime | None = None
    expires_at: datetime | None = None


class DeviceOfflineSyncRequest(BaseModel):
    """Request offline availability for one or more media items on a device."""

    media_guids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    status: OfflineItemStatus = "queued"
    expires_at: datetime | None = None


class DeviceOfflineItemRead(DeviceOfflineItemUpdate):
    """Stored offline sync state with basic media display metadata."""

    media_title: str | None = None
    media_type: str | None = None
    updated_at: datetime


class DeviceOfflineItemsResponse(BaseModel):
    """Offline sync queue/state for a device."""

    items: list[DeviceOfflineItemRead]
    total: int


class DeviceOfflineManifestSubtitle(BaseModel):
    """Subtitle asset advertised in an offline manifest."""

    id: str
    language: str
    title: str | None = None
    format: str | None = None
    url: str | None = None
    content_url: str | None = None
    is_forced: bool = False
    is_default: bool = False


class DeviceOfflineManifestItem(BaseModel):
    """Concrete media/subtitle URLs for one offline item."""

    media_guid: uuid.UUID
    media_title: str | None = None
    media_type: str | None = None
    status: OfflineItemStatus
    file_guid: uuid.UUID | None = None
    file_name: str | None = None
    file_size: int | None = None
    duration: float | None = None
    download_url: str | None = None
    subtitles: list[DeviceOfflineManifestSubtitle] = []
    expires_at: datetime | None = None
    updated_at: datetime


class DeviceOfflineManifestResponse(BaseModel):
    """Offline sync manifest for a device."""

    device_guid: uuid.UUID
    device_id: str
    items: list[DeviceOfflineManifestItem]
    total: int


class DeviceCapabilitiesUpdate(BaseModel):
    """Capabilities advertised by a client device."""

    supported_commands: list[RemoteControlCommand] = []
    supported_video_codecs: list[str] = []
    supported_audio_codecs: list[str] = []
    supported_containers: list[str] = []
    profile_id: str | None = Field(default=None, max_length=50)
    max_resolution: str | None = Field(default=None, max_length=20)
    max_bitrate: int | None = Field(default=None, ge=1)
    supports_direct_play: bool = True
    supports_direct_stream: bool = True
    supports_transcoding: bool = True
    supports_media_control: bool = True
    supports_display_message: bool = False
    supports_play_queue: bool = False
    supports_volume_control: bool = False
    supports_remote_play_media: bool = False
    supports_browse: bool = False
    app_name: str | None = Field(default=None, max_length=100)
    app_version: str | None = Field(default=None, max_length=100)


class DeviceCapabilitiesResponse(DeviceCapabilitiesUpdate):
    device_guid: uuid.UUID
    device_id: str


from pyrate.schemas.activity_log import ActivityLogRead  # noqa: E402

DeviceCommandHistoryResponse.model_rebuild()
DeviceSessionContractResponse.model_rebuild()
