"""API endpoints for transcoding sessions management."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from pyrate.auth.dependencies import get_current_superuser, get_current_user
from pyrate.schemas.transcoding import (
    TranscodingSessionRead,
    TranscodingSessionsResponse,
)
from pyrate.services.transcoding_session import get_transcoding_session_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=TranscodingSessionsResponse)
async def list_sessions(
    active_only: bool = False,
    current_user=Depends(get_current_superuser),
):
    """
    List all transcoding sessions with live container status.

    Requires superuser privileges.
    """
    service = get_transcoding_session_service()
    return await service.get_sessions_with_status(active_only=active_only)


@router.get("/my", response_model=TranscodingSessionsResponse)
async def list_my_sessions(
    current_user=Depends(get_current_user),
):
    """
    List transcoding sessions for the current user.
    """
    service = get_transcoding_session_service()
    user_sessions = await service.get_user_sessions(str(current_user.guid))

    from pyrate.schemas.transcoding import TranscodingSessionRead

    session_reads = [TranscodingSessionRead.from_session(s) for s in user_sessions]
    active_count = sum(1 for s in user_sessions if s.is_active)

    return TranscodingSessionsResponse(
        sessions=session_reads,
        total=len(user_sessions),
        active_count=active_count,
    )


@router.get("/{session_id}", response_model=TranscodingSessionRead)
async def get_session(
    session_id: str,
    current_user=Depends(get_current_user),
):
    """
    Get a specific transcoding session.

    Users can only view their own sessions unless they are superusers.
    """
    service = get_transcoding_session_service()
    session = await service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check authorization - user can only see their own sessions unless superuser
    if not current_user.is_superuser and session.user_guid != str(current_user.guid):
        raise HTTPException(
            status_code=403, detail="Not authorized to view this session"
        )

    return TranscodingSessionRead.from_session(session)


@router.delete("/{session_id}")
async def terminate_session(
    session_id: str,
    current_user=Depends(get_current_user),
):
    """
    Terminate a transcoding session.

    This stops the transcoding container and removes the session.
    Users can terminate their own sessions, superusers can terminate any session.
    """
    service = get_transcoding_session_service()
    session = await service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check authorization - user can only terminate their own sessions unless superuser
    if not current_user.is_superuser and session.user_guid != str(current_user.guid):
        raise HTTPException(
            status_code=403, detail="Not authorized to terminate this session"
        )

    result = await service.terminate_session(session_id)
    logger.info("User %s terminated transcoding session %s", current_user.guid, session_id)

    return {
        "message": "Session terminated",
        **result,
    }


@router.delete("")
async def terminate_all_sessions(
    current_user=Depends(get_current_superuser),
):
    """
    Terminate all active transcoding sessions.

    Requires superuser privileges.
    """
    service = get_transcoding_session_service()
    sessions = await service.get_all_sessions(active_only=True)

    terminated_count = 0
    errors = []

    for session in sessions:
        try:
            await service.terminate_session(session.session_id)
            terminated_count += 1
        except Exception as e:
            errors.append({"session_id": session.session_id, "error": str(e)})

    logger.info("Admin %s terminated all sessions (%d terminated)", current_user.guid, terminated_count)

    return {
        "message": f"Terminated {terminated_count} sessions",
        "terminated_count": terminated_count,
        "errors": errors if errors else None,
    }


@router.get("/{session_id}/logs")
async def get_session_logs(
    session_id: str,
    tail_lines: int = 100,
    current_user=Depends(get_current_user),
):
    """
    Get logs from a transcoding session.

    For Kubernetes jobs, retrieves logs from the FFmpeg container.
    For Docker containers, retrieves logs from the Docker container.
    Users can only view logs for their own sessions unless they are superusers.
    """
    service = get_transcoding_session_service()
    session = await service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check authorization
    if not current_user.is_superuser and session.user_guid != str(current_user.guid):
        raise HTTPException(
            status_code=403, detail="Not authorized to view logs for this session"
        )

    logs = await service.get_session_logs(session, tail_lines=tail_lines)

    return {
        "session_id": session_id,
        "runtime_type": session.runtime_type,
        "logs": logs,
    }


@router.get("/{session_id}/status")
async def get_session_status(
    session_id: str,
    current_user=Depends(get_current_user),
):
    """
    Get detailed status of a transcoding session.

    For Kubernetes jobs, returns job status including completion state.
    For Docker containers, returns container status.
    """
    service = get_transcoding_session_service()
    session = await service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check authorization
    if not current_user.is_superuser and session.user_guid != str(current_user.guid):
        raise HTTPException(
            status_code=403, detail="Not authorized to view status for this session"
        )

    status = {
        "session_id": session_id,
        "runtime_type": session.runtime_type,
        "is_active": session.is_active,
    }
    status.update(await service.get_session_runtime_status(session))

    return status


@router.post("/cleanup")
async def cleanup_sessions(
    current_user=Depends(get_current_superuser),
):
    """
    Clean up orphaned temp files and stale sessions.

    This endpoint:
    1. Removes stale sessions from Redis (containers no longer running)
    2. Deletes orphaned temp files older than 2 hours

    Requires superuser privileges.
    """
    from pyrate.database import sessionmanager
    from pyrate.services.media import MediaService

    result = {
        "stale_sessions_cleaned": 0,
        "temp_cleanup": {},
    }

    # Clean up stale sessions
    service = get_transcoding_session_service()
    result["stale_sessions_cleaned"] = await service.cleanup_stale_sessions()

    # Clean up orphaned temp files
    async with sessionmanager.session() as db:
        cleanup_service = MediaService(db)
        result["temp_cleanup"] = await cleanup_service.cleanup_orphaned_temp_files(
            max_age_hours=2
        )

    return result
