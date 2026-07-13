import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from streamarr.libraries.categories import category_for
from streamarr.models.list import ListItem
from streamarr.models.media import MediaItem
from streamarr.models.media_translation import MediaItemTranslation
from streamarr.schemas.favorite import (
    FavoriteListItem,
    FavoriteListResponse,
    FavoriteStatusResponse,
)
from streamarr.services.list import ListService

# Mapping from URL prefix to MediaType values
TYPE_PREFIX_MAP = {
    "movies": "MOVIES",
    "shows": "SHOWS",
    "games": "GAMES",
    "music": "MUSIC",
    "books": "BOOKS",
    "audiobooks": "AUDIOBOOKS",
}

# Mapping from MediaType to ListItemType
MEDIA_TYPE_TO_ITEM_TYPE = {
    "MOVIES": "MOVIE",
    "SHOWS": "SHOW",
    "GAMES": "GAME",
    "MUSIC": "MUSIC",
    "BOOKS": "BOOK",
    "AUDIOBOOKS": "AUDIOBOOK",
    "EPISODES": "EPISODE",
    "SEASONS": "SHOW",
    "ARTISTS": "MUSIC",
    "ALBUMS": "MUSIC",
    "SONGS": "MUSIC",
}


class FavoriteService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.list_service = ListService(db)

    async def get_media_item(self, type_prefix: str, item_guid: uuid.UUID) -> MediaItem:
        """Resolve media item by GUID and validate it matches the given type prefix.

        Enforces that the item's parent library category matches the prefix, so
        e.g. ``/favorites/movies/{guid}`` cannot silently toggle a game/show.
        The check is category-level (not exact media_type) so favoriting a
        season/episode under ``shows`` or an album/song under ``music`` still
        resolves correctly before ``resolve_root_item`` walks up to the root.
        """
        media_type = TYPE_PREFIX_MAP.get(type_prefix.lower())
        if media_type is None:
            raise HTTPException(status_code=404, detail="Unknown media type")

        result = await self.db.execute(
            select(MediaItem).where(MediaItem.guid == item_guid)
        )
        media_item = result.scalar_one_or_none()

        if media_item is None:
            raise HTTPException(status_code=404, detail="Media item not found")

        if category_for(media_item.media_type) != category_for(media_type):
            raise HTTPException(
                status_code=404,
                detail="Media item does not match the requested type",
            )

        return media_item

    async def resolve_root_item(self, media_item: MediaItem) -> MediaItem:
        """Walk up the parent chain and return the root (top-level) media item.

        Loads up to 3 ancestor levels in a single batch query using a recursive
        CTE, avoiding the N+1 pattern of one query per level.
        """
        if media_item.parent_guid is None:
            return media_item

        from sqlalchemy import literal_column, union_all

        # Recursive CTE: start from the immediate parent, walk up to 3 levels
        anchor = (
            select(
                MediaItem.guid,
                MediaItem.parent_guid,
                literal_column("1").label("depth"),
            )
            .where(MediaItem.guid == media_item.parent_guid)
            .cte(name="ancestors", recursive=True)
        )

        recursive = (
            select(
                MediaItem.guid,
                MediaItem.parent_guid,
                (anchor.c.depth + 1).label("depth"),
            )
            .join(anchor, MediaItem.guid == anchor.c.parent_guid)
            .where(anchor.c.depth < 3)
        )

        cte = anchor.union_all(recursive)

        # Fetch the ancestor with the highest depth (closest to root)
        root_query = (
            select(cte.c.guid)
            .order_by(cte.c.depth.desc())
            .limit(1)
        )
        result = await self.db.execute(root_query)
        root_guid = result.scalar_one_or_none()

        if root_guid is None:
            return media_item

        # Load the full MediaItem for the root
        result = await self.db.execute(
            select(MediaItem).where(MediaItem.guid == root_guid)
        )
        root_item = result.scalar_one_or_none()
        return root_item if root_item is not None else media_item

    def _get_item_type(self, media_item: MediaItem) -> str:
        """Get the ListItemType string for a media item."""
        media_type_str = (
            media_item.media_type.value
            if hasattr(media_item.media_type, "value")
            else str(media_item.media_type)
        )
        return MEDIA_TYPE_TO_ITEM_TYPE.get(media_type_str, "movie")

    async def get_status(
        self, type_prefix: str, item_guid: uuid.UUID, user_guid: uuid.UUID
    ) -> FavoriteStatusResponse:
        """Check whether a user has favorited a given media item."""
        media_item = await self.get_media_item(type_prefix, item_guid)
        root_item = await self.resolve_root_item(media_item)

        is_fav = await self.list_service.is_in_favorites(user_guid, root_item.guid)
        return FavoriteStatusResponse(
            is_favorited=is_fav,
            monitored=bool(getattr(root_item, "monitored", False)),
        )

    async def toggle(
        self, type_prefix: str, item_guid: uuid.UUID, user_guid: uuid.UUID
    ) -> FavoriteStatusResponse:
        """Toggle the favorite status for a media item."""
        media_item = await self.get_media_item(type_prefix, item_guid)
        root_item = await self.resolve_root_item(media_item)
        item_type = self._get_item_type(root_item)

        is_now_favorited = await self.list_service.toggle_favorite(
            user_guid, root_item.guid, item_type,
        )
        action = "favorited" if is_now_favorited else "unfavorited"
        logger.info("User %s %s item %s (%s)", user_guid, action, root_item.guid, item_type)

        # Queue the rclone → library promotion for this item's files so the
        # favorited copy survives remote retention. Episodes/seasons: promote
        # the item the user clicked, not root — the episode holds the file.
        # Only do this when the user's resolved permissions actually grant
        # favorites_permanent — otherwise the favourite is just a bookmark.
        if is_now_favorited:
            try:
                from streamarr.services.permission import PermissionService
                perms = await PermissionService(self.db).resolve_user_permissions(user_guid)
            except Exception as e:
                logger.warning("Failed to resolve permissions for favorite promotion: %s", e)
                perms = None

            if perms is not None and perms.favorites_permanent:
                try:
                    from streamarr.worker import promote_favorite_to_library
                    await promote_favorite_to_library.kiq(str(media_item.guid))
                except Exception as e:
                    logger.warning("Failed to queue library promotion: %s", e)

                # Backwards search: monitor the whole root subtree and
                # acquire every missing leaf at the favorites quality.
                try:
                    from streamarr.worker import backfill_favorite_monitored
                    await backfill_favorite_monitored.kiq(
                        str(root_item.guid), str(user_guid)
                    )
                except Exception as e:
                    logger.warning("Failed to queue favorites backfill: %s", e)
        else:
            # Unfavorited: release the monitoring lock for the subtree so
            # normal retention can reclaim it. Ungated — a user may have
            # lost favorites_permanent after favoriting. Never deletes files.
            try:
                from streamarr.worker import unmonitor_favorite
                await unmonitor_favorite.kiq(str(root_item.guid))
            except Exception as e:
                logger.warning("Failed to queue unmonitor: %s", e)

        try:
            from streamarr.services.viewing_history import (
                _enqueue_rec_rebuilds_for_watcher_and_friends,
            )

            await _enqueue_rec_rebuilds_for_watcher_and_friends(
                self.db, user_guid
            )
        except Exception as e:
            logger.warning("Failed to enqueue rec rebuild on favorite toggle: %s", e)

        return FavoriteStatusResponse(
            is_favorited=is_now_favorited,
            monitored=bool(getattr(root_item, "monitored", False)),
        )

    async def _apply_translations(
        self, items: list[FavoriteListItem], ui_language: str | None
    ) -> None:
        """Apply translated titles to favorite list items based on user language."""
        if not ui_language or not items:
            return

        lang = (ui_language or "en").split("-")[0].lower()
        media_guids = [item.media_item_guid for item in items]
        tr_result = await self.db.execute(
            select(MediaItemTranslation).where(
                MediaItemTranslation.media_item_guid.in_(media_guids),
                MediaItemTranslation.language == lang,
            )
        )
        tr_map = {t.media_item_guid: t for t in tr_result.scalars().all()}
        for item in items:
            t = tr_map.get(item.media_item_guid)
            if t and t.title:
                item.title = t.title

    async def list_favorites(
        self, user_guid: uuid.UUID, type_prefix: str | None = None,
        ui_language: str | None = None,
    ) -> FavoriteListResponse:
        """Return all favorites for a user, optionally filtered by media type."""
        fav_list = await self.list_service.get_or_create_favorites_list(user_guid)

        ParentItem = aliased(MediaItem)
        RootItem = aliased(MediaItem)

        poster_col = func.coalesce(
            RootItem.poster_path,
            ParentItem.poster_path,
            MediaItem.poster_path,
        )

        query = (
            select(ListItem, MediaItem, poster_col)
            .join(MediaItem, ListItem.item_guid == MediaItem.guid)
            .outerjoin(ParentItem, MediaItem.parent_guid == ParentItem.guid)
            .outerjoin(RootItem, ParentItem.parent_guid == RootItem.guid)
            .where(ListItem.list_guid == fav_list.guid)
            .order_by(ListItem.created_at.desc())
        )

        if type_prefix is not None:
            media_type = TYPE_PREFIX_MAP.get(type_prefix.lower())
            if media_type is None:
                raise HTTPException(status_code=400, detail="Unknown media type")
            query = query.where(MediaItem.media_type == media_type)

        result = await self.db.execute(query)
        rows = result.all()

        items = [
            FavoriteListItem(
                guid=list_item.guid,
                media_item_guid=media.guid,
                title=media.title,
                media_type=str(
                    media.media_type.value
                    if hasattr(media.media_type, "value")
                    else media.media_type
                ),
                poster_url=resolved_poster,
            )
            for list_item, media, resolved_poster in rows
        ]

        await self._apply_translations(items, ui_language)

        logger.debug("Listed %d favorites for user %s (type=%s)", len(items), user_guid, type_prefix)
        return FavoriteListResponse(items=items, total=len(items))
