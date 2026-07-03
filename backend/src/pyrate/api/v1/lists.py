import logging
import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import selectinload

from pyrate.api.dependencies import CurrentSuperuser, DatabaseSession
from pyrate.auth.dependencies import get_current_user, get_current_user_optional
from pyrate.config import get_app_url
from pyrate.models.list import (
    List,
    ListItem,
    ListType,
    ListVisibility,
    UserListInteractionType,
)
from pyrate.models.media import MediaItem
from pyrate.schemas.device import (
    DeviceCommandResponse,
    DeviceSessionPlayQueueCreate,
    DeviceSessionPlayQueueItem,
)
from pyrate.schemas.list import (
    AddItemToListRequest,
    ListCreate,
    ListInteractionRequest,
    ListItemCreate,
    ListItemRead,
    ListRead,
    ListStatsResponse,
    ListSummaryRead,
    ListUpdate,
    PaginatedListItemsWithDataResponse,
    PaginatedListsResponse,
    SystemListCreate,
    UserListInteractionCreate,
)
from pyrate.schemas.media import MediaItemRead
from pyrate.services.cache_control import clear_rendered_layout_cache
from pyrate.services.list import ListService

logger = logging.getLogger(__name__)

router = APIRouter()


# List endpoints
@router.get("", response_model=PaginatedListsResponse)
async def get_lists(
    db: DatabaseSession,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    list_type: ListType | None = Query(None, description="Filter by list type"),
    visibility: ListVisibility | None = Query(None, description="Filter by visibility"),
    owner_guid: str | None = Query(None, description="Filter by owner GUID"),
    owner: str | None = Query(None, description="Shortcut: 'me' resolves to the current user's GUID"),
    content_type: str | None = Query(None, description="Filter lists containing this item type (movie, show, game)"),
    update_source: str | None = Query(None, description="Exact match on List.update_source"),
    update_source_prefix: str | None = Query(None, description="Prefix match on List.update_source"),
    current_user=Depends(get_current_user_optional),
):
    """Get all lists with optional filtering"""
    skip = (page - 1) * per_page
    current_user_guid = str(current_user.guid) if current_user else None
    current_user_is_superuser = current_user.is_superuser if current_user else False

    if owner == "me":
        if not current_user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        owner_guid = str(current_user.guid)

    lists, total = await ListService(db).get_all(
        skip=skip,
        limit=per_page,
        list_type=list_type,
        visibility=visibility,
        owner_guid=owner_guid,
        current_user_guid=current_user_guid,
        current_user_is_superuser=current_user_is_superuser,
        content_type=content_type,
        update_source=update_source,
        update_source_prefix=update_source_prefix,
    )

    total_pages = math.ceil(total / per_page) if total > 0 else 1

    items = await ListService(db).get_lists_with_item_types(lists)

    return PaginatedListsResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.post("", response_model=ListSummaryRead)
async def create_list(
    db: DatabaseSession, list_data: ListCreate, current_user=Depends(get_current_user)
):
    """Create a new list"""
    # Only admins can create system lists
    if list_data.list_type == ListType.SYSTEM and not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Only administrators can create system lists"
        )

    owner_guid = (
        str(current_user.guid) if list_data.list_type == ListType.USER else None
    )
    list_obj = await ListService(db).create(list_data, owner_guid)
    logger.info("User %s created list %s", current_user.guid, list_obj.guid)
    await clear_rendered_layout_cache("list_changed")
    return ListSummaryRead.model_validate(list_obj)


@router.get("/{list_id}", response_model=ListRead)
async def get_list(
    db: DatabaseSession, list_id: UUID, current_user=Depends(get_current_user_optional)
):
    """Get a specific list by ID"""
    list_obj = await ListService(db).get_by_id(str(list_id))
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")

    # Check if user can access this list
    if list_obj.visibility == ListVisibility.PRIVATE:
        if not current_user or str(current_user.guid) != str(list_obj.owner_guid):
            raise HTTPException(status_code=403, detail="Access denied")

    return ListRead.model_validate(list_obj)


@router.put("/{list_id}", response_model=ListRead)
async def update_list(
    db: DatabaseSession,
    list_id: UUID,
    list_update: ListUpdate,
    current_user=Depends(get_current_user),
):
    """Update a list"""
    list_obj = await ListService(db).get_by_id(str(list_id))
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")

    # Check ownership or admin rights
    if list_obj.list_type == ListType.SYSTEM and not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Only administrators can update system lists"
        )
    elif list_obj.list_type == ListType.USER and str(list_obj.owner_guid) != str(
        current_user.guid
    ):
        raise HTTPException(
            status_code=403, detail="You can only update your own lists"
        )

    updated_list = await ListService(db).update(list_obj, list_update)
    logger.info("User %s updated list %s", current_user.guid, list_id)
    await clear_rendered_layout_cache("list_changed")
    return ListRead.model_validate(updated_list)


