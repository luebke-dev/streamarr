"""Media markers API — manage intro/outro/credits markers."""

import uuid

from fastapi import APIRouter, HTTPException

from streamarr.api.dependencies import (
    CurrentSuperuser,
    CurrentUser,
    DatabaseSession,
    UserPermissionsDep,
)
from streamarr.schemas.media_marker import (
    MediaMarkerCreate,
    MediaMarkerRead,
    MediaMarkersForPlayer,
    MediaMarkerUpdate,
)
from streamarr.services.media_access import get_visible_media_item
from streamarr.services.media_marker import MediaMarkerService

router = APIRouter()


@router.get("/{media_id}/markers", response_model=MediaMarkersForPlayer)
async def get_markers_for_player(
    media_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
):
    """Get effective markers for the player (best per type)."""
    await get_visible_media_item(db, media_id, current_user, permissions)
    service = MediaMarkerService(db)
    return await service.get_effective_markers(media_id)


@router.get("/{media_id}/markers/all", response_model=list[MediaMarkerRead])
async def list_all_markers(
    media_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """List all markers for a media item (admin only)."""
    service = MediaMarkerService(db)
    return await service.get_all_markers(media_id)


@router.post("/{media_id}/markers", response_model=MediaMarkerRead)
async def create_marker(
    media_id: uuid.UUID,
    body: MediaMarkerCreate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Create or update a marker (admin only)."""
    service = MediaMarkerService(db)
    return await service.create_marker(media_id, body)


@router.put("/markers/{marker_id}", response_model=MediaMarkerRead)
async def update_marker(
    marker_id: uuid.UUID,
    body: MediaMarkerUpdate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Update a marker (admin only)."""
    service = MediaMarkerService(db)
    marker = await service.update_marker(marker_id, body)
    if not marker:
        raise HTTPException(status_code=404, detail="Marker not found")
    return marker


@router.delete("/markers/{marker_id}", status_code=204)
async def delete_marker(
    marker_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Delete a marker (admin only)."""
    service = MediaMarkerService(db)
    if not await service.delete_marker(marker_id):
        raise HTTPException(status_code=404, detail="Marker not found")


@router.post("/seasons/{season_id}/detect-markers")
async def trigger_season_detection(
    season_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Kick off chromaprint intro/outro detection for a season."""
    from streamarr.worker import detect_intro_outro_season

    await detect_intro_outro_season.kiq(str(season_id))
    return {"status": "queued", "message": "Detection started for season"}


@router.post("/{media_id}/detect-credits")
async def trigger_credits_detection(
    media_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Kick off credits detection for a movie."""
    from streamarr.worker import detect_credits_movie

    await detect_credits_movie.kiq(str(media_id))
    return {"status": "queued", "message": "Credits detection started"}
