"""
Unified Streaming API

HLS (HTTP Live Streaming) endpoints for all media types.
Serves m3u8 playlists and .ts segments for video/audio playback.

Works with play tokens from /play API.
"""

import asyncio
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from pyrate.api.dependencies import DatabaseSession
from pyrate.services.computing import ComputingService
from pyrate.services.play_token import get_play_token_service
from pyrate.services.transcoding_session import get_transcoding_session_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Regex for valid segment filenames: {session_id}_{number}.ts
_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9_-]+_\d{3}\.ts$")
# Regex for valid session IDs (alphanumeric + hyphens, no glob wildcards).
# Length capped so a pathological value can't fuel an expensive glob.
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
# Regex for valid trickplay sprite filenames: sprite_NNN.webp
_SPRITE_RE = re.compile(r"^sprite_\d{3}\.webp$")
_PLAYLIST_STARTUP_WAIT_SECONDS = 12
_PLAYLIST_STARTUP_POLL_SECONDS = 0.25

# Filesystem roots that play tokens are allowed to point at. Paths outside
# these roots are rejected at the streaming sink even if a play token
# somehow minted them — defense in depth against LFI via buggy token code.
_ALLOWED_MEDIA_ROOTS = (
    Path("/library"),
    Path("/downloads"),
    Path("/cache"),
    Path("/temp"),
)


def _validate_session_id(session_id: str) -> None:
    """Reject session_id values that wouldn't safely compose filesystem paths."""
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format")


def _resolve_media_file(raw_path: str) -> Path:
    """Resolve a play-token file path and assert it lives under an allowed root.

    Raises HTTPException(404) when the path is missing or outside every
    permitted root — same status as a real 404 so we don't leak
    whether a bogus path was "close" to something valid.
    """
    candidate = Path(raw_path).resolve()
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="File not found")
    for root in _ALLOWED_MEDIA_ROOTS:
        try:
            root_resolved = root.resolve()
        except FileNotFoundError:
            continue
        if candidate.is_relative_to(root_resolved):
            return candidate
    logger.warning(
        "Refused to stream file outside allowed roots: %s (resolved=%s)",
        raw_path, candidate,
    )
    raise HTTPException(status_code=404, detail="File not found")


async def _verify_play_token(request: Request, session_id: str, token: str | None = None):
    """Extract and verify play token from query parameter or Authorization header.

    Returns the validated play token or raises HTTPException.
    """
    token_service = get_play_token_service()

    if not token:
        token = request.query_params.get("token", "")

    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=401, detail="No play token provided")

    play_token = await token_service.get_token(token)
    if not play_token:
        raise HTTPException(status_code=401, detail="Invalid or expired play token")

    if play_token.session_id != session_id:
        raise HTTPException(
            status_code=403, detail="Session ID does not match play token"
        )

    return play_token, token, token_service


# ==================== HLS Playlist ====================


@router.get("/{session_id}/playlist.m3u8")
async def get_playlist(session_id: str, request: Request, token: str | None = None):
    """
    Get HLS playlist for a streaming session.

    The playlist contains references to video segments (.ts files).
    This endpoint extends the play token TTL on each access.

    Works for all media types (movies, episodes, music, etc.)
    """
    _validate_session_id(session_id)
    play_token, raw_token, token_service = await _verify_play_token(
        request, session_id, token
    )

    # Extend token TTL on playlist access
    await token_service.extend_ttl(raw_token)

    # Update session last_accessed_at (throttled to avoid excessive Redis writes)
    session_service = get_transcoding_session_service()
    await session_service.update_session_access(session_id)

    # Serve playlist file
    playlist_path = Path(f"/temp/{session_id}.m3u8")

    if not playlist_path.exists():
        deadline = asyncio.get_running_loop().time() + _PLAYLIST_STARTUP_WAIT_SECONDS
        while not playlist_path.exists() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(_PLAYLIST_STARTUP_POLL_SECONDS)

    if not playlist_path.exists():
        logger.debug(
            "Playlist not found for session %s after %.1fs startup wait",
            session_id,
            _PLAYLIST_STARTUP_WAIT_SECONDS,
        )
        raise HTTPException(
            status_code=404,
            detail="Playlist not found. Transcoding may not have started yet.",
        )

    content = playlist_path.read_text()

    return Response(
        content=content,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "no-cache",
        },
    )