@router.delete("/{list_id}", status_code=204)
async def delete_list(
    db: DatabaseSession, list_id: UUID, current_user=Depends(get_current_user)
):
    """Delete a list"""
    list_obj = await ListService(db).get_by_id(str(list_id))
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")

    # Check ownership or admin rights
    if list_obj.list_type == ListType.SYSTEM and not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Only administrators can delete system lists"
        )
    elif list_obj.list_type == ListType.USER and str(list_obj.owner_guid) != str(
        current_user.guid
    ):
        raise HTTPException(
            status_code=403, detail="You can only delete your own lists"
        )

    await ListService(db).delete(list_obj)
    logger.info("User %s deleted list %s", current_user.guid, list_id)
    await clear_rendered_layout_cache("list_changed")


# List items endpoints
@router.get("/{list_id}/items", response_model=PaginatedListItemsWithDataResponse)
async def get_list_items(
    db: DatabaseSession,
    list_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Items per page"),
    current_user=Depends(get_current_user_optional),
):
    """Get items in a list with their actual data"""
    # Check if list exists and is accessible
    list_obj = await ListService(db).get_by_id(str(list_id))
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")

    if list_obj.visibility == ListVisibility.PRIVATE:
        if not current_user or str(current_user.guid) != str(list_obj.owner_guid):
            raise HTTPException(status_code=403, detail="Access denied")

    skip = (page - 1) * per_page
    language = (
        current_user.ui_language
        if current_user and getattr(current_user, "ui_language", None)
        else None
    )
    friend_watchers_for_user = None
    if (
        current_user
        and list_obj.update_source
        and list_obj.update_source.startswith("rec:friends_watching:")
    ):
        friend_watchers_for_user = str(current_user.guid)
    enriched_items, total = await ListService(db).get_items_with_data(
        str(list_id),
        skip,
        per_page,
        language=language,
        friend_watchers_for_user=friend_watchers_for_user,
    )

    total_pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedListItemsWithDataResponse(
        items=enriched_items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/{list_id}/items/optimized", response_model=list[MediaItemRead])
async def get_list_items_optimized(
    db: DatabaseSession,
    list_id: UUID,
    current_user=Depends(get_current_user_optional),
):
    """
    Get items in a list with optimized batch loading for genres.

    This endpoint loads all data in minimal queries:
    1. One query for all list items with media data
    2. One query for all genres (batch)
    3. No N+1 query problem

    Much faster than the paginated endpoint for frontend list pages.
    """
    # Check if list exists and is accessible
    list_obj = await ListService(db).get_by_id(str(list_id))
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")

    if list_obj.visibility == ListVisibility.PRIVATE:
        if not current_user or str(current_user.guid) != str(list_obj.owner_guid):
            raise HTTPException(status_code=403, detail="Access denied")

    language = (
        current_user.ui_language
        if current_user and getattr(current_user, "ui_language", None)
        else None
    )
    return await ListService(db).get_items_optimized(list_id, language=language)


@router.post("/{list_id}/items", response_model=ListItemRead)
async def add_item_to_list(
    db: DatabaseSession,
    list_id: UUID,
    item_request: AddItemToListRequest,
    current_user=Depends(get_current_user),
):
    """Add an item to a list"""
    list_obj = await ListService(db).get_by_id(str(list_id))
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")

    # Check if user can add to this list
    if list_obj.list_type == ListType.SYSTEM and not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Only administrators can modify system lists"
        )
    elif list_obj.list_type == ListType.USER and str(list_obj.owner_guid) != str(
        current_user.guid
    ):
        raise HTTPException(
            status_code=403, detail="You can only modify your own lists"
        )

    try:
        item_data = ListItemCreate(
            item_type=item_request.item_type,
            item_guid=item_request.item_guid,
            notes=item_request.notes,
            order_index=item_request.order_index,
        )

        item = await ListService(db).add_item(
            str(list_id), item_data, str(current_user.guid)
        )
        logger.info("User %s added item %s to list %s", current_user.guid, item_request.item_guid, list_id)
        await clear_rendered_layout_cache("list_items_changed")
        return ListItemRead.model_validate(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{list_id}/items/{item_id}", status_code=204)
async def remove_item_from_list(
    db: DatabaseSession,
    list_id: UUID,
    item_id: UUID,
    current_user=Depends(get_current_user),
):
    """Remove an item from a list"""
    list_obj = await ListService(db).get_by_id(str(list_id))
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")

    # Check permissions
    if list_obj.list_type == ListType.SYSTEM and not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Only administrators can modify system lists"
        )
    elif list_obj.list_type == ListType.USER and str(list_obj.owner_guid) != str(
        current_user.guid
    ):
        raise HTTPException(
            status_code=403, detail="You can only modify your own lists"
        )

    try:
        await ListService(db).remove_item(str(list_id), str(item_id))
        logger.info("User %s removed item %s from list %s", current_user.guid, item_id, list_id)
        await clear_rendered_layout_cache("list_items_changed")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# User interactions with lists
