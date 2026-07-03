"""Trailer browsing endpoints."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import selectinload

from pyrate.api.dependencies import CurrentUser, DatabaseSession, UserPermissionsDep
from pyrate.api.v1.media import MediaTrailer, _trailer_candidates
from pyrate.models.media import MediaItem, MediaType
from pyrate.schemas.media import MediaItemSummary
from pyrate.services.permission import MEDIA_TYPE_TO_LIBRARY
from pyrate.utils.age_rating import is_allowed

router = APIRouter()


class TrailerBrowseItem(BaseModel):
    """A visible library item with metadata-backed trailers."""

    media_item: MediaItemSummary
    trailers: list[MediaTrailer]
    trailer_count: int


class TrailerBrowseResponse(BaseModel):
    """Paginated trailer browse response."""

    items: list[TrailerBrowseItem]
    total: int
    skip: int
    limit: int


def _allowed_media_types(
    current_user,
    permissions,
    requested_type: MediaType | None,
) -> list[MediaType]:
    if requested_type:
        library_name = MEDIA_TYPE_TO_LIBRARY.get(requested_type.value)
        if (
            not current_user.is_superuser
            and library_name
            and library_name not in permissions.allowed_libraries
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Access denied to {library_name} library",
            )
        return [requested_type]

    if current_user.is_superuser:
        return list(MediaType)

    return [
        media_type
        for media_type in MediaType
        if MEDIA_TYPE_TO_LIBRARY.get(media_type.value) in permissions.allowed_libraries
    ]


@router.get("", response_model=TrailerBrowseResponse)
async def browse_trailers(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    media_type: MediaType | None = Query(None, description="Filter by media type"),
    search_term: str | None = Query(None, max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Return visible media items that have metadata-backed trailers."""
    allowed_media_types = _allowed_media_types(current_user, permissions, media_type)
    if not allowed_media_types:
        return TrailerBrowseResponse(items=[], total=0, skip=skip, limit=limit)

    conditions = [
        MediaItem.media_type.in_(allowed_media_types),
        MediaItem.parent_guid.is_(None),
        MediaItem.extra_data.isnot(None),
        or_(
            MediaItem.extra_data.ilike("%trailers%"),
            MediaItem.extra_data.ilike("%remote_trailers%"),
            MediaItem.extra_data.ilike("%video_provider_results%"),
            MediaItem.extra_data.ilike("%videos%"),
        ),
    ]
    if not current_user.is_superuser:
        conditions.append(
            or_(
                MediaItem.min_age.is_(None),
                MediaItem.min_age <= current_user.parental_max_age,
            )
            if current_user.parental_max_age is not None
            else MediaItem.guid.isnot(None)
        )
    if search_term:
        pattern = f"%{search_term.strip()}%"
        conditions.append(
            or_(
                MediaItem.title.ilike(pattern),
                MediaItem.original_title.ilike(pattern),
            )
        )

    result = await db.execute(
        select(MediaItem)
        .options(selectinload(MediaItem.genres), selectinload(MediaItem.platforms))
        .where(*conditions)
        .order_by(desc(MediaItem.created_at))
        .limit(skip + limit + 100)
    )
    candidates = list(result.scalars().unique().all())

    items: list[TrailerBrowseItem] = []
    total = 0
    for media_item in candidates:
        if not current_user.is_superuser and not is_allowed(
            media_item.min_age,
            current_user.parental_max_age,
        ):
            continue
        trailers = [MediaTrailer(**candidate) for candidate in _trailer_candidates(media_item)]
        if not trailers:
            continue
        if total >= skip and len(items) < limit:
            items.append(
                TrailerBrowseItem(
                    media_item=MediaItemSummary.model_validate(media_item),
                    trailers=trailers,
                    trailer_count=len(trailers),
                )
            )
        total += 1

    return TrailerBrowseResponse(items=items, total=total, skip=skip, limit=limit)