# ==================== Status Endpoint ====================


@router.get("/{session_id}/status")
async def get_stream_status(session_id: str, request: Request, db: DatabaseSession):
    """Get streaming session status."""
    _validate_session_id(session_id)
    import glob

    play_token, _raw_token, _token_service = await _verify_play_token(
        request, session_id
    )

    # Check playlist
    playlist_path = Path(f"/temp/{session_id}.m3u8")
    playlist_exists = playlist_path.exists()

    # Count segments
    segment_files = glob.glob(f"/temp/{session_id}_*.ts")
    segment_count = len(segment_files)

    # Check if transcoding container is running using ComputingService
    is_transcoding = False
    try:
        async with ComputingService(db) as service:
            tasks = await service.get_tasks_by_label("transcode.session_id", session_id)
            if tasks:
                task = tasks[0]
                is_transcoding = task.get("status") == "running"
    except Exception:
        logger.warning("Failed to check transcoding status for session %s", session_id)

    # Stream is ready when the playlist exists and at least one segment has been written
    is_ready = playlist_exists and segment_count > 0

    # Check trickplay sprite availability
    trickplay_dir = Path(f"/temp/{session_id}_trickplay")
    trickplay_files = list(trickplay_dir.glob("sprite_*.webp")) if trickplay_dir.exists() else []
    trickplay_count = len(trickplay_files)

    return {
        "session_id": session_id,
        "is_ready": is_ready,
        "playlist_ready": playlist_exists,
        "segment_count": segment_count,
        "is_transcoding": is_transcoding,
        "trickplay_ready": trickplay_count > 0,
        "trickplay_count": trickplay_count,
        "status": "transcoding"
        if is_transcoding
        else ("ready" if playlist_exists else "initializing"),
    }


# ==================== Position Availability Check ====================


@router.get("/{session_id}/check-position")
async def check_position_available(
    session_id: str,
    request: Request,
    position: float = Query(..., description="Absolute position in seconds to check"),
    start_position: float = Query(0, description="Transcode start position in seconds"),
    segment_duration: float = Query(6.0, description="Segment duration in seconds"),
    db: DatabaseSession = None,
):
    """
    Check if a specific position is available on the server (already transcoded).

    Returns whether the segment for the given position exists on disk,
    allowing the client to decide between a simple seek vs. starting a new transcode.
    """
    _validate_session_id(session_id)
    play_token, _raw_token, _token_service = await _verify_play_token(
        request, session_id
    )

    # Calculate which segment corresponds to this position
    relative_position = position - start_position
    if relative_position < 0:
        return {"available": False, "segment_index": -1, "reason": "before_start"}

    segment_index = int(relative_position / segment_duration)
    segment_file = Path(f"/temp/{session_id}_{segment_index:03d}.ts")

    if segment_file.exists():
        return {
            "available": True,
            "segment_index": segment_index,
            "stream_position": relative_position,
        }

    # Check if the transcode is still running (segment might appear soon)
    is_transcoding = False
    try:
        if db:
            async with ComputingService(db) as service:
                tasks = await service.get_tasks_by_label(
                    "transcode.session_id", session_id
                )
                if tasks:
                    task = tasks[0]
                    is_transcoding = task.get("status") == "running"
    except Exception:
        logger.debug("Could not check transcoding status for session %s", session_id)

    return {
        "available": False,
        "segment_index": segment_index,
        "is_transcoding": is_transcoding,
        "reason": "not_transcoded",
    }


# ==================== Direct File Streaming ====================


def _media_type_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    media_types = {
        ".aac": "audio/aac",
        ".azw": "application/vnd.amazon.ebook",
        ".azw3": "application/vnd.amazon.ebook",
        ".cbr": "application/vnd.comicbook-rar",
        ".cbz": "application/vnd.comicbook+zip",
        ".epub": "application/epub+zip",
        ".fb2": "application/xml",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".m4v": "video/mp4",
        ".mkv": "video/x-matroska",
        ".mobi": "application/x-mobipocket-ebook",
        ".mov": "video/quicktime",
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".ogg": "audio/ogg",
        ".ogv": "video/ogg",
        ".opus": "audio/opus",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".wav": "audio/wav",
        ".webm": "video/webm",
        ".wma": "audio/x-ms-wma",
    }
    return media_types.get(ext, "application/octet-stream")