@router.post("/{list_id}/interactions", status_code=201)
async def create_list_interaction(
    db: DatabaseSession,
    list_id: UUID,
    interaction_request: ListInteractionRequest,
    current_user=Depends(get_current_user),
):
    """Like, follow, or bookmark a list"""
    list_obj = await ListService(db).get_by_id(str(list_id))
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")

    # Can't like your own lists
    if str(list_obj.owner_guid) == str(current_user.guid):
        raise HTTPException(
            status_code=400, detail="Cannot like your own list"
        )

    # Can't interact with private lists you don't own
    if list_obj.visibility == ListVisibility.PRIVATE:
        raise HTTPException(
            status_code=403, detail="Cannot interact with private lists"
        )

    interaction_data = UserListInteractionCreate(
        user_guid=current_user.guid,
        list_guid=list_id,
        interaction_type=interaction_request.interaction_type,
    )

    await ListService(db).create_user_interaction(interaction_data)


@router.delete("/{list_id}/interactions/{interaction_type}", status_code=204)
async def remove_list_interaction(
    db: DatabaseSession,
    list_id: UUID,
    interaction_type: UserListInteractionType,
    current_user=Depends(get_current_user),
):
    """Remove a like, follow, or bookmark from a list"""
    await ListService(db).remove_user_interaction(
        str(current_user.guid), str(list_id), interaction_type
    )


