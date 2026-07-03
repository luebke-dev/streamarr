"""Grouped playback query dependencies."""

from uuid import UUID

from fastapi import Query


class PlaybackInfoQuery:
    def __init__(
        self,
        device_guid: UUID | None = Query(
            None,
            description="Registered device whose playback capabilities should be used",
        ),
        supported_video_codecs: str | None = Query(
            None, description="Comma-separated client video codecs"
        ),
        supported_audio_codecs: str | None = Query(
            None, description="Comma-separated client audio codecs"
        ),
        supported_containers: str | None = Query(
            None, description="Comma-separated client media containers"
        ),
        client_max_resolution: str | None = Query(
            None, description="Maximum resolution the client can handle"
        ),
        client_max_bitrate: int | None = Query(
            None,
            ge=1,
            description="Maximum source bitrate the client can handle in bits per second",
        ),
        profile_id: str | None = Query(
            None,
            description="Playback profile id, such as browser, chromecast, dlna_generic, or a custom profile",
        ),
        video_codec: str = Query("h264", description="Preferred transcode video codec"),
        audio_codec: str = Query("aac", description="Preferred transcode audio codec"),
        resolution: str | None = Query(
            None, description="Preferred transcode resolution"
        ),
        media_source_id: UUID | None = Query(
            None, description="Specific media source/file GUID to select"
        ),
    ) -> None:
        self.device_guid = device_guid
        self.supported_video_codecs = supported_video_codecs
        self.supported_audio_codecs = supported_audio_codecs
        self.supported_containers = supported_containers
        self.client_max_resolution = client_max_resolution
        self.client_max_bitrate = client_max_bitrate
        self.profile_id = profile_id
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        self.resolution = resolution
        self.media_source_id = media_source_id


class PlayMediaQuery:
    def __init__(
        self,
        video_codec: str = Query(
            "h264", description="Video codec: h264, h265, vp9, copy"
        ),
        audio_codec: str = Query(
            "aac", description="Audio codec: aac, opus, mp3, copy"
        ),
        video_bitrate: str | None = Query(
            None,
            description="Video bitrate (e.g., '2000k', '5000k'). None for CRF mode",
        ),
        audio_bitrate: str = Query(
            "128k", description="Audio bitrate (e.g., '128k', '192k', '320k')"
        ),
        start_position: float | None = Query(
            None, description="Start position in seconds for seek transcoding"
        ),
        resolution: str | None = Query(
            None,
            description="Target resolution (e.g., '1920x1080', '1280x720', '854x480')",
        ),
        supported_video_codecs: str | None = Query(
            None,
            description="Comma-separated list of video codecs the client supports (e.g., 'h264,h265,vp9')",
        ),
        supported_audio_codecs: str | None = Query(
            None,
            description="Comma-separated list of audio codecs the client supports (e.g., 'aac,opus,mp3')",
        ),
        supported_containers: str | None = Query(
            None,
            description="Comma-separated list of media containers the client supports (e.g., 'mp4,webm')",
        ),
        client_max_resolution: str | None = Query(
            None,
            description="Maximum resolution the client can handle (e.g., '4k', '1080p', '720p')",
        ),
        client_max_bitrate: int | None = Query(
            None,
            ge=1,
            description="Maximum source bitrate the client can handle in bits per second",
        ),
        device_guid: UUID | None = Query(
            None,
            description="Registered device whose playback capabilities should be used",
        ),
        profile_id: str | None = Query(
            None,
            description="Playback profile id, such as browser, chromecast, dlna_generic, or a custom profile",
        ),
        media_source_id: UUID | None = Query(
            None, description="Specific media source/file GUID to play"
        ),
        audio_track: int | None = Query(
            None,
            ge=0,
            description="Audio stream index (0-based among audio streams) to use. Overrides automatic language-based selection.",
        ),
        requested_subtitle_stream_index: int | None = Query(
            None,
            alias="subtitle_stream_index",
            ge=0,
            description="Subtitle stream index to use. Overrides automatic language-based selection.",
        ),
    ) -> None:
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        self.video_bitrate = video_bitrate
        self.audio_bitrate = audio_bitrate
        self.start_position = start_position
        self.resolution = resolution
        self.supported_video_codecs = supported_video_codecs
        self.supported_audio_codecs = supported_audio_codecs
        self.supported_containers = supported_containers
        self.client_max_resolution = client_max_resolution
        self.client_max_bitrate = client_max_bitrate
        self.device_guid = device_guid
        self.profile_id = profile_id
        self.media_source_id = media_source_id
        self.audio_track = audio_track
        self.requested_subtitle_stream_index = requested_subtitle_stream_index

    def impl_kwargs(self) -> dict:
        return {
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "video_bitrate": self.video_bitrate,
            "audio_bitrate": self.audio_bitrate,
            "start_position": self.start_position,
            "resolution": self.resolution,
            "supported_video_codecs": self.supported_video_codecs,
            "supported_audio_codecs": self.supported_audio_codecs,
            "supported_containers": self.supported_containers,
            "client_max_resolution": self.client_max_resolution,
            "client_max_bitrate": self.client_max_bitrate,
            "device_guid": self.device_guid,
            "profile_id": self.profile_id,
            "media_source_id": self.media_source_id,
            "audio_track": self.audio_track,
            "requested_subtitle_stream_index": (
                self.requested_subtitle_stream_index
            ),
        }