async def _resolve_token_file(request: Request, token: str | None = None) -> tuple[Path, str, object]:
    token_service = get_play_token_service()

    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=401, detail="No play token provided")

    play_token = await token_service.get_token(token)
    if not play_token:
        raise HTTPException(status_code=401, detail="Invalid or expired play token")

    file_path = play_token.file_path
    if not file_path:
        raise HTTPException(status_code=404, detail="No file path associated with token")

    resolved_path = _resolve_media_file(file_path)
    await token_service.extend_ttl(token)
    return resolved_path, token, play_token


@router.get("/file")
async def stream_direct_file(request: Request, token: str | None = None):
    """Serve any play-token-backed media file directly with range support."""
    media_path, _raw_token, _play_token = await _resolve_token_file(request, token)

    return FileResponse(
        media_path,
        media_type=_media_type_for_path(media_path),
        filename=media_path.name,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


# ==================== Direct Audio Streaming ====================


@router.get("/audio/file")
async def stream_audio_file(request: Request, token: str | None = None):
    """
    Stream an audio file directly without transcoding.

    Used for audio-only content (music) where HLS transcoding is unnecessary.
    The browser's native <audio> element can play common formats (OGG, MP3, FLAC)
    directly. FileResponse supports HTTP Range requests for seeking.
    """
    audio_path, _raw_token, _play_token = await _resolve_token_file(request, token)

    return FileResponse(
        audio_path,
        media_type=_media_type_for_path(audio_path),
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/book/file")
async def stream_book_file(request: Request, token: str | None = None):
    """Serve a book file (EPUB, PDF, etc.) directly for in-browser reading."""
    book_path, _raw_token, _play_token = await _resolve_token_file(request, token)

    return FileResponse(
        book_path,
        media_type=_media_type_for_path(book_path),
        filename=book_path.name,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


# ==================== Trickplay Sprites ====================


@router.get("/{session_id}/trickplay")
async def get_trickplay_manifest(
    session_id: str,
    request: Request,
    token: str | None = None,
    interval_seconds: int = Query(
        10,
        ge=1,
        le=600,
        description="Seconds represented by each thumbnail cell",
    ),
):
    """List generated trickplay sprite sheets and their timeline ranges."""
    _validate_session_id(session_id)
    _play_token, raw_token, _token_service = await _verify_play_token(
        request, session_id, token
    )

    trickplay_dir = Path(f"/temp/{session_id}_trickplay")
    sprite_paths = []
    if trickplay_dir.exists():
        sprite_paths = sorted(
            path
            for path in trickplay_dir.glob("sprite_*.webp")
            if _SPRITE_RE.match(path.name)
        )

    columns = 10
    rows = 10
    thumbnails_per_sprite = columns * rows
    sprite_duration = thumbnails_per_sprite * interval_seconds
    sprites = []
    for index, sprite_path in enumerate(sprite_paths):
        start_seconds = index * sprite_duration
        url = f"/api/stream/{session_id}/trickplay/{sprite_path.name}"
        if raw_token:
            url = f"{url}?token={raw_token}"
        try:
            size = sprite_path.stat().st_size
        except OSError:
            size = None
        sprites.append(
            {
                "index": index,
                "file_name": sprite_path.name,
                "url": url,
                "start_seconds": start_seconds,
                "end_seconds": start_seconds + sprite_duration,
                "thumbnail_count": thumbnails_per_sprite,
                "size": size,
            }
        )

    return {
        "session_id": session_id,
        "ready": bool(sprites),
        "interval_seconds": interval_seconds,
        "columns": columns,
        "rows": rows,
        "thumbnail_width": 160,
        "thumbnail_height": 90,
        "sprite_count": len(sprites),
        "sprites": sprites,
    }


@router.get("/{session_id}/trickplay/{filename}")
async def get_trickplay_sprite(
    session_id: str, filename: str, request: Request, token: str | None = None
):
    """
    Get a trickplay sprite sheet image for video thumbnail previews.

    Sprite sheets are generated on-demand alongside the transcode.
    Each sheet contains a 10x10 grid of thumbnails (one every 10 seconds).
    Returns 404 if the sprite is not yet generated.
    """
    _validate_session_id(session_id)
    play_token, raw_token, token_service = await _verify_play_token(
        request, session_id, token
    )

    # Security: validate sprite filename
    if not _SPRITE_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid sprite filename")

    sprite_path = Path(f"/temp/{session_id}_trickplay/{filename}")

    if not sprite_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Sprite not yet generated",
        )

    return FileResponse(
        sprite_path,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000",
        },
    )


# ==================== HLS Segments ====================
# NOTE: This catch-all route MUST be declared after /status and /check-position,
# otherwise Starlette's declaration-order matching would intercept those
# specific paths and return 400 ("Invalid segment file name").


@router.get("/{session_id}/{segment_file}")
async def get_segment(
    session_id: str, segment_file: str, request: Request, token: str | None = None
):
    """
    Get HLS segment file (.ts) for a streaming session.

    Segments contain actual video/audio data.
    This endpoint extends the play token TTL on each access.

    Works for all media types.
    """
    _validate_session_id(session_id)
    play_token, raw_token, token_service = await _verify_play_token(
        request, session_id, token
    )

    # Security: validate segment file name (prevent path traversal)
    if not _SEGMENT_RE.match(segment_file):
        raise HTTPException(status_code=400, detail="Invalid segment file name")

    # Extend token TTL on segment access
    await token_service.extend_ttl(raw_token)

    # Update session last_accessed_at (throttled to avoid excessive Redis writes)
    session_service = get_transcoding_session_service()
    await session_service.update_session_access(session_id)

    # Serve segment file
    segment_path = Path(f"/temp/{segment_file}")

    if not segment_path.exists():
        logger.warning("Segment not found: %s", segment_file)
        raise HTTPException(
            status_code=404, detail="Segment not found. It may not be transcoded yet."
        )

    return FileResponse(
        segment_path,
        media_type="video/MP2T",
        headers={
            "Cache-Control": "public, max-age=31536000",  # Segments are immutable
        },
    )


# ==================== Stop Streaming ====================


@router.delete("/{session_id}")
async def stop_stream(
    session_id: str,
    request: Request,
    db: DatabaseSession,
    delete_library_file: bool = Query(
        True,
        description="Whether to delete the source media file from disk and database",
    ),
):
    """
    Stop a streaming session and clean up all associated files.

    This endpoint:
    1. Stops the transcoding container
    2. Deletes temporary transcoding files (.ts, .m3u8)
    3. Optionally deletes the source media file from disk and database
    4. Invalidates the play token
    """
    from pyrate.services.media import cleanup_stream_on_stop

    play_token, raw_token, token_service = await _verify_play_token(
        request, session_id
    )

    # Get session info before cleanup (for library file info)
    session_service = get_transcoding_session_service()
    session = await session_service.get_session(session_id)

    content_id = None
    input_path = None
    if session:
        content_id = session.content_id
        input_path = session.input_path
    elif play_token:
        content_id = str(play_token.content_id) if play_token.content_id else None
        input_path = play_token.file_path

    # Stop transcoding container using ComputingService
    container_stopped = False
    try:
        async with ComputingService(db) as service:
            tasks = await service.get_tasks_by_label("transcode.session_id", session_id)
            if tasks:
                task = tasks[0]
                task_id = task.get("task_id") or task.get("container_id")
                if task_id:
                    await service.terminate_task(task_id)
                    container_stopped = True
                    logger.info(
                        "Stopped transcoding container for session: %s", session_id
                    )

            # Also stop trickplay container if running
            trickplay_tasks = await service.get_tasks_by_label(
                "trickplay.session_id", session_id
            )
            for tp_task in trickplay_tasks:
                tp_id = tp_task.get("task_id") or tp_task.get("container_id")
                if tp_id:
                    await service.terminate_task(tp_id)
                    logger.info("Stopped trickplay container for session: %s", session_id)
    except Exception:
        logger.warning("Failed to stop container for session %s", session_id)

    # Perform full cleanup (temp files + optionally library file)
    cleanup_result = await cleanup_stream_on_stop(
        db=db,
        session_id=session_id,
        content_id=content_id,
        input_path=input_path,
        delete_library_file=delete_library_file,
    )

    # Remove session from Redis so it stops counting toward concurrency limits.
    if session:
        await session_service.delete_session(session_id)

    # Invalidate play token
    await token_service.delete_token(raw_token)

    return {
        "message": "Streaming session stopped and cleaned up",
        "session_id": session_id,
        "container_stopped": container_stopped,
        "cleanup": cleanup_result,
    }