# User's lists
@router.get("/users/{user_id}/lists", response_model=PaginatedListsResponse)
async def get_user_lists(
    db: DatabaseSession,
    user_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user_optional),
):
    """Get lists owned by a specific user"""
    skip = (page - 1) * per_page
    # If requesting another user's lists, only show public ones
    # If requesting own lists, show all
    lists, total = await ListService(db).get_user_lists(str(user_id), skip, per_page)

    total_pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedListsResponse(
        items=[ListSummaryRead.model_validate(list_item) for list_item in lists],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/users/{user_id}/liked", response_model=PaginatedListsResponse)
async def get_user_liked_lists(
    db: DatabaseSession,
    user_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user_optional),
):
    """Get lists liked by a specific user.

    The owner sees their own liked lists; superusers can inspect any
    user's liked lists (symmetrical to ``/users/{user_id}/lists`` above,
    which is public). Anyone else gets 403.
    """
    is_owner = current_user and str(current_user.guid) == str(user_id)
    is_admin = current_user and current_user.is_superuser
    if not (is_owner or is_admin):
        raise HTTPException(
            status_code=403, detail="Can only view your own liked lists"
        )

    skip = (page - 1) * per_page
    lists, total = await ListService(db).get_user_liked_lists(
        str(user_id), skip, per_page
    )

    total_pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedListsResponse(
        items=[ListSummaryRead.model_validate(list_item) for list_item in lists],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


# Admin endpoints
@router.get("/admin/all", response_model=PaginatedListsResponse)
async def get_all_lists_admin(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    list_type: ListType | None = Query(None, description="Filter by list type"),
    visibility: ListVisibility | None = Query(None, description="Filter by visibility"),
    search: str | None = Query(None, description="Search by list name"),
):
    """Get all lists across all users (admin only).

    Returns all lists including private ones, regardless of ownership.
    """
    skip = (page - 1) * per_page
    lists, total = await ListService(db).get_all_admin(
        skip=skip,
        limit=per_page,
        list_type=list_type,
        visibility=visibility,
        search=search,
    )

    total_pages = math.ceil(total / per_page) if total > 0 else 1

    return PaginatedListsResponse(
        items=[ListSummaryRead.model_validate(list_item) for list_item in lists],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.delete("/admin/{list_id}")
async def admin_delete_list(
    db: DatabaseSession,
    list_id: UUID,
    current_user: CurrentSuperuser,
):
    """Delete any list (admin only)."""
    list_obj = await ListService(db).get_by_id(str(list_id))
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")

    await ListService(db).delete(list_obj)
    logger.info("Admin %s deleted list %s", current_user.guid, list_id)
    await clear_rendered_layout_cache("list_changed")
    return {"message": "List deleted successfully"}


# System lists (admin only)
@router.post("/system", response_model=ListRead)
async def create_system_list(
    db: DatabaseSession,
    list_data: SystemListCreate,
    current_user: CurrentSuperuser,
):
    """Create a system list (admin only)"""
    # Convert to regular ListCreate
    list_create = ListCreate(
        name=list_data.name,
        description=list_data.description,
        list_type=ListType.SYSTEM,
        visibility=list_data.visibility,
        auto_update=list_data.auto_update,
        update_source=list_data.update_source,
        tags=list_data.tags,
        poster_path=list_data.poster_path,
    )

    list_obj = await ListService(db).create(list_create, None)
    logger.info("Admin %s created system list %s", current_user.guid, list_obj.guid)
    await clear_rendered_layout_cache("list_changed")
    return ListRead.model_validate(list_obj)


@router.get("/{list_id}/stats", response_model=ListStatsResponse)
async def get_list_stats(
    db: DatabaseSession, list_id: UUID, current_user=Depends(get_current_user_optional)
):
    """Get statistics for a list"""
    list_obj = await ListService(db).get_by_id(str(list_id))
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")

    # Check visibility
    if list_obj.visibility == ListVisibility.PRIVATE:
        if not current_user or str(current_user.guid) != str(list_obj.owner_guid):
            raise HTTPException(status_code=403, detail="Access denied")

    return ListStatsResponse(
        list_guid=list_obj.guid,
        item_count=list_obj.item_count,
        like_count=list_obj.like_count,
        follow_count=list_obj.follow_count,
        created_at=list_obj.created_at,
        updated_at=list_obj.updated_at,
        last_auto_update=list_obj.last_auto_update,
    )

# Collections endpoints backed by the List model/service.
collections_router = APIRouter()

COLLECTION_TAG = "pyrate:collection"


class CollectionCreate(BaseModel):
    name: str
    description: str | None = None
    visibility: ListVisibility = ListVisibility.PRIVATE
    tags: str | None = None
    poster_path: str | None = None


def _collection_tags(tags: str | None) -> str:
    if not tags:
        return COLLECTION_TAG
    if COLLECTION_TAG in tags:
        return tags
    return f"{tags},{COLLECTION_TAG}"


def _strip_collection_tag(tags: str | None) -> str | None:
    if not tags:
        return tags
    public_tags = [
        tag.strip()
        for tag in tags.split(",")
        if tag.strip() and tag.strip() != COLLECTION_TAG
    ]
    return ",".join(public_tags) or None


def _as_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(value)


def _to_collection_summary(list_obj: List) -> ListSummaryRead:
    summary = ListSummaryRead.model_validate(list_obj)
    summary.tags = _strip_collection_tag(summary.tags)
    return summary


def _to_collection_read(list_obj: List) -> ListRead:
    collection = ListRead.model_validate(list_obj)
    collection.tags = _strip_collection_tag(collection.tags)
    return collection


async def _get_collection_or_404(
    db: DatabaseSession,
    collection_id: UUID,
) -> List:
    collection = await ListService(db).get_by_id(str(collection_id))
    if not collection or COLLECTION_TAG not in (collection.tags or ""):
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


def _ensure_collection_access(collection: List, current_user) -> None:
    if collection.visibility == ListVisibility.PRIVATE:
        if not current_user or str(current_user.guid) != str(collection.owner_guid):
            raise HTTPException(status_code=403, detail="Access denied")


def _ensure_collection_owner(collection: List, current_user) -> None:
    if current_user.is_superuser:
        return
    if str(collection.owner_guid) != str(current_user.guid):
        raise HTTPException(
            status_code=403, detail="You can only modify your own collections"
        )


@collections_router.get("", response_model=PaginatedListsResponse)
async def get_collections(
    db: DatabaseSession,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    owner: str | None = Query(None, description="Shortcut: 'me' resolves to the current user's GUID"),
    owner_guid: str | None = Query(None, description="Filter by owner GUID"),
    visibility: ListVisibility | None = Query(None, description="Filter by visibility"),
    current_user=Depends(get_current_user_optional),
):
    skip = (page - 1) * per_page
    current_user_guid = current_user.guid if current_user else None

    if owner == "me":
        if not current_user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        owner_guid = str(current_user.guid)

    filters = [
        List.is_active,
        List.deleted_at.is_(None),
        List.list_type == ListType.USER,
        List.tags.like(f"%{COLLECTION_TAG}%"),
    ]

    if owner_guid:
        filters.append(List.owner_guid == _as_uuid(owner_guid))

    if visibility:
        if visibility == ListVisibility.PRIVATE:
            if not current_user:
                raise HTTPException(status_code=401, detail="Not authenticated")
            filters.append(
                and_(
                    List.visibility == ListVisibility.PRIVATE,
                    List.owner_guid == current_user_guid,
                )
            )
        else:
            filters.append(List.visibility == visibility)
    elif current_user:
        filters.append(
            or_(
                List.visibility == ListVisibility.PUBLIC,
                and_(
                    List.visibility == ListVisibility.PRIVATE,
                    List.owner_guid == current_user_guid,
                ),
            )
        )
    else:
        filters.append(List.visibility == ListVisibility.PUBLIC)

    where_clause = and_(*filters)
    count_result = await db.execute(select(func.count(List.guid)).where(where_clause))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(List)
        .options(
            selectinload(List.owner),
            selectinload(List.items),
            selectinload(List.user_interactions),
        )
        .where(where_clause)
        .order_by(List.updated_at.desc())
        .offset(skip)
        .limit(per_page)
    )
    collections = list(result.scalars().all())

    items = await ListService(db).get_lists_with_item_types(collections)
    for item in items:
        item.tags = _strip_collection_tag(item.tags)

    return PaginatedListsResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=math.ceil(total / per_page) if total > 0 else 1,
    )


