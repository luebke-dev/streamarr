"""
User Service

Handles all user-related business logic and database operations.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from streamarr.auth.jwt_handler import jwt_handler
from streamarr.models.media import MediaItem, MediaType
from streamarr.models.user import User
from streamarr.models.viewing_history import ViewingHistory
from streamarr.schemas.user import UserCreate, UserUpdate


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_users(
        self, *, skip: int = 0, limit: int = 50
    ) -> list[User]:
        """Return a paginated list of users ordered by creation date."""
        result = await self.db.execute(
            select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_guid(self, user_guid: uuid.UUID) -> User | None:
        """Fetch a single user by GUID, or None if not found."""
        stmt = select(User).where(User.guid == user_guid)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user(self, user_create: UserCreate) -> User:
        """Create a new user, hashing the password if provided."""
        user_data = user_create.model_dump(exclude={"password"})

        if user_create.password:
            user_data["hashed_password"] = jwt_handler.get_password_hash(
                user_create.password
            )

        db_user = User(**user_data)
        self.db.add(db_user)
        await self.db.commit()
        await self.db.refresh(db_user)
        logger.info("Created user %s (%s)", db_user.guid, db_user.email)
        return db_user

    async def update_user(
        self, user: User, user_update: UserUpdate
    ) -> User:
        """Apply partial updates to an existing user model and persist."""
        update_data = user_update.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if hasattr(user, field):
                setattr(user, field, value)

        await self.db.commit()
        await self.db.refresh(user)
        logger.info("Updated user %s, fields: %s", user.guid, list(update_data.keys()))
        return user

    async def delete_user(self, user: User) -> None:
        """Delete a user from the database."""
        logger.info("Deleted user %s (%s)", user.guid, user.email)
        await self.db.delete(user)
        await self.db.commit()

    async def change_password(self, user: User, new_password: str) -> None:
        """Hash and persist a new password for the given user."""
        user.hashed_password = jwt_handler.get_password_hash(new_password)
        await self.db.commit()
        logger.info("Changed password for user %s", user.guid)

    async def update_language_settings(
        self, user: User, update_data: dict
    ) -> User:
        """Update language-related fields on the user."""
        for field, value in update_data.items():
            if hasattr(user, field):
                setattr(user, field, value)
        await self.db.commit()
        await self.db.refresh(user)
        logger.info("Updated language settings for user %s", user.guid)
        return user

    async def update_codec_settings(
        self, user: User, codec_data: dict
    ) -> User:
        """Merge codec settings into quality_preferences and persist."""
        qp = dict(user.quality_preferences or {})
        qp.update(codec_data)
        user.quality_preferences = qp
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_playback_preferences(
        self, user: User, prefs_data: dict
    ) -> User:
        """Replace playback_preferences on the user and persist."""
        user.playback_preferences = prefs_data
        await self.db.commit()
        await self.db.refresh(user)
        logger.info("Updated playback preferences for user %s", user.guid)
        return user

    async def update_gaming_preferences(
        self, user: User, prefs_data: dict
    ) -> User:
        """Merge gaming_preferences on the user and persist."""
        merged = dict(user.gaming_preferences or {})
        merged.update(prefs_data)
        user.gaming_preferences = merged
        await self.db.commit()
        await self.db.refresh(user)
        logger.info("Updated gaming preferences for user %s", user.guid)
        return user

    async def update_display_preferences(
        self, user: User, preference_key: str, prefs_data: dict
    ) -> User:
        """Update one display-preference entry and persist."""
        merged = dict(user.display_preferences or {})
        merged[preference_key] = prefs_data
        user.display_preferences = merged
        await self.db.commit()
        await self.db.refresh(user)
        logger.info(
            "Updated display preferences for user %s key %s",
            user.guid,
            preference_key,
        )
        return user

    async def update_permission_overrides(
        self, user: User, overrides: dict
    ) -> User:
        """Apply permission override fields to user and persist."""
        for field, value in overrides.items():
            setattr(user, field, value)
        await self.db.commit()
        await self.db.refresh(user)
        logger.info("Updated permission overrides for user %s, fields: %s", user.guid, list(overrides.keys()))
        return user

    async def get_user_stats(self, user_guid: uuid.UUID) -> dict:
        """Calculate viewing statistics for a user.

        Returns a dict with keys matching UserViewingStats fields.
        """
        total_query = select(func.count(ViewingHistory.guid)).where(
            ViewingHistory.user_guid == user_guid
        )
        total_watched = await self.db.scalar(total_query) or 0

        movies_query = (
            select(func.count(ViewingHistory.guid))
            .join(MediaItem)
            .where(
                ViewingHistory.user_guid == user_guid,
                MediaItem.media_type == MediaType.MOVIES,
                ViewingHistory.is_completed == True,  # noqa: E712
            )
        )
        total_movies_watched = await self.db.scalar(movies_query) or 0

        episodes_query = (
            select(func.count(ViewingHistory.guid))
            .join(MediaItem)
            .where(
                ViewingHistory.user_guid == user_guid,
                MediaItem.media_type == MediaType.SHOWS,
                MediaItem.parent_guid.isnot(None),
                ViewingHistory.is_completed == True,  # noqa: E712
            )
        )
        total_episodes_watched = await self.db.scalar(episodes_query) or 0

        watch_time_query = select(func.sum(ViewingHistory.progress_seconds)).where(
            ViewingHistory.user_guid == user_guid
        )
        total_watch_time_seconds = await self.db.scalar(watch_time_query) or 0
        total_watch_time_hours = round(total_watch_time_seconds / 3600, 2)

        completed_query = select(func.count(ViewingHistory.guid)).where(
            ViewingHistory.user_guid == user_guid,
            ViewingHistory.is_completed == True,  # noqa: E712
        )
        completed_content = await self.db.scalar(completed_query) or 0

        in_progress_query = select(func.count(ViewingHistory.guid)).where(
            ViewingHistory.user_guid == user_guid,
            ViewingHistory.is_completed == False,  # noqa: E712
            ViewingHistory.progress_seconds > 0,
        )
        in_progress_content = await self.db.scalar(in_progress_query) or 0

        logger.debug(
            "User %s stats: %d watched, %.2f hours",
            user_guid, total_watched, total_watch_time_hours,
        )
        return {
            "total_watched": total_watched,
            "total_movies_watched": total_movies_watched,
            "total_episodes_watched": total_episodes_watched,
            "total_watch_time_seconds": total_watch_time_seconds,
            "total_watch_time_hours": total_watch_time_hours,
            "completed_content": completed_content,
            "in_progress_content": in_progress_content,
        }
