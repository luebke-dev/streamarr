import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from streamarr.models.list import (
    ListItemType,
    ListType,
    ListVisibility,
    UserListInteractionType,
)
from streamarr.schemas.base import PaginatedResponse, BaseSchema

if TYPE_CHECKING:
    from .user import UserRead


class ListBase(BaseSchema):
    name: str
    description: str | None = None
    list_type: ListType
    visibility: ListVisibility = ListVisibility.PRIVATE
    auto_update: bool = False
    update_source: str | None = None
    tags: str | None = None
    poster_path: str | None = None
    name_translations: dict[str, str] | None = None
    description_translations: dict[str, str] | None = None


class ListCreate(ListBase):
    name: str
    list_type: ListType


class ListUpdate(BaseSchema):
    name: str | None = None
    description: str | None = None
    visibility: ListVisibility | None = None
    auto_update: bool | None = None
    update_source: str | None = None
    tags: str | None = None
    poster_path: str | None = None
    name_translations: dict[str, str] | None = None
    description_translations: dict[str, str] | None = None


class ListItemBase(BaseSchema):
    item_type: ListItemType
    item_guid: uuid.UUID
    order_index: int | None = None
    notes: str | None = None


class ListItemCreate(ListItemBase):
    item_type: ListItemType
    item_guid: uuid.UUID


class ListItemRead(ListItemBase):
    guid: uuid.UUID
    created_at: datetime
    list_guid: uuid.UUID
    added_by_guid: uuid.UUID | None = None
    added_by: "UserRead | None" = None


class UserListInteractionBase(BaseSchema):
    interaction_type: UserListInteractionType


class UserListInteractionCreate(UserListInteractionBase):
    user_guid: uuid.UUID
    list_guid: uuid.UUID
    interaction_type: UserListInteractionType


class UserListInteractionRead(UserListInteractionBase):
    guid: uuid.UUID
    created_at: datetime
    user_guid: uuid.UUID
    list_guid: uuid.UUID


# List read schema with all relationships
class ListRead(ListBase):
    guid: uuid.UUID
    created_at: datetime
    updated_at: datetime
    owner_guid: uuid.UUID | None = None
    is_active: bool
    last_auto_update: datetime | None = None
    item_count: int = 0
    like_count: int = 0
    follow_count: int = 0

    # Relationships (optional for performance)
    owner: "UserRead | None" = None
    items: list[ListItemRead] = []
    user_interactions: list[UserListInteractionRead] = []


# Simplified list read for list views (without full items/interactions)
class ListSummaryRead(BaseSchema):
    guid: uuid.UUID
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None = None
    list_type: ListType
    visibility: ListVisibility
    owner_guid: uuid.UUID | None = None
    is_active: bool
    auto_update: bool
    update_source: str | None = None
    last_auto_update: datetime | None = None
    item_count: int = 0
    like_count: int = 0
    follow_count: int = 0
    poster_path: str | None = None
    tags: str | None = None
    item_types: list[str] = []
    name_translations: dict[str, str] | None = None
    description_translations: dict[str, str] | None = None

    owner: "UserRead | None" = None


class PaginatedListsResponse(PaginatedResponse[ListSummaryRead]):
    pass


class PaginatedListItemsResponse(PaginatedResponse[ListItemRead]):
    pass


class AddItemToListRequest(BaseModel):
    item_type: ListItemType
    item_guid: uuid.UUID
    notes: str | None = None
    order_index: int | None = None


class ListInteractionRequest(BaseModel):
    interaction_type: UserListInteractionType


class ListStatsResponse(BaseSchema):
    list_guid: uuid.UUID
    item_count: int
    like_count: int
    follow_count: int
    created_at: datetime
    updated_at: datetime
    last_auto_update: datetime | None = None


class ListItemWithData(ListItemRead):
    """List item with the resolved media payload that the API layer attaches."""

    item_data: dict | None = None


class PaginatedListItemsWithDataResponse(PaginatedResponse[ListItemWithData]):
    pass


class SystemListCreate(BaseSchema):
    name: str
    description: str | None = None
    update_source: str  # Required for system lists
    auto_update: bool = True
    visibility: ListVisibility = ListVisibility.PUBLIC
    tags: str | None = None
    poster_path: str | None = None
    name_translations: dict[str, str] | None = None
    description_translations: dict[str, str] | None = None


class SystemListUpdate(BaseSchema):
    name: str | None = None
    description: str | None = None
    update_source: str | None = None
    auto_update: bool | None = None
    visibility: ListVisibility | None = None
    tags: str | None = None
    poster_path: str | None = None
    name_translations: dict[str, str] | None = None
    description_translations: dict[str, str] | None = None


# User interaction summary
class UserListInteractionSummary(BaseSchema):
    user_guid: uuid.UUID
    list_guid: uuid.UUID
    has_liked: bool = False
    has_followed: bool = False
    has_bookmarked: bool = False
    interaction_date: datetime | None = None


# List with user interaction status (for authenticated users)
class ListWithUserInteraction(ListSummaryRead):
    user_interaction: UserListInteractionSummary | None = None