@collections_router.post("", response_model=ListSummaryRead)
async def create_collection(
    db: DatabaseSession,
    collection_data: CollectionCreate,
    current_user=Depends(get_current_user),
):
    list_data = ListCreate(
        name=collection_data.name,
        description=collection_data.description,
        list_type=ListType.USER,
        visibility=collection_data.visibility,
        tags=_collection_tags(collection_data.tags),
        poster_path=collection_data.poster_path,
    )
    collection = await ListService(db).create(list_data, str(current_user.guid))
    logger.info("User %s created collection %s", current_user.guid, collection.guid)
    return _to_collection_summary(collection)


@collections_router.get("/{collection_id}", response_model=ListRead)
async def get_collection(
    db: DatabaseSession,
    collection_id: UUID,
    current_user=Depends(get_current_user_optional),
):
    collection = await _get_collection_or_404(db, collection_id)
    _ensure_collection_access(collection, current_user)
    return _to_collection_read(collection)


@collections_router.get("/{collection_id}/items", response_model=PaginatedListItemsWithDataResponse)
async def get_collection_items(
    db: DatabaseSession,
    collection_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Items per page"),
    current_user=Depends(get_current_user_optional),
):
    collection = await _get_collection_or_404(db, collection_id)
    _ensure_collection_access(collection, current_user)

    skip = (page - 1) * per_page
    language = (
        current_user.ui_language
        if current_user and getattr(current_user, "ui_language", None)
        else None
    )
    items, total = await ListService(db).get_items_with_data(
        str(collection_id), skip, per_page, language=language
    )

    return PaginatedListItemsWithDataResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=math.ceil(total / per_page) if total > 0 else 1,
    )


@collections_router.post("/{collection_id}/items", response_model=ListItemRead)
async def add_item_to_collection(
    db: DatabaseSession,
    collection_id: UUID,
    item_request: AddItemToListRequest,
    current_user=Depends(get_current_user),
):
    collection = await _get_collection_or_404(db, collection_id)
    _ensure_collection_owner(collection, current_user)

    try:
        item_data = ListItemCreate(
            item_type=item_request.item_type,
            item_guid=item_request.item_guid,
            notes=item_request.notes,
            order_index=item_request.order_index,
        )
        item = await ListService(db).add_item(
            str(collection_id), item_data, str(current_user.guid)
        )
        item.added_by = current_user
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "User %s added item %s to collection %s",
        current_user.guid,
        item_request.item_guid,
        collection_id,
    )
    return ListItemRead.model_validate(item)


