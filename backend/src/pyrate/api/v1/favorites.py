import uuid

from fastapi import APIRouter, BackgroundTasks

from pyrate.api.dependencies import CurrentUser, DatabaseSession
from pyrate.schemas.favorite import FavoriteListResponse, FavoriteStatusResponse
from pyrate.services.cache_control import clear_rendered_layout_cache
from pyrate.services.favorite import FavoriteService

router = APIRouter()


@router.get("/{type_prefix}/{item_guid}/status", response_model=FavoriteStatusResponse)
async def get_favorite_status(
    type_prefix: str,
    item_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> FavoriteStatusResponse:
    """Check whether the current user has favorited a given media item."""
    return await FavoriteService(db).get_status(type_prefix, item_guid, current_user.guid)


@router.post("/{type_prefix}/{item_guid}", response_model=FavoriteStatusResponse)
async def toggle_favorite(
    type_prefix: str,
    item_guid: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> FavoriteStatusResponse:
    """Toggle the favorite status for a media item. Returns the new status."""
    result = await FavoriteService(db).toggle(type_prefix, item_guid, current_user.guid)
    background_tasks.add_task(clear_rendered_layout_cache, "favorites_changed")
    return result


# Register at both "" and "/" so the route matches /api/favorites and
# /api/favorites/. Without this, FastAPI's redirect_slashes turns the
# slash form into a 307 that some browser/axios combos don't follow,
# and a stale frontend bundle pinned to the slash form silently sees
# no favorites. include_in_schema=False on the alias to keep OpenAPI clean.
@router.get("", response_model=FavoriteListResponse)
@router.get("/", response_model=FavoriteListResponse, include_in_schema=False)
async def list_favorites(
    db: DatabaseSession,
    current_user: CurrentUser,
    type_prefix: str | None = None,
) -> FavoriteListResponse:
    """Return all favorites for the current user, optionally filtered by media type."""
    return await FavoriteService(db).list_favorites(
        current_user.guid, type_prefix, ui_language=current_user.ui_language
    )
