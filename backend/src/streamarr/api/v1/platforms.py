"""Platform API endpoints."""

from fastapi import APIRouter, Response

from streamarr.api.dependencies import CurrentUser, DatabaseSession
from streamarr.schemas.media import PlatformRead
from streamarr.services.platform import PlatformService

router = APIRouter()


@router.get("", response_model=list[PlatformRead])
async def list_platforms(db: DatabaseSession, current_user: CurrentUser, response: Response):
    """List all platforms."""
    platforms = await PlatformService(db).list_all()
    response.headers["Cache-Control"] = "private, max-age=3600"
    return [PlatformRead.model_validate(p) for p in platforms]