@collections_router.delete("/{collection_id}/items/{item_id}", status_code=204)
async def remove_item_from_collection(
    db: DatabaseSession,
    collection_id: UUID,
    item_id: UUID,
    current_user=Depends(get_current_user),
):
    collection = await _get_collection_or_404(db, collection_id)
    _ensure_collection_owner(collection, current_user)

    try:
        await ListService(db).remove_item(str(collection_id), str(item_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    logger.info(
        "User %s removed item %s from collection %s",
        current_user.guid,
        item_id,
        collection_id,
    )


# Playlists endpoints backed by the List model/service.
playlists_router = APIRouter()

PLAYLIST_TAG = "pyrate:playlist"


class PlaylistCreate(BaseModel):
    name: str
    description: str | None = None
    visibility: ListVisibility = ListVisibility.PRIVATE
    tags: str | None = None
    poster_path: str | None = None


class PlaylistUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    visibility: ListVisibility | None = None
    tags: str | None = None
    poster_path: str | None = None


class PlaylistShareUpdate(BaseModel):
    enabled: bool = True


class PlaylistShareResponse(BaseModel):
    playlist_id: UUID
    is_shared: bool
    visibility: ListVisibility
    share_url: str | None = None


class PlaylistPlayOnDeviceRequest(BaseModel):
    device_id: str
    start_item_guid: UUID | None = None
    start_index: int = 0
    start_position_seconds: int | None = None
    from_device_id: str | None = None


class PlaylistReorderRequest(BaseModel):
    item_ids: list[UUID]


class PlaylistQueueItem(BaseModel):
    playlist_item_id: UUID
    media_item_guid: UUID
    item_type: str
    queue_index: int
    title: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    duration_seconds: int | None = None
    is_current: bool = False


class PlaylistQueueResponse(BaseModel):
    playlist_id: UUID
    playlist_name: str
    start_index: int
    current_item: PlaylistQueueItem | None = None
    previous_item: PlaylistQueueItem | None = None
    next_item: PlaylistQueueItem | None = None
    items: list[PlaylistQueueItem]
    total: int


def _playlist_tags(tags: str | None) -> str:
    if not tags:
        return PLAYLIST_TAG
    if PLAYLIST_TAG in tags:
        return tags
    return f"{tags},{PLAYLIST_TAG}"


def _strip_playlist_tag(tags: str | None) -> str | None:
    if not tags:
        return tags
    public_tags = [
        tag.strip()
        for tag in tags.split(",")
        if tag.strip() and tag.strip() != PLAYLIST_TAG
    ]
    return ",".join(public_tags) or None


def _to_playlist_summary(list_obj: List) -> ListSummaryRead:
    summary = ListSummaryRead.model_validate(list_obj)
    summary.tags = _strip_playlist_tag(summary.tags)
    return summary


def _to_playlist_read(list_obj: List) -> ListRead:
    playlist = ListRead.model_validate(list_obj)
    playlist.tags = _strip_playlist_tag(playlist.tags)
    return playlist


async def _get_playlist_or_404(
    db: DatabaseSession,
    playlist_id: UUID,
) -> List:
    playlist = await ListService(db).get_by_id(str(playlist_id))
    if not playlist or PLAYLIST_TAG not in (playlist.tags or ""):
        raise HTTPException(status_code=404, detail="Playlist not found")
    return playlist


def _ensure_playlist_access(playlist: List, current_user) -> None:
    if playlist.visibility == ListVisibility.PRIVATE:
        if not current_user or str(current_user.guid) != str(playlist.owner_guid):
            raise HTTPException(status_code=403, detail="Access denied")


def _ensure_playlist_owner(playlist: List, current_user) -> None:
    if current_user.is_superuser:
        return
    if str(playlist.owner_guid) != str(current_user.guid):
        raise HTTPException(
            status_code=403, detail="You can only modify your own playlists"
        )


def _playlist_share_response(playlist: List) -> PlaylistShareResponse:
    is_shared = playlist.visibility == ListVisibility.PUBLIC
    return PlaylistShareResponse(
        playlist_id=playlist.guid,
        is_shared=is_shared,
        visibility=playlist.visibility,
        share_url=f"{get_app_url()}/playlists/{playlist.guid}" if is_shared else None,
    )


async def _build_playlist_queue(
    db: DatabaseSession,
    playlist: List,
    *,
    start_item_guid: UUID | None = None,
    start_index: int = 0,
) -> PlaylistQueueResponse:
    result = await db.execute(
        select(ListItem)
        .where(ListItem.list_guid == playlist.guid)
        .order_by(
            ListItem.order_index.is_(None),
            ListItem.order_index.asc(),
            ListItem.created_at.asc(),
        )
    )
    list_items = list(result.scalars().all())
    media_guids = [item.item_guid for item in list_items]
    media_map: dict[UUID, MediaItem] = {}
    if media_guids:
        media_result = await db.execute(
            select(MediaItem).where(MediaItem.guid.in_(media_guids))
        )
        media_map = {item.guid: item for item in media_result.scalars().all()}

    queue_items: list[PlaylistQueueItem] = []
    for index, list_item in enumerate(list_items):
        media_item = media_map.get(list_item.item_guid)
        duration_seconds = None
        if media_item:
            # Duration lives on files, not MediaItem; clients can resolve playback
            # details when they start the selected item.
            title = media_item.title
            poster_path = media_item.poster_path
            backdrop_path = media_item.backdrop_path
        else:
            title = None
            poster_path = None
            backdrop_path = None
        queue_items.append(
            PlaylistQueueItem(
                playlist_item_id=list_item.guid,
                media_item_guid=list_item.item_guid,
                item_type=list_item.item_type.value.lower(),
                queue_index=index,
                title=title,
                poster_path=poster_path,
                backdrop_path=backdrop_path,
                duration_seconds=duration_seconds,
            )
        )

    if start_item_guid:
        for item in queue_items:
            if item.media_item_guid == start_item_guid:
                start_index = item.queue_index
                break
        else:
            raise HTTPException(status_code=404, detail="Start item not found")

    if queue_items:
        if start_index < 0 or start_index >= len(queue_items):
            raise HTTPException(status_code=400, detail="start_index is out of range")
        queue_items[start_index].is_current = True
        current_item = queue_items[start_index]
        previous_item = queue_items[start_index - 1] if start_index > 0 else None
        next_item = (
            queue_items[start_index + 1]
            if start_index + 1 < len(queue_items)
            else None
        )
    else:
        current_item = previous_item = next_item = None
        start_index = 0

    return PlaylistQueueResponse(
        playlist_id=playlist.guid,
        playlist_name=playlist.name,
        start_index=start_index,
        current_item=current_item,
        previous_item=previous_item,
        next_item=next_item,
        items=queue_items,
        total=len(queue_items),
    )


@playlists_router.get("", response_model=PaginatedListsResponse)
async def get_playlists(
    db: DatabaseSession,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    owner: str | None = Query(
        None, description="Shortcut: 'me' resolves to the current user's GUID"
    ),
    owner_guid: str | None = Query(None, description="Filter by owner GUID"),
    visibility: ListVisibility | None = Query(None, description="Filter by visibility"),
    current_user=Depends(get_current_user_optional),
):
    skip = (page - 1) * per_page
    current_user_guid = current_user.guid if current_user else None

    if owner == "me":
        if not current_user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        owner_guid = str(current_user.guid)

    filters = [
        List.is_active,
        List.deleted_at.is_(None),
        List.list_type == ListType.USER,
        List.tags.like(f"%{PLAYLIST_TAG}%"),
    ]

    if owner_guid:
        filters.append(List.owner_guid == _as_uuid(owner_guid))

    if visibility:
        if visibility == ListVisibility.PRIVATE:
            if not current_user:
                raise HTTPException(status_code=401, detail="Not authenticated")
            filters.append(
                and_(
                    List.visibility == ListVisibility.PRIVATE,
                    List.owner_guid == current_user_guid,
                )
            )
        else:
            filters.append(List.visibility == visibility)
    elif current_user:
        filters.append(
            or_(
                List.visibility == ListVisibility.PUBLIC,
                and_(
                    List.visibility == ListVisibility.PRIVATE,
                    List.owner_guid == current_user_guid,
                ),
            )
        )
    else:
        filters.append(List.visibility == ListVisibility.PUBLIC)

    where_clause = and_(*filters)
    count_result = await db.execute(select(func.count(List.guid)).where(where_clause))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(List)
        .options(
            selectinload(List.owner),
            selectinload(List.items),
            selectinload(List.user_interactions),
        )
        .where(where_clause)
        .order_by(List.updated_at.desc())
        .offset(skip)
        .limit(per_page)
    )
    playlists = list(result.scalars().all())

    items = await ListService(db).get_lists_with_item_types(playlists)
    for item in items:
        item.tags = _strip_playlist_tag(item.tags)

    return PaginatedListsResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=math.ceil(total / per_page) if total > 0 else 1,
    )


