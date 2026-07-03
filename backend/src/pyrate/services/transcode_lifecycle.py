"""Transcode/probe container lifecycle helpers.

This module owns the *lifecycle* side of playback: launching ffmpeg/ffprobe
compute tasks (transcode, trickplay), inspecting active transcode containers
and probing media files. It is deliberately separate from the playback
*decision* layer (:mod:`pyrate.services.playback_decision`) and the play-action
orchestration in :mod:`pyrate.services.play`.

For backwards compatibility the public functions here are re-exported from
:mod:`pyrate.services.play`.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.services.computing import ComputingService

logger = logging.getLogger(__name__)


async def _get_base_library_path(db: AsyncSession) -> str:
    """Get the base library path from settings or use default."""
    from pyrate.services.settings import SettingsService

    settings_service = SettingsService(db)
    # Try to get from settings, fallback to environment default
    base_path = await settings_service.get("library.base_path", "/data")
    return base_path


async def probe_video_full(file_path: str, db: AsyncSession) -> dict | None:
    """
    Probe video file and extract complete stream information using ffprobe.
    Uses ComputingService to run ffprobe via Docker or Kubernetes provider.
    Returns a dict with all streams (video, audio, subtitle) including language metadata.
    This data is stored in the database for stream selection during playback.

    Args:
        file_path: Path to the video file to probe
        db: Database session (required)

    Returns:
        Dictionary with video, audio, and subtitle stream information
    """
    return await _probe_video_with_computing_service(file_path, db)


async def _probe_video_with_computing_service(
    file_path: str, db: AsyncSession
) -> dict | None:
    """Probe video using ComputingService (delegates to the shared helper)."""
    try:
        logger.info("Probing video file with ComputingService: %s", file_path)
        async with ComputingService(db) as computing_service:
            probe_data = await computing_service.probe_media_file(file_path)
        if not probe_data:
            return None
        return _structure_probe_data(probe_data, file_path)
    except Exception as e:
        logger.error("Error probing video %s with ComputingService: %s", file_path, e)
        return None


def _structure_probe_data(probe_data: dict, file_path: str) -> dict:
    """Structure FFprobe output data for easier access.

    Delegates to the canonical :func:`pyrate.libraries.base.structure_probe_data`
    utility and logs the result.
    """
    from pyrate.libraries.base import structure_probe_data

    structured_data = structure_probe_data(probe_data)

    logger.info(
        "Probed %s: %s video, %s audio, %s subtitle streams",
        file_path, len(structured_data['video_streams']), len(structured_data['audio_streams']), len(structured_data['subtitle_streams']),
    )

    return structured_data


async def get_active_transcode_container(
    content_id: str,
    db: AsyncSession | None = None,
) -> str | None:
    """
    Check if there's an active FFmpeg compute task transcoding for this content.
    Returns the Docker container ID when available, otherwise the provider task ID.
    """
    try:
        async with ComputingService(db) as computing_service:
            tasks = await computing_service.list_tasks(
                labels={"content_id": str(content_id)}
            )
        for task in tasks:
            if task.get("status") not in {"pending", "running"}:
                continue
            return task.get("container_id") or task.get("task_id")
        return None
    except Exception as e:
        logging.error("Error checking for active transcode task: %s", e)
        return None


async def probe_video_metadata(file_path: str, db: AsyncSession | None = None) -> dict:
    """
    Probe video file and extract metadata using ffprobe via Docker container.
    Returns a dict with duration, size, width, height, codec, and bitrate.

    Args:
        file_path: Path to the video file to probe
        db: Optional database session. If provided, uses ComputingService.
    """
    metadata = {
        "duration": None,
        "file_size": None,
        "width": None,
        "height": None,
        "codec": None,
        "bitrate": None,
    }

    try:
        # Use probe_video_full which uses ComputingService if db is provided
        probe_data = await probe_video_full(file_path, db=db)

        if not probe_data:
            return metadata

        # Extract format info
        fmt = probe_data.get("format", {})
        if fmt:
            duration = fmt.get("duration")
            metadata["duration"] = float(duration) if duration else None

            size = fmt.get("size")
            metadata["file_size"] = int(size) if size else None

            bit_rate = fmt.get("bit_rate")
            metadata["bitrate"] = int(int(bit_rate) / 1000) if bit_rate else None

        # Extract video stream info
        video_streams = probe_data.get("video_streams", [])
        if video_streams:
            video = video_streams[0]
            metadata["width"] = video.get("width")
            metadata["height"] = video.get("height")
            metadata["codec"] = video.get("codec_name")

        return metadata

    except Exception as e:
        logger.error("Error probing video metadata: %s", e)
        return metadata


async def start_trickplay_container(
    input_path: str,
    session_id: str,
) -> str | None:
    """
    Start trickplay sprite generation for a streaming session.

    Launches a Docker container that generates sprite sheet thumbnails
    from the source video. Runs as fire-and-forget — failures are logged
    but don't affect playback.

    Uses its own DB session to avoid concurrent session conflicts when
    called via asyncio.create_task.

    Args:
        input_path: Path to the source video file
        session_id: The streaming session ID

    Returns:
        Task ID or None if failed
    """
    try:
        from pyrate.database import sessionmanager

        async with sessionmanager.session() as db:
            base_path = await _get_base_library_path(db)

            async with ComputingService(db) as computing_service:
                return await computing_service.start_trickplay_generation(
                    input_path=input_path,
                    session_id=session_id,
                    library_path=base_path,
                )
    except Exception as e:
        logger.warning("Failed to start trickplay generation for session %s: %s", session_id, e)
        return None


async def start_transcode_container(
    db: AsyncSession,
    input_path: str,
    rel_output: str,
    segment_pattern: str,
    hls_time: int = 6,
    session_id: str | None = None,
    video_codec: str | None = "h264",
    audio_codec: str = "aac",
    video_bitrate: str | None = None,
    audio_bitrate: str = "128k",
    start_position: float | None = None,
    resolution: str | None = None,
    # Stream selection parameters
    audio_stream_index: int | None = None,
    subtitle_stream_index: int | None = None,
    burn_subtitles: bool = False,
    # Session tracking parameters
    user_guid: str | None = None,
    user_name: str | None = None,
    content_type: str = "episode",
    content_id: str | None = None,
    content_title: str | None = None,
    audio_only: bool = False,
) -> str:
    """
    Start a new FFmpeg transcoding session with customizable options.

    Automatically chooses between Docker and Kubernetes based on configuration
    and runtime environment.

    Args:
        db: Database session
        input_path: Path to the input video file
        rel_output: Path to the output playlist file
        segment_pattern: Pattern for segment filenames
        hls_time: Duration of each HLS segment in seconds
        session_id: Optional session ID for this transcode (defaults to UUID)
        video_codec: Video codec to use ('h264', 'h265', 'vp9', 'copy')
        audio_codec: Audio codec to use ('aac', 'opus', 'mp3', 'copy')
        video_bitrate: Target video bitrate (e.g., '2000k', '5000k', None for CRF mode)
        audio_bitrate: Target audio bitrate (e.g., '128k', '192k', '320k')
        start_position: Start position in seconds for seek transcoding
        resolution: Target resolution (e.g., '1920x1080', '1280x720', '854x480', None for original)
        audio_stream_index: Index of the audio stream to use (from probe_data)
        subtitle_stream_index: Index of the subtitle stream to burn (from probe_data)
        burn_subtitles: Whether to burn subtitles into the video
        user_guid: GUID of the user starting the transcode
        user_name: Username of the user starting the transcode
        content_type: Type of content ('movie', 'episode', 'music')
        content_id: GUID of the content being transcoded
        content_title: Title of the content being transcoded

    Returns:
        The transcoding session ID
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    logger.info("Input Path: %s", input_path)
    logger.info("Transcode Session ID: %s", session_id)
    logger.info(
        "Options: video=%s, audio=%s, vbr=%s, abr=%s, start=%s, res=%s",
        video_codec, audio_codec, video_bitrate, audio_bitrate, start_position, resolution,
    )
    logger.info(
        "Stream selection: audio_stream=%s, subtitle_stream=%s, burn_subtitles=%s",
        audio_stream_index, subtitle_stream_index, burn_subtitles,
    )

    # Use the computing service to start transcoding. Re-import locally so the
    # concrete provider class is resolved at call time (kept for parity with the
    # historical implementation / patch targets).
    from pyrate.services.computing import ComputingService

    # Get base library path from settings
    base_path = await _get_base_library_path(db)

    logger.info("Starting transcoding through computing service")

    # Use context manager to ensure proper cleanup
    async with ComputingService(db) as computing_service:
        return await computing_service.start_transcoding(
            input_path=input_path,
            rel_output=rel_output,
            segment_pattern=segment_pattern,
            hls_time=hls_time,
            session_id=session_id,
            video_codec=video_codec,
            audio_codec=audio_codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            start_position=start_position,
            resolution=resolution,
            audio_stream_index=audio_stream_index,
            subtitle_stream_index=subtitle_stream_index,
            burn_subtitles=burn_subtitles,
            user_guid=user_guid,
            user_name=user_name,
            content_type=content_type,
            content_id=content_id,
            content_title=content_title,
            library_path=base_path,
            audio_only=audio_only,
        )
