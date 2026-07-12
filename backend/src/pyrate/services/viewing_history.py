"""
Viewing History Service

Tracks and manages user viewing progress across media items.
"""

import json
import logging
import math
import uuid

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.device import Device
from pyrate.models.friendship import Friendship, FriendshipStatus
from pyrate.models.media import MediaItem, MediaType
from pyrate.models.viewing_history import ViewingHistory


async def _enqueue_rec_rebuilds_for_watcher_and_friends(
    db: AsyncSession, user_guid: uuid.UUID
) -> None:
    """Fire rebuild_user_recommendations for the watcher and all accepted
    friends so their rec:friends_watching:* lists refresh on the next
    on-demand rebuild (Redis-debounced 5 min)."""
    try:
        from pyrate.worker import rebuild_user_recommendations

        targets: set[str] = {str(user_guid)}
        friend_q = await db.execute(
            select(
                case(
                    (Friendship.requester_id == user_guid, Friendship.addressee_id),
                    else_=Friendship.requester_id,
                )
            ).where(
                Friendship.status == FriendshipStatus.accepted,
                or_(
                    Friendship.requester_id == user_guid,
                    Friendship.addressee_id == user_guid,
                ),
            )
        )
        for (friend_guid,) in friend_q.all():
            targets.add(str(friend_guid))

        for target in targets:
            await rebuild_user_recommendations.kiq(target)
    except Exception as e:
        logging.getLogger(__name__).warning(
            "Failed to enqueue rec rebuilds for %s: %s", user_guid, e
        )

logger = logging.getLogger(__name__)

# Thresholds for auto-completion detection
COMPLETION_THRESHOLD = 90.0
UNCOMPLETE_THRESHOLD = 85.0

# Eager-loads for viewing history queries. The MediaItem branches reuse the
# canonical shape from services/library so all serializers see the same
# relationships pre-fetched (skipping any of these returns 500 with a
# MissingGreenlet because Pydantic model_validate runs outside the session).
from pyrate.services.library import MEDIA_ITEM_LOAD_OPTIONS

_MEDIA_ITEM_LOAD_OPTIONS = (
    selectinload(ViewingHistory.media_item).options(*MEDIA_ITEM_LOAD_OPTIONS),
    selectinload(ViewingHistory.media_item)
    .selectinload(MediaItem.parent)
    .selectinload(MediaItem.parent),
)


def _extract_episode_hierarchy(media_item: MediaItem | None) -> dict:
    """Extract content type and episode hierarchy info from a media item."""
    result = {
        "content_type": "movie",
        "movie_guid": None,
        "episode_guid": None,
        "show_title": None,
        "season_number": None,
        "episode_number": None,
    }

    if not media_item:
        return result

    if media_item.media_type == MediaType.MOVIES:
        result["content_type"] = "movie"
        result["movie_guid"] = media_item.guid
    elif media_item.parent_guid:
        result["content_type"] = "episode"
        result["episode_guid"] = media_item.guid
        result["episode_number"] = media_item.sequence_number
        season = media_item.parent
        if season:
            result["season_number"] = season.sequence_number
            show = season.parent
            if show:
                result["show_title"] = show.title
    else:
        result["content_type"] = media_item.media_type.value.lower()
        result["movie_guid"] = media_item.guid

    return result


def _calculate_progress(progress_seconds: float, duration_seconds: float | None) -> tuple[float, bool]:
    """Calculate progress percentage and completion status.
    Returns (progress_percentage, is_completed).
    """
    if not duration_seconds or duration_seconds <= 0:
        return 0.0, False
    pct = min(100.0, (progress_seconds / duration_seconds) * 100.0)
    return pct, pct >= COMPLETION_THRESHOLD


def _load_history_extra_data(history: ViewingHistory | None) -> dict:
    """Parse a history row's JSON ``extra_data`` into a dict (empty if absent)."""
    if not history or not history.extra_data:
        return {}
    try:
        data = json.loads(history.extra_data)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get_playback_preferences(history: ViewingHistory | None) -> dict:
    """The ``playback_preferences`` sub-dict stored in a history row's extra data."""
    extra_data = _load_history_extra_data(history)
    raw_preferences = extra_data.get("playback_preferences")
    return raw_preferences if isinstance(raw_preferences, dict) else {}


class ViewingHistoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_paginated(
        self,
        user_guid: uuid.UUID,
        content_guid: uuid.UUID | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """Get paginated viewing history for a user. Returns dict with items, total, page, per_page, total_pages."""
        skip = (page - 1) * per_page

        query = (
            select(ViewingHistory)
            .where(ViewingHistory.user_guid == user_guid)
            .options(*_MEDIA_ITEM_LOAD_OPTIONS)
            .order_by(ViewingHistory.last_watched_at.desc())
        )

        count_query = select(func.count(ViewingHistory.guid)).where(
            ViewingHistory.user_guid == user_guid
        )

        if content_guid:
            query = query.where(ViewingHistory.media_item_guid == content_guid)
            count_query = count_query.where(ViewingHistory.media_item_guid == content_guid)

        total = await self.db.scalar(count_query) or 0
        total_pages = math.ceil(total / per_page) if total > 0 else 1

        result = await self.db.execute(query.offset(skip).limit(per_page))
        return {
            "items": result.scalars().all(),
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    async def create_or_update(
        self,
        user_guid: uuid.UUID,
        media_item_guid: uuid.UUID,
        progress_seconds: float,
        duration_seconds: float | None = None,
        progress_percentage: float | None = None,
        extra_data: str | None = None,
    ) -> ViewingHistory:
        """Create or update viewing history for a media item.

        For books, `progress_percentage` can be set directly (page progress)
        and `extra_data` can store the EPUB CFI position.

        Raises ValueError with codes: "media_item_not_found"
        """
        media_item = await self.db.get(MediaItem, media_item_guid)
        if not media_item:
            logger.debug("Media item not found for viewing history: media_item_guid=%s", media_item_guid)
            raise ValueError("media_item_not_found")

        query = select(ViewingHistory).where(
            ViewingHistory.user_guid == user_guid,
            ViewingHistory.media_item_guid == media_item_guid,
        )
        result = await self.db.execute(query)
        existing = result.scalar_one_or_none()

        if existing:
            was_completed = existing.is_completed
            existing.progress_seconds = progress_seconds
            if duration_seconds:
                existing.duration_seconds = duration_seconds

            # For books: use direct percentage if provided
            if progress_percentage is not None:
                existing.progress_percentage = progress_percentage
                existing.is_completed = progress_percentage >= COMPLETION_THRESHOLD
            elif existing.duration_seconds and existing.duration_seconds > 0:
                pct, completed = _calculate_progress(existing.progress_seconds, existing.duration_seconds)
                existing.progress_percentage = pct
                if completed:
                    existing.is_completed = True
                elif pct < UNCOMPLETE_THRESHOLD:
                    existing.is_completed = False

            if extra_data is not None:
                existing.extra_data = extra_data

            await self.db.commit()
            await self.db.refresh(existing)
            logger.debug("Updated viewing history user=%s media=%s progress=%.1f%%", user_guid, media_item_guid, existing.progress_percentage)
            if existing.is_completed and not was_completed:
                await _enqueue_rec_rebuilds_for_watcher_and_friends(self.db, user_guid)
            return existing

        pct, is_completed = _calculate_progress(progress_seconds, duration_seconds)
        if progress_percentage is not None:
            pct = progress_percentage
            is_completed = progress_percentage >= COMPLETION_THRESHOLD

        new_history = ViewingHistory(
            user_guid=user_guid,
            media_item_guid=media_item_guid,
            progress_seconds=progress_seconds,
            duration_seconds=duration_seconds,
            progress_percentage=pct,
            is_completed=is_completed,
            extra_data=extra_data,
        )

        self.db.add(new_history)
        await self.db.commit()
        await self.db.refresh(new_history)
        logger.debug("Created viewing history user=%s media=%s progress=%.1f%%", user_guid, media_item_guid, pct)
        if is_completed:
            await _enqueue_rec_rebuilds_for_watcher_and_friends(self.db, user_guid)
        return new_history

    async def update_playback_preferences(
        self,
        *,
        user_guid: uuid.UUID,
        media_item_guid: uuid.UUID,
        preference_updates: dict[str, object | None],
        history: ViewingHistory | None = None,
    ) -> ViewingHistory:
        """Persist per-item playback preferences on the user's history row.

        ``preference_updates`` maps a preference key to its new value; a value
        of ``None`` removes that key. Only the keys present in the mapping are
        touched. Creates the history row if it does not exist yet. Commits.
        """
        if history is None:
            history = await self.get_history_entry(user_guid, media_item_guid)
        if history is None:
            history = ViewingHistory(
                user_guid=user_guid,
                media_item_guid=media_item_guid,
                progress_seconds=0,
                duration_seconds=None,
                progress_percentage=0.0,
                is_completed=False,
            )
            self.db.add(history)

        extra_data = _load_history_extra_data(history)
        preferences = get_playback_preferences(history)

        for preference_key, value in preference_updates.items():
            if value is None:
                preferences.pop(preference_key, None)
            else:
                preferences[preference_key] = value

        if preferences:
            extra_data["playback_preferences"] = preferences
        else:
            extra_data.pop("playback_preferences", None)

        history.extra_data = json.dumps(extra_data) if extra_data else None
        await self.db.commit()
        await self.db.refresh(history)
        return history

    async def delete(self, user_guid: uuid.UUID, history_guid: uuid.UUID) -> None:
        """Delete a viewing history record.

        Raises ValueError with codes: "not_found"
        """
        query = select(ViewingHistory).where(
            ViewingHistory.guid == history_guid,
            ViewingHistory.user_guid == user_guid,
        )
        result = await self.db.execute(query)
        history = result.scalar_one_or_none()

        if not history:
            raise ValueError("not_found")

        await self.db.delete(history)
        await self.db.commit()

    async def get_continue_watching(
        self,
        user_guid: uuid.UUID,
        content_type: str | None = None,
        limit: int = 10,
    ) -> list[ViewingHistory]:
        """Get in-progress items for continue watching, deduplicated by show."""
        fetch_limit = limit * 10
        query = (
            select(ViewingHistory)
            .where(
                ViewingHistory.user_guid == user_guid,
                ViewingHistory.is_completed == False,  # noqa: E712
                # Games never accumulate a progress_percentage (Lightrays
                # sessions have no duration), so gate them on "not completed"
                # alone — a game you launched is always continuable.
                or_(
                    ViewingHistory.progress_percentage > 0,
                    ViewingHistory.media_item.has(
                        MediaItem.media_type == MediaType.GAMES
                    ),
                ),
            )
            .options(*_MEDIA_ITEM_LOAD_OPTIONS)
            .order_by(ViewingHistory.last_watched_at.desc())
            .limit(fetch_limit)
        )

        if content_type == "movie":
            query = query.where(
                ViewingHistory.media_item.has(MediaItem.media_type == MediaType.MOVIES)
            )
        elif content_type == "episode":
            query = query.where(
                ViewingHistory.media_item.has(
                    and_(
                        MediaItem.media_type == MediaType.SHOWS,
                        MediaItem.parent_guid.isnot(None),
                    )
                )
            )
        elif content_type == "game":
            query = query.where(
                ViewingHistory.media_item.has(MediaItem.media_type == MediaType.GAMES)
            )
        elif content_type == "music":
            query = query.where(
                ViewingHistory.media_item.has(MediaItem.media_type == MediaType.SONGS)
            )
        elif content_type == "book":
            query = query.where(
                ViewingHistory.media_item.has(MediaItem.media_type == MediaType.BOOKS)
            )

        result = await self.db.execute(query)
        history_items = result.scalars().all()

        # Deduplicate: one entry per show/movie
        deduplicated: list[ViewingHistory] = []
        seen_keys: set[uuid.UUID] = set()

        for item in history_items:
            if len(deduplicated) >= limit:
                break

            dedup_key = self._get_dedup_key(item)
            if dedup_key and dedup_key in seen_keys:
                continue
            if dedup_key:
                seen_keys.add(dedup_key)

            deduplicated.append(item)

        return deduplicated

    async def get_recently_watched(
        self, user_guid: uuid.UUID, limit: int = 10
    ) -> list[ViewingHistory]:
        """Get recently watched items for a user."""
        query = (
            select(ViewingHistory)
            .where(ViewingHistory.user_guid == user_guid)
            .options(*_MEDIA_ITEM_LOAD_OPTIONS)
            .order_by(ViewingHistory.last_watched_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_stats(self, user_guid: uuid.UUID) -> dict:
        """Get viewing statistics for a user."""
        total_watched = await self.db.scalar(
            select(func.count(ViewingHistory.guid)).where(
                ViewingHistory.user_guid == user_guid
            )
        ) or 0

        total_movies_watched = await self.db.scalar(
            select(func.count(ViewingHistory.guid))
            .join(MediaItem)
            .where(
                ViewingHistory.user_guid == user_guid,
                MediaItem.media_type == MediaType.MOVIES,
                ViewingHistory.is_completed == True,  # noqa: E712
            )
        ) or 0

        total_episodes_watched = await self.db.scalar(
            select(func.count(ViewingHistory.guid))
            .join(MediaItem)
            .where(
                ViewingHistory.user_guid == user_guid,
                MediaItem.media_type == MediaType.SHOWS,
                MediaItem.parent_guid.isnot(None),
                ViewingHistory.is_completed == True,  # noqa: E712
            )
        ) or 0

        total_watch_time_seconds = await self.db.scalar(
            select(func.sum(ViewingHistory.progress_seconds)).where(
                ViewingHistory.user_guid == user_guid
            )
        ) or 0

        completed_content = await self.db.scalar(
            select(func.count(ViewingHistory.guid)).where(
                ViewingHistory.user_guid == user_guid,
                ViewingHistory.is_completed == True,  # noqa: E712
            )
        ) or 0

        in_progress_content = await self.db.scalar(
            select(func.count(ViewingHistory.guid)).where(
                ViewingHistory.user_guid == user_guid,
                ViewingHistory.is_completed == False,  # noqa: E712
                ViewingHistory.progress_seconds > 0,
            )
        ) or 0

        return {
            "total_watched": total_watched,
            "total_movies_watched": total_movies_watched,
            "total_episodes_watched": total_episodes_watched,
            "total_watch_time_seconds": total_watch_time_seconds,
            "total_watch_time_hours": round(total_watch_time_seconds / 3600, 2),
            "completed_content": completed_content,
            "in_progress_content": in_progress_content,
        }

    @staticmethod
    def _get_dedup_key(item: ViewingHistory) -> uuid.UUID | None:
        """Get deduplication key: show guid for episodes, media_item_guid for others."""
        if not item.media_item:
            return None
        if item.media_item.parent_guid:
            season = item.media_item.parent
            if season and season.parent:
                return season.parent.guid
        return item.media_item_guid

    # ── Read helpers (moved out of the router; endpoints keep response building) ──

    async def get_user_device(
        self, user_guid: uuid.UUID, device_id: str
    ) -> Device | None:
        """Device owned by ``user_guid`` with the given client ``device_id``."""
        result = await self.db.execute(
            select(Device).where(
                Device.user_id == user_guid,
                Device.device_id == device_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_top_level_shows(
        self, show_guid: uuid.UUID | None = None, limit: int = 20
    ) -> list[MediaItem]:
        """Top-level show items (optionally one show), title-ordered."""
        query = select(MediaItem).where(
            MediaItem.media_type == MediaType.SHOWS,
            MediaItem.parent_guid.is_(None),
        )
        if show_guid:
            query = query.where(MediaItem.guid == show_guid)
        query = query.order_by(MediaItem.title.asc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_child_items(self, parent_guid: uuid.UUID) -> list[MediaItem]:
        """Direct children of a media item, sequence/creation ordered."""
        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.parent_guid == parent_guid)
            .order_by(MediaItem.sequence_number.asc(), MediaItem.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_child_items_of(
        self, parent_guids: list[uuid.UUID]
    ) -> list[MediaItem]:
        """All children whose parent is in ``parent_guids`` (unordered)."""
        result = await self.db.execute(
            select(MediaItem).where(MediaItem.parent_guid.in_(parent_guids))
        )
        return list(result.scalars().all())

    async def get_user_history_for_items(
        self, user_guid: uuid.UUID, item_guids: list[uuid.UUID]
    ) -> list[ViewingHistory]:
        """User's history rows for ``item_guids``, newest-watched first."""
        result = await self.db.execute(
            select(ViewingHistory)
            .where(
                ViewingHistory.user_guid == user_guid,
                ViewingHistory.media_item_guid.in_(item_guids),
            )
            .order_by(ViewingHistory.last_watched_at.desc())
        )
        return list(result.scalars().all())

    async def get_history_entry(
        self, user_guid: uuid.UUID, media_item_guid: uuid.UUID
    ) -> ViewingHistory | None:
        """The user's history row for a single item, or ``None``."""
        result = await self.db.execute(
            select(ViewingHistory).where(
                ViewingHistory.user_guid == user_guid,
                ViewingHistory.media_item_guid == media_item_guid,
            )
        )
        return result.scalar_one_or_none()

    async def list_recent_sessions(
        self, user_guid: uuid.UUID, limit: int
    ) -> list[ViewingHistory]:
        """Most-recently-updated history rows for the user (session source)."""
        result = await self.db.execute(
            select(ViewingHistory)
            .where(ViewingHistory.user_guid == user_guid)
            .order_by(ViewingHistory.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