@playlists_router.post("", response_model=ListSummaryRead)
async def create_playlist(
    db: DatabaseSession,
    playlist_data: PlaylistCreate,
    current_user=Depends(get_current_user),
):
    list_data = ListCreate(
        name=playlist_data.name,
        description=playlist_data.description,
        list_type=ListType.USER,
        visibility=playlist_data.visibility,
        tags=_playlist_tags(playlist_data.tags),
        poster_path=playlist_data.poster_path,
    )
    playlist = await ListService(db).create(list_data, str(current_user.guid))
    logger.info("User %s created playlist %s", current_user.guid, playlist.guid)
    return _to_playlist_summary(playlist)


@playlists_router.get("/{playlist_id}", response_model=ListRead)
async def get_playlist(
    db: DatabaseSession,
    playlist_id: UUID,
    current_user=Depends(get_current_user_optional),
):
    playlist = await _get_playlist_or_404(db, playlist_id)
    _ensure_playlist_access(playlist, current_user)
    return _to_playlist_read(playlist)


@playlists_router.put("/{playlist_id}", response_model=ListRead)
async def update_playlist(
    db: DatabaseSession,
    playlist_id: UUID,
    playlist_update: PlaylistUpdate,
    current_user=Depends(get_current_user),
):
    """Update playlist metadata. Owners and admins may update user playlists."""
    playlist = await _get_playlist_or_404(db, playlist_id)
    _ensure_playlist_owner(playlist, current_user)
    update_data = playlist_update.model_dump(exclude_unset=True)
    if "tags" in update_data:
        update_data["tags"] = _playlist_tags(update_data["tags"])
    updated = await ListService(db).update(playlist, ListUpdate(**update_data))
    logger.info("User %s updated playlist %s", current_user.guid, playlist_id)
    return _to_playlist_read(updated)


@playlists_router.get("/{playlist_id}/share", response_model=PlaylistShareResponse)
async def get_playlist_share(
    db: DatabaseSession,
    playlist_id: UUID,
    current_user=Depends(get_current_user),
):
    """Return playlist sharing state."""
    playlist = await _get_playlist_or_404(db, playlist_id)
    _ensure_playlist_owner(playlist, current_user)
    return _playlist_share_response(playlist)


@playlists_router.put("/{playlist_id}/share", response_model=PlaylistShareResponse)
async def update_playlist_share(
    db: DatabaseSession,
    playlist_id: UUID,
    share_update: PlaylistShareUpdate,
    current_user=Depends(get_current_user),
):
    """Enable or disable public sharing for a playlist."""
    playlist = await _get_playlist_or_404(db, playlist_id)
    _ensure_playlist_owner(playlist, current_user)
    visibility = (
        ListVisibility.PUBLIC if share_update.enabled else ListVisibility.PRIVATE
    )
    updated = await ListService(db).update(
        playlist,
        ListUpdate(visibility=visibility),
    )
    logger.info(
        "User %s %s playlist sharing for %s",
        current_user.guid,
        "enabled" if share_update.enabled else "disabled",
        playlist_id,
    )
    return _playlist_share_response(updated)


@playlists_router.get("/{playlist_id}/items", response_model=PaginatedListItemsWithDataResponse)
async def get_playlist_items(
    db: DatabaseSession,
    playlist_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Items per page"),
    current_user=Depends(get_current_user_optional),
):
    playlist = await _get_playlist_or_404(db, playlist_id)
    _ensure_playlist_access(playlist, current_user)

    skip = (page - 1) * per_page
    language = (
        current_user.ui_language
        if current_user and getattr(current_user, "ui_language", None)
        else None
    )
    items, total = await ListService(db).get_items_with_data(
        str(playlist_id), skip, per_page, language=language
    )

    return PaginatedListItemsWithDataResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=math.ceil(total / per_page) if total > 0 else 1,
    )


