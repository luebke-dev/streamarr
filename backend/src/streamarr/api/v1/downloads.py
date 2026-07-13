import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from streamarr.api.dependencies import CurrentSuperuser, DatabaseSession
from streamarr.services.download import DownloadService

router = APIRouter()


class DownloadResponse(BaseModel):
    """Enhanced download response with media details"""

    guid: str
    title: str
    display_title: str
    type: str
    status: str
    status_phase: str | None = None
    status_detail: str | None = None
    progress: float | None
    # Live download speed in bytes/sec (None when not downloading)
    speed_bps: int | None = None
    # Navigation info
    media_item_guid: str | None
    media_title: str | None
    # Episode-specific info
    show_title: str | None
    season_number: int | None
    episode_number: int | None
    # Downloader info
    downloader_name: str | None
    downloader_type: str | None
    # User who started the download
    user_guid: str | None
    started_by_name: str | None
    created_at: datetime | None
    # Error info for failed downloads
    error_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


@router.get("")
async def list_downloads(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    user_guid: uuid.UUID | None = None,
):
    """List all downloads with media information"""
    service = DownloadService(db)
    downloads = await service.list_downloads(user_guid=user_guid)
    return [DownloadResponse(**d) for d in downloads]


@router.delete("/{download_id}")
async def delete_download(
    download_id: uuid.UUID, db: DatabaseSession, current_user: CurrentSuperuser
):
    """Delete a download"""
    service = DownloadService(db)
    download = await service.delete(download_id)
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    return {"detail": "Download deleted"}


@router.post("/{download_id}/pause")
async def pause_download(
    download_id: uuid.UUID, db: DatabaseSession, current_user: CurrentSuperuser
):
    """Pause an in-progress or queued download."""
    service = DownloadService(db)
    try:
        download = await service.pause(download_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Downloader error: {exc}")
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    return {"detail": "Download paused", "status": download.status}


@router.post("/{download_id}/resume")
async def resume_download(
    download_id: uuid.UUID, db: DatabaseSession, current_user: CurrentSuperuser
):
    """Resume a paused download."""
    service = DownloadService(db)
    try:
        download = await service.resume(download_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Downloader error: {exc}")
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    return {"detail": "Download resumed", "status": download.status}
