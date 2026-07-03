"""List service for managing user lists and their items."""

import logging
import uuid

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.list import (
    List,
    ListItem,
    ListType,
    ListVisibility,
    UserListInteraction,
    UserListInteractionType,
)
from pyrate.models.media import Genre, MediaItem, media_genre_table
from pyrate.schemas.list import (
    ListCreate,
    ListItemCreate,
    ListItemWithData,
    ListSummaryRead,
    ListUpdate,
    UserListInteractionCreate,
)
from pyrate.schemas.media import MediaItemRead

logger = logging.getLogger(__name__)


def _convert_to_uuid(value: str | uuid.UUID) -> uuid.UUID:
    """Convert a string UUID to a UUID object if needed."""
    return uuid.UUID(value) if isinstance(value, str) else value


class ListService:
    """Service for managing lists, list items, and user interactions."""

    # Base filter to exclude soft-deleted lists from all queries
    _NOT_DELETED = List.deleted_at.is_(None)

    def __init__(self, db: AsyncSession):
        """Initialize the list service.

        Args:
            db: Database session
        """
        self.db = db

    # List operations
    async def get_by_id(self, list_id: str) -> List | None:
        """Get a list by ID with all relationships loaded.

        Args:
            list_id: The list GUID

        Returns:
            The list if found, None otherwise
        """
        list_uuid = _convert_to_uuid(list_id)
        result = await self.db.execute(
            select(List)
            .options(
                selectinload(List.owner),
                selectinload(List.items),
                selectinload(List.user_interactions),
            )
            .where(List.guid == list_uuid, self._NOT_DELETED)
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 20,
        list_type: ListType | None = None,
        visibility: ListVisibility | None = None,
        owner_guid: str | None = None,
        current_user_guid: str | None = None,
        current_user_is_superuser: bool = False,
        content_type: str | None = None,
        update_source: str | None = None,
        update_source_prefix: str | None = None,
    ) -> tuple[list[List], int]:
        """Get lists with filtering options.

        For private lists, only show lists owned by the current user.
        For system lists, only show to superusers when filtering by owner.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            list_type: Filter by list type
            visibility: Filter by visibility
            owner_guid: Filter by owner GUID
            current_user_guid: Current user's GUID for permission checks
            current_user_is_superuser: Whether current user is superuser

        Returns:
            Tuple of (list of lists, total count)
        """
        # Build base query — always exclude soft-deleted lists
        filters = [List.is_active, self._NOT_DELETED]

        if list_type:
            filters.append(List.list_type == list_type)

        if owner_guid:
            # When filtering by owner_guid, only show lists owned by that user
            # System lists (with owner_guid = None) should not be included
            # because "My Lists" should only show personal lists
            filters.append(List.owner_guid == _convert_to_uuid(owner_guid))

            # Hide per-user SYSTEM lists (e.g. rec:*) from default "my lists"
            # views. A caller who explicitly asks for them via list_type=SYSTEM
            # or update_source[_prefix] still gets them.
            if (
                list_type is None
                and not update_source
                and not update_source_prefix
            ):
                filters.append(List.list_type != ListType.SYSTEM)

        # Handle visibility - private lists only visible to owner
        if visibility:
            if visibility == ListVisibility.PRIVATE and current_user_guid:
                filters.append(
                    and_(
                        List.visibility == ListVisibility.PRIVATE,
                        List.owner_guid == _convert_to_uuid(current_user_guid),
                    )
                )
            else:
                filters.append(List.visibility == visibility)
        else:
            # Default: show public lists and private lists owned by current user
            if current_user_guid:
                filters.append(
                    or_(
                        List.visibility == ListVisibility.PUBLIC,
                        and_(
                            List.visibility == ListVisibility.PRIVATE,
                            List.owner_guid == _convert_to_uuid(current_user_guid),
                        ),
                    )
                )
            else:
                filters.append(List.visibility == ListVisibility.PUBLIC)

        if update_source:
            filters.append(List.update_source == update_source)
        if update_source_prefix:
            filters.append(List.update_source.like(f"{update_source_prefix}%"))

        # Filter by content type (lists containing items of this type)
        if content_type:
            filters.append(
                List.guid.in_(
                    select(ListItem.list_guid)
                    .where(ListItem.item_type == content_type)
                    .distinct()
                )
            )

        # Count query
        count_query = select(func.count(List.guid)).where(and_(*filters))
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Data query
        query = (
            select(List)
            .options(
                selectinload(List.owner),
                selectinload(List.items),
                selectinload(List.user_interactions),
            )
            .where(and_(*filters))
            .offset(skip)
            .limit(limit)
            .order_by(List.updated_at.desc())
        )

        result = await self.db.execute(query)
        lists = list(result.scalars().all())

        return lists, total

    async def get_all_admin(
        self,
        skip: int = 0,
        limit: int = 20,
        list_type: ListType | None = None,
        visibility: ListVisibility | None = None,
        search: str | None = None,
    ) -> tuple[list[List], int]:
        """Get all lists for admin view (no visibility restrictions).

        Returns all lists including private ones from all users.
        Only for use by superusers.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            list_type: Filter by list type
            visibility: Filter by visibility
            search: Search term for list name

        Returns:
            Tuple of (list of lists, total count)
        """
        filters = []

        if list_type:
            filters.append(List.list_type == list_type)

        if visibility:
            filters.append(List.visibility == visibility)

        if search:
            filters.append(List.name.ilike(f"%{search}%"))

        where_clause = and_(*filters) if filters else True

        # Count query
        count_query = select(func.count(List.guid)).where(where_clause)
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Data query
        query = (
            select(List)
            .options(
                selectinload(List.owner),
            )
            .where(where_clause)
            .offset(skip)
            .limit(limit)
            .order_by(List.updated_at.desc())
        )

        result = await self.db.execute(query)
        lists = list(result.scalars().all())

        return lists, total

    async def create(
        self,
        list_data: ListCreate,
        owner_guid: str | None = None,
        *,
        commit: bool = True,
    ) -> List:
        """Create a new list.

        Args:
            list_data: The list creation data
            owner_guid: The owner's GUID (for user lists)

        Returns:
            The created list
        """
        list_dict = list_data.model_dump()

        # Set owner for user lists
        if list_dict.get("list_type") == ListType.USER and owner_guid:
            # Convert string UUID to UUID object for proper database handling
            list_dict["owner_guid"] = _convert_to_uuid(owner_guid)
        elif list_dict.get("list_type") == ListType.SYSTEM:
            list_dict["owner_guid"] = None

        db_list = List(**list_dict)
        self.db.add(db_list)
        if commit:
            await self.db.commit()
            await self.db.refresh(db_list)
        else:
            await self.db.flush()

        # Re-query with eager loading to avoid lazy-load issues in async context
        result = await self.db.execute(
            select(List)
            .options(selectinload(List.owner), selectinload(List.items))
            .where(List.guid == db_list.guid)
        )
        created = result.scalar_one()
        logger.info("Created list %s (%s) for owner %s", created.guid, created.name, owner_guid)
        return created

    async def update(self, db_list: List, list_update: ListUpdate) -> List:
        """Update a list.

        Args:
            db_list: The existing list model
            list_update: The update data

        Returns:
            The updated list
        """
        update_data = list_update.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(db_list, key, value)

        self.db.add(db_list)
        await self.db.commit()
        await self.db.refresh(db_list)
        logger.info("Updated list %s (%s)", db_list.guid, db_list.name)

        return db_list

    async def delete(self, db_list: List) -> None:
        """Soft-delete a list (marks as deleted, purged after 30 days).

        Favorites lists cannot be deleted.

        Args:
            db_list: The list to delete
        """
        if db_list.list_type == ListType.FAVORITES:
            raise ValueError("Favorites list cannot be deleted")

        from datetime import UTC, datetime

        db_list.deleted_at = datetime.now(UTC)
        await self.db.commit()
        logger.info("Soft-deleted list %s (%s)", db_list.guid, db_list.name)

    async def restore(self, db_list: List) -> None:
        """Restore a soft-deleted list.

        Args:
            db_list: The list to restore
        """
        db_list.deleted_at = None
        await self.db.commit()

    async def purge_deleted_lists(self, retention_days: int = 30) -> int:
        """Permanently delete lists that have been soft-deleted for longer than retention_days.

        Returns:
            Number of lists purged
        """
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import delete as sa_delete

        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        result = await self.db.execute(
            sa_delete(List).where(
                List.deleted_at.isnot(None),
                List.deleted_at < cutoff,
            )
        )
        await self.db.commit()
        return result.rowcount

    async def get_lists_with_item_types(
        self, lists: list[List]
    ) -> list[ListSummaryRead]:
        """Enrich a list of List objects with their item_types.

        Performs a single batch query to get distinct item types for all lists,
        avoiding the N+1 query problem.

        Args:
            lists: The list objects to enrich

        Returns:
            List of ListSummaryRead with item_types populated
        """
        list_guids = [list_obj.guid for list_obj in lists]
        item_types_map: dict[str, list[str]] = {}
        if list_guids:
            types_result = await self.db.execute(
                select(ListItem.list_guid, ListItem.item_type)
                .where(ListItem.list_guid.in_(list_guids))
                .distinct()
            )
            for row in types_result.all():
                guid_str = str(row[0])
                if guid_str not in item_types_map:
                    item_types_map[guid_str] = []
                item_types_map[guid_str].append(row[1])

        items = []
        for list_obj in lists:
            summary = ListSummaryRead.model_validate(list_obj)
            summary.item_types = item_types_map.get(str(list_obj.guid), [])
            items.append(summary)

        return items

    async def get_items_with_data(
        self,
        list_id: str,
        skip: int = 0,
        limit: int = 50,
        language: str | None = None,
        friend_watchers_for_user: str | uuid.UUID | None = None,
    ) -> tuple[list[ListItemWithData], int]:
        """Get items in a list enriched with their media data.

        Batch-fetches media data and translations in minimal queries
        to avoid N+1 problems.

        Args:
            list_id: The list GUID
            skip: Number of records to skip
            limit: Maximum number of records to return
            language: Language code for translations (e.g. "en", "de")

        Returns:
            Tuple of (enriched items, total count)
        """
        items, total = await self.get_items(list_id, skip, limit)

        # Batch-fetch media data for all items in one query
        item_guids = [item.item_guid for item in items]
        media_map = {}
        if item_guids:
            result = await self.db.execute(
                select(MediaItem).where(MediaItem.guid.in_(item_guids))
            )
            media_map = {m.guid: m for m in result.scalars().all()}

        # Apply translations to media items
        translation_map = {}
        if item_guids and language:
            from pyrate.models.media_translation import MediaItemTranslation

            lang = language.split("-")[0].lower()
            tr_result = await self.db.execute(
                select(MediaItemTranslation).where(
                    MediaItemTranslation.media_item_guid.in_(item_guids),
                    MediaItemTranslation.language == lang,
                )
            )
            translation_map = {
                t.media_item_guid: t for t in tr_result.scalars().all()
            }

        friend_watchers_map: dict[uuid.UUID, list[dict]] = {}
        if friend_watchers_for_user and item_guids:
            friend_watchers_map = await self._get_friend_watchers_for_items(
                friend_watchers_for_user, item_guids
            )

        enriched_items = []
        for item in items:
            item_with_data = ListItemWithData.model_validate(item)
            media_data = media_map.get(item.item_guid)
            if media_data:
                t = translation_map.get(media_data.guid)
                item_with_data.item_data = {
                    "guid": str(media_data.guid),
                    "title": t.title if t and t.title else media_data.title,
                    "poster_path": media_data.poster_path,
                    "backdrop_path": media_data.backdrop_path,
                    "release_date": media_data.release_date.isoformat()
                    if media_data.release_date
                    else None,
                    "description": t.description
                    if t and t.description
                    else media_data.description,
                    "vote_average": getattr(media_data, "vote_average", None),
                }
                if friend_watchers_map:
                    watchers = friend_watchers_map.get(item.item_guid, [])
                    if watchers:
                        item_with_data.item_data["friend_watchers"] = watchers
            enriched_items.append(item_with_data)

        return enriched_items, total

    async def _get_friend_watchers_for_items(
        self,
        viewer_guid: str | uuid.UUID,
        item_guids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[dict]]:
        """For each item, return up to 5 accepted-friend viewers.

        Used to attach friend_watchers to rec:friends_watching:* list items.
        """
        from sqlalchemy import case
        from sqlalchemy import func as sa_func

        from pyrate.models.friendship import Friendship, FriendshipStatus
        from pyrate.models.user import User
        from pyrate.models.viewing_history import ViewingHistory

        viewer_uuid = _convert_to_uuid(viewer_guid)

        # Build set of accepted friend guids (both directions)
        friends_subq = (
            select(
                case(
                    (Friendship.requester_id == viewer_uuid, Friendship.addressee_id),
                    else_=Friendship.requester_id,
                ).label("friend_guid")
            )
            .where(
                Friendship.status == FriendshipStatus.accepted,
                or_(
                    Friendship.requester_id == viewer_uuid,
                    Friendship.addressee_id == viewer_uuid,
                ),
            )
            .subquery()
        )

        q = (
            select(
                ViewingHistory.media_item_guid,
                User.guid,
                User.first_name,
                User.last_name,
                User.preferred_username,
                User.picture,
                sa_func.max(ViewingHistory.last_watched_at).label("last_watched_at"),
            )
            .join(User, User.guid == ViewingHistory.user_guid)
            .where(
                ViewingHistory.media_item_guid.in_(item_guids),
                ViewingHistory.user_guid.in_(select(friends_subq.c.friend_guid)),
            )
            .group_by(
                ViewingHistory.media_item_guid,
                User.guid,
                User.first_name,
                User.last_name,
                User.preferred_username,
                User.picture,
            )
        )

        result = await self.db.execute(q)
        out: dict[uuid.UUID, list[dict]] = {}
        for (
            media_item_guid,
            user_guid,
            first_name,
            last_name,
            preferred_username,
            picture,
            last_watched_at,
        ) in result.all():
            watchers = out.setdefault(media_item_guid, [])
            if len(watchers) >= 5:
                continue
            display_name = (
                preferred_username
                or (f"{first_name} {last_name}".strip() if first_name or last_name else None)
                or "Friend"
            )
            watchers.append({
                "user_guid": str(user_guid),
                "display_name": display_name,
                "avatar_url": picture,
                "last_watched_at": last_watched_at.isoformat() if last_watched_at else None,
            })
        return out

    async def get_items_optimized(
        self, list_id: str | uuid.UUID, language: str | None = None
    ) -> list[MediaItemRead]:
        """Get all items in a list with optimized batch loading for genres.

        Loads all data in minimal queries:
        1. One query for all list items with media data (join)
        2. One query for all genres (batch)
        3. Optional translation application

        Args:
            list_id: The list GUID
            language: Language code for translations (e.g. "en-DE")

        Returns:
            List of MediaItemRead with genres attached
        """
        # Get all media items in the list in ONE query with join
        stmt = (
            select(MediaItem)
            .join(ListItem, ListItem.item_guid == MediaItem.guid)
            .where(ListItem.list_guid == list_id)
            .order_by(ListItem.created_at.desc())
        )

        result = await self.db.execute(stmt)
        media_items = result.scalars().all()

        if not media_items:
            return []

        # Batch load genres for ALL media items in ONE query
        media_guids = [item.guid for item in media_items]

        stmt = (
            select(
                media_genre_table.c.media_item_guid,
                Genre.id,
                Genre.name,
            )
            .select_from(media_genre_table)
            .join(Genre, Genre.id == media_genre_table.c.genre_id)
            .where(media_genre_table.c.media_item_guid.in_(media_guids))
        )
        result = await self.db.execute(stmt)
        genre_data = result.all()

        # Build genre map: media_guid -> [genres]
        genre_map: dict[uuid.UUID, list[dict]] = {}
        for media_item_guid, genre_id, genre_name in genre_data:
            if media_item_guid not in genre_map:
                genre_map[media_item_guid] = []
            genre_map[media_item_guid].append({"id": genre_id, "name": genre_name})

        # Convert to response schema with genres attached
        response = []
        for item in media_items:
            item_dict = {
                "guid": item.guid,
                "media_type": item.media_type,
                "title": item.title,
                "original_title": item.original_title,
                "description": item.description,
                "tagline": item.tagline,
                "release_date": item.release_date,
                "poster_path": item.poster_path,
                "backdrop_path": item.backdrop_path,
                "parent_guid": item.parent_guid,
                "sequence_number": item.sequence_number,
                "availability_status": item.availability_status,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "last_searched_at": item.last_searched_at,
                "last_metadata_updated_at": item.last_metadata_updated_at,
                "children_count": 0,
                "files": [],
                "releases": [],
                "external_ids": [],
                "genres": genre_map.get(item.guid, []),
                "extra_data": item.extra_data,
            }
            response.append(MediaItemRead(**item_dict))

        # Apply translations if language is set
        if language:
            from pyrate.services.translation import TranslationService

            ts = TranslationService(self.db)
            await ts.apply_translations(response, language)

        return response

    # List Item operations
    async def get_items(
        self, list_id: str, skip: int = 0, limit: int = 50
    ) -> tuple[list[ListItem], int]:
        """Get items in a list.

        Args:
            list_id: The list GUID
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of items, total count)
        """
        # Count query
        count_query = select(func.count(ListItem.guid)).where(
            ListItem.list_guid == _convert_to_uuid(list_id)
        )
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Data query
        query = (
            select(ListItem)
            .options(selectinload(ListItem.added_by))
            .where(ListItem.list_guid == _convert_to_uuid(list_id))
            .order_by(
                ListItem.order_index.asc().nulls_last(), ListItem.created_at.desc()
            )
            .offset(skip)
            .limit(limit)
        )

        result = await self.db.execute(query)
        items = list(result.scalars().all())

        return items, total

    async def add_item(
        self,
        list_id: str,
        item_data: ListItemCreate,
        added_by_guid: str | None = None,
    ) -> ListItem:
        """Add an item to a list.

        Args:
            list_id: The list GUID
            item_data: The item data
            added_by_guid: GUID of user adding the item

        Returns:
            The created list item

        Raises:
            ValueError: If item already exists in list
        """
        # Check if item already exists in list
        existing_item = await self.db.execute(
            select(ListItem).where(
                and_(
                    ListItem.list_guid == _convert_to_uuid(list_id),
                    ListItem.item_type == item_data.item_type,
                    ListItem.item_guid == item_data.item_guid,
                )
            )
        )

        if existing_item.scalar_one_or_none():
            raise ValueError("Item already exists in list")

        item_dict = item_data.model_dump()
        item_dict["list_guid"] = _convert_to_uuid(list_id)
        if added_by_guid:
            item_dict["added_by_guid"] = _convert_to_uuid(added_by_guid)

        db_item = ListItem(**item_dict)
        self.db.add(db_item)

        await self.db.execute(
            sa_update(List)
            .where(List.guid == _convert_to_uuid(list_id))
            .values(item_count=List.item_count + 1)
        )

        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError("Item already exists in list") from exc
        except SQLAlchemyError:
            await self.db.rollback()
            raise
        await self.db.refresh(db_item)
        logger.info("Added item %s to list %s", item_data.item_guid, list_id)

        return db_item

    async def remove_item(self, list_id: str, item_id: str) -> None:
        """Remove an item from a list.

        Args:
            list_id: The list GUID
            item_id: The item GUID

        Raises:
            ValueError: If item not found in list
        """
        result = await self.db.execute(
            select(ListItem).where(
                and_(
                    ListItem.list_guid == _convert_to_uuid(list_id),
                    ListItem.guid == _convert_to_uuid(item_id),
                )
            )
        )

        db_item = result.scalar_one_or_none()
        if not db_item:
            logger.warning("Item %s not found in list %s for removal", item_id, list_id)
            raise ValueError("Item not found in list")

        await self.db.delete(db_item)

        await self.db.execute(
            sa_update(List)
            .where(List.guid == _convert_to_uuid(list_id))
            .values(
                item_count=case(
                    (List.item_count > 0, List.item_count - 1),
                    else_=0,
                )
            )
        )

        await self.db.commit()
        logger.info("Removed item %s from list %s", item_id, list_id)

    # User List Interaction operations
    async def get_user_interaction(
        self,
        user_guid: str,
        list_guid: str,
        interaction_type: UserListInteractionType,
    ) -> UserListInteraction | None:
        """Get a specific user interaction with a list.

        Args:
            user_guid: The user GUID
            list_guid: The list GUID
            interaction_type: The type of interaction

        Returns:
            The interaction if found, None otherwise
        """
        result = await self.db.execute(
            select(UserListInteraction).where(
                and_(
                    UserListInteraction.user_guid == _convert_to_uuid(user_guid),
                    UserListInteraction.list_guid == _convert_to_uuid(list_guid),
                    UserListInteraction.interaction_type == interaction_type,
                )
            )
        )

        return result.scalar_one_or_none()

    async def create_user_interaction(
        self, interaction_data: UserListInteractionCreate
    ) -> UserListInteraction:
        """Create a user interaction with a list (like, follow, bookmark).

        Args:
            interaction_data: The interaction data

        Returns:
            The created or existing interaction
        """
        # Check if interaction already exists
        existing = await self.get_user_interaction(
            interaction_data.user_guid,
            interaction_data.list_guid,
            interaction_data.interaction_type,
        )

        if existing:
            return existing  # Already exists, return existing

        db_interaction = UserListInteraction(**interaction_data.model_dump())
        self.db.add(db_interaction)

        # Update list counters atomically
        if interaction_data.interaction_type == UserListInteractionType.LIKE:
            await self.db.execute(
                sa_update(List)
                .where(List.guid == interaction_data.list_guid)
                .values(like_count=List.like_count + 1)
            )
        elif interaction_data.interaction_type == UserListInteractionType.FOLLOW:
            await self.db.execute(
                sa_update(List)
                .where(List.guid == interaction_data.list_guid)
                .values(follow_count=List.follow_count + 1)
            )

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            existing = await self.get_user_interaction(
                interaction_data.user_guid,
                interaction_data.list_guid,
                interaction_data.interaction_type,
            )
            if existing is not None:
                return existing
            raise
        await self.db.refresh(db_interaction)

        return db_interaction

    async def remove_user_interaction(
        self,
        user_guid: str,
        list_guid: str,
        interaction_type: UserListInteractionType,
    ) -> None:
        """Remove a user interaction with a list.

        Args:
            user_guid: The user GUID
            list_guid: The list GUID
            interaction_type: The type of interaction
        """
        existing = await self.get_user_interaction(
            user_guid, list_guid, interaction_type
        )

        if not existing:
            return  # Nothing to remove

        await self.db.delete(existing)

        # Update list counters
        list_result = await self.db.execute(
            select(List).where(List.guid == _convert_to_uuid(list_guid))
        )
        db_list = list_result.scalar_one()

        if interaction_type == UserListInteractionType.LIKE:
            db_list.like_count = max(0, db_list.like_count - 1)
        elif interaction_type == UserListInteractionType.FOLLOW:
            db_list.follow_count = max(0, db_list.follow_count - 1)

        await self.db.commit()

    # User-specific list queries
    async def get_user_lists(
        self,
        user_guid: str,
        skip: int = 0,
        limit: int = 20,
        requester_guid: str | None = None,
    ) -> tuple[list[List], int]:
        """Get all lists owned by a user.

        Args:
            user_guid: The user GUID whose lists to list
            skip: Number of records to skip
            limit: Maximum number of records to return
            requester_guid: GUID of the requesting user; private lists are only
                visible when the requester is the owner

        Returns:
            Tuple of (list of lists, total count)
        """
        return await self.get_all(
            skip=skip,
            limit=limit,
            owner_guid=user_guid,
            current_user_guid=requester_guid,
        )

    async def get_or_create_system_list(
        self,
        owner_guid: str | uuid.UUID,
        update_source: str,
        name: str = "",
        description: str | None = None,
        name_translations: dict | None = None,
        context_item_guid: uuid.UUID | None = None,
    ) -> List:
        """Get or create a per-user SYSTEM list keyed by (owner, update_source).

        Used by the recommendation builder. Race-safe via
        ``uq_list_user_update_source`` partial unique index — the previous
        SELECT-then-INSERT pattern threw IntegrityError when two rebuild
        workers raced on the same user, which surfaced as "On-demand
        rebuild failed for <user>/SHOWS". We now do an upsert and re-read.
        """
        owner_uuid = _convert_to_uuid(owner_guid)

        stmt = (
            pg_insert(List)
            .values(
                name=name or update_source,
                description=description,
                name_translations=name_translations,
                list_type=ListType.SYSTEM,
                owner_guid=owner_uuid,
                visibility=ListVisibility.PRIVATE,
                is_active=True,
                auto_update=True,
                update_source=update_source,
                context_item_guid=context_item_guid,
            )
            .on_conflict_do_nothing(
                index_elements=["owner_guid", "update_source"],
                index_where=(
                    List.owner_guid.isnot(None) & List.update_source.isnot(None)
                ),
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()

        result = await self.db.execute(
            select(List)
            .options(selectinload(List.owner), selectinload(List.items))
            .where(
                List.owner_guid == owner_uuid,
                List.update_source == update_source,
                List.list_type == ListType.SYSTEM,
                self._NOT_DELETED,
            )
        )
        existing = result.scalar_one()

        # Refresh metadata if the caller passed updated values
        changed = False
        if name and existing.name != name:
            existing.name = name
            changed = True
        if description is not None and existing.description != description:
            existing.description = description
            changed = True
        if name_translations is not None and existing.name_translations != name_translations:
            existing.name_translations = name_translations
            changed = True
        if context_item_guid is not None and existing.context_item_guid != context_item_guid:
            existing.context_item_guid = context_item_guid
            changed = True
        if changed:
            await self.db.commit()
            await self.db.refresh(existing)
        return existing

    async def replace_items(
        self,
        list_guid: str | uuid.UUID,
        items: list[tuple[uuid.UUID, str, int]],
    ) -> None:
        """Bulk-replace the items of a list.

        `items` is a list of (item_guid, item_type, order_index) tuples. Any
        existing items are deleted and the new ones inserted in one commit.
        Updates list.item_count, last_auto_update, updated_at.
        """
        from datetime import UTC, datetime

        from sqlalchemy import delete as sa_delete

        list_uuid = _convert_to_uuid(list_guid)

        await self.db.execute(
            sa_delete(ListItem).where(ListItem.list_guid == list_uuid)
        )

        for item_guid, item_type, order_index in items:
            self.db.add(
                ListItem(
                    list_guid=list_uuid,
                    item_type=item_type,
                    item_guid=item_guid,
                    order_index=order_index,
                )
            )

        list_result = await self.db.execute(
            select(List).where(List.guid == list_uuid)
        )
        db_list = list_result.scalar_one()
        db_list.item_count = len(items)
        db_list.last_auto_update = datetime.now(UTC)

        await self.db.commit()

    async def get_or_create_favorites_list(self, user_guid: str | uuid.UUID) -> List:
        """Get or create the user's undeletable Favorites list.

        Each user has exactly one Favorites list (list_type=FAVORITES).
        It is auto-created on first access and cannot be deleted.
        """
        user_uuid = _convert_to_uuid(user_guid)

        result = await self.db.execute(
            select(List)
            .options(selectinload(List.items))
            .where(
                List.owner_guid == user_uuid,
                List.list_type == ListType.FAVORITES,
            )
            .limit(1)
        )
        favorites_list = result.scalars().first()

        if favorites_list is not None:
            return favorites_list

        # Create the Favorites list
        favorites_list = List(
            name="Favorites",
            description=None,
            list_type=ListType.FAVORITES,
            owner_guid=user_uuid,
            visibility=ListVisibility.PRIVATE,
            is_active=True,
        )
        self.db.add(favorites_list)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            result = await self.db.execute(
                select(List)
                .options(selectinload(List.owner), selectinload(List.items))
                .where(
                    List.owner_guid == user_uuid,
                    List.list_type == ListType.FAVORITES,
                )
                .limit(1)
            )
            return result.scalars().first()
        await self.db.refresh(favorites_list)

        # Re-query with eager loading
        result = await self.db.execute(
            select(List)
            .options(selectinload(List.owner), selectinload(List.items))
            .where(List.guid == favorites_list.guid)
        )
        return result.scalar_one()

    async def is_in_favorites(
        self, user_guid: str | uuid.UUID, media_item_guid: uuid.UUID
    ) -> bool:
        """Check if a media item is in the user's Favorites list."""
        fav_list = await self.get_or_create_favorites_list(user_guid)
        result = await self.db.execute(
            select(ListItem)
            .where(
                ListItem.list_guid == fav_list.guid,
                ListItem.item_guid == media_item_guid,
            )
            .limit(1)
        )
        return result.scalars().first() is not None

    async def toggle_favorite(
        self,
        user_guid: str | uuid.UUID,
        media_item_guid: uuid.UUID,
        item_type: str,
    ) -> bool:
        """Toggle a media item in/out of the user's Favorites list.

        Returns True if now favorited, False if removed.
        """
        from sqlalchemy import delete as sa_delete

        fav_list = await self.get_or_create_favorites_list(user_guid)

        result = await self.db.execute(
            select(ListItem)
            .where(
                ListItem.list_guid == fav_list.guid,
                ListItem.item_guid == media_item_guid,
            )
            .limit(1)
        )
        existing = result.scalars().first()

        if existing is not None:
            await self.db.execute(
                sa_delete(ListItem).where(ListItem.guid == existing.guid)
            )
            await self.db.execute(
                sa_update(List)
                .where(List.guid == fav_list.guid)
                .values(
                    item_count=case(
                        (List.item_count > 0, List.item_count - 1),
                        else_=0,
                    )
                )
            )
            await self.db.commit()
            return False

        new_item = ListItem(
            list_guid=fav_list.guid,
            item_type=item_type,
            item_guid=media_item_guid,
            added_by_guid=_convert_to_uuid(user_guid),
        )
        self.db.add(new_item)
        await self.db.execute(
            sa_update(List)
            .where(List.guid == fav_list.guid)
            .values(item_count=List.item_count + 1)
        )
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
        return True

    async def get_user_liked_lists(
        self, user_guid: str, skip: int = 0, limit: int = 20
    ) -> tuple[list[List], int]:
        """Get all lists liked by a user.

        Args:
            user_guid: The user GUID
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of lists, total count)
        """
        # Count query
        count_query = (
            select(func.count(List.guid))
            .join(UserListInteraction)
            .where(
                and_(
                    UserListInteraction.user_guid == _convert_to_uuid(user_guid),
                    UserListInteraction.interaction_type
                    == UserListInteractionType.LIKE,
                    List.is_active,
                    self._NOT_DELETED,
                )
            )
        )
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Data query
        query = (
            select(List)
            .join(UserListInteraction)
            .options(
                selectinload(List.owner),
                selectinload(List.items),
                selectinload(List.user_interactions),
            )
            .where(
                and_(
                    UserListInteraction.user_guid == _convert_to_uuid(user_guid),
                    UserListInteraction.interaction_type
                    == UserListInteractionType.LIKE,
                    List.is_active,
                    self._NOT_DELETED,
                )
            )
            .offset(skip)
            .limit(limit)
            .order_by(UserListInteraction.created_at.desc())
        )

        result = await self.db.execute(query)
        lists = list(result.scalars().all())

        return lists, total