@playlists_router.get("/{playlist_id}/queue", response_model=PlaylistQueueResponse)
async def get_playlist_queue(
    db: DatabaseSession,
    playlist_id: UUID,
    start_item_guid: UUID | None = Query(None),
    start_index: int = Query(0, ge=0),
    current_user=Depends(get_current_user_optional),
):
    """Return an ordered playback queue for a playlist."""
    playlist = await _get_playlist_or_404(db, playlist_id)
    _ensure_playlist_access(playlist, current_user)
    return await _build_playlist_queue(
        db,
        playlist,
        start_item_guid=start_item_guid,
        start_index=start_index,
    )


@playlists_router.post("/{playlist_id}/play-on-device", response_model=DeviceCommandResponse)
async def play_playlist_on_device(
    db: DatabaseSession,
    playlist_id: UUID,
    body: PlaylistPlayOnDeviceRequest,
    current_user=Depends(get_current_user),
):
    """Build a playlist queue and send it to one of the user's device sessions."""
    from pyrate.api.v1.devices import send_device_session_play_queue

    playlist = await _get_playlist_or_404(db, playlist_id)
    _ensure_playlist_access(playlist, current_user)
    queue = await _build_playlist_queue(
        db,
        playlist,
        start_item_guid=body.start_item_guid,
        start_index=body.start_index,
    )
    if not queue.items:
        raise HTTPException(status_code=400, detail="Playlist queue is empty")

    return await send_device_session_play_queue(
        body.device_id,
        DeviceSessionPlayQueueCreate(
            items=[
                DeviceSessionPlayQueueItem(
                    media_guid=item.media_item_guid,
                    media_type=item.item_type,
                    media_title=item.title,
                )
                for item in queue.items
            ],
            start_index=queue.start_index,
            start_position_seconds=body.start_position_seconds,
            from_device_id=body.from_device_id,
        ),
        current_user,
        db,
    )


@playlists_router.post("/{playlist_id}/items", response_model=ListItemRead)
async def add_item_to_playlist(
    db: DatabaseSession,
    playlist_id: UUID,
    item_request: AddItemToListRequest,
    current_user=Depends(get_current_user),
):
    playlist = await _get_playlist_or_404(db, playlist_id)
    _ensure_playlist_owner(playlist, current_user)

    try:
        item_data = ListItemCreate(
            item_type=item_request.item_type,
            item_guid=item_request.item_guid,
            notes=item_request.notes,
            order_index=item_request.order_index,
        )
        item = await ListService(db).add_item(
            str(playlist_id), item_data, str(current_user.guid)
        )
        item.added_by = current_user
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "User %s added item %s to playlist %s",
        current_user.guid,
        item_request.item_guid,
        playlist_id,
    )
    return ListItemRead.model_validate(item)


@playlists_router.patch("/{playlist_id}/items/order", response_model=PaginatedListItemsWithDataResponse)
async def reorder_playlist_items(
    db: DatabaseSession,
    playlist_id: UUID,
    reorder: PlaylistReorderRequest,
    current_user=Depends(get_current_user),
):
    playlist = await _get_playlist_or_404(db, playlist_id)
    _ensure_playlist_owner(playlist, current_user)

    if len(set(reorder.item_ids)) != len(reorder.item_ids):
        raise HTTPException(status_code=400, detail="Duplicate playlist item ids")

    if reorder.item_ids:
        result = await db.execute(
            select(ListItem.guid).where(
                ListItem.list_guid == playlist_id,
                ListItem.guid.in_(reorder.item_ids),
            )
        )
        found_ids = {row[0] for row in result.all()}
        missing_ids = set(reorder.item_ids) - found_ids
        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail="One or more playlist items were not found",
            )

    for order_index, item_id in enumerate(reorder.item_ids):
        await db.execute(
            sa_update(ListItem)
            .where(ListItem.list_guid == playlist_id, ListItem.guid == item_id)
            .values(order_index=order_index)
        )

    await db.commit()

    items, total = await ListService(db).get_items_with_data(str(playlist_id), 0, 100)
    logger.info("User %s reordered playlist %s", current_user.guid, playlist_id)
    return PaginatedListItemsWithDataResponse(
        items=items,
        total=total,
        page=1,
        per_page=100,
        total_pages=math.ceil(total / 100) if total > 0 else 1,
    )


@playlists_router.delete("/{playlist_id}/items/{item_id}", status_code=204)
async def remove_item_from_playlist(
    db: DatabaseSession,
    playlist_id: UUID,
    item_id: UUID,
    current_user=Depends(get_current_user),
):
    playlist = await _get_playlist_or_404(db, playlist_id)
    _ensure_playlist_owner(playlist, current_user)

    try:
        await ListService(db).remove_item(str(playlist_id), str(item_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    logger.info(
        "User %s removed item %s from playlist %s",
        current_user.guid,
        item_id,
        playlist_id,
    )
