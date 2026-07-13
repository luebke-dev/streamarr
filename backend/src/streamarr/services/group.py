import logging
import uuid

from sqlalchemy import delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

from streamarr.models.group import Group, UserGroupLink
from streamarr.models.user import User
from streamarr.schemas.group import (
    GroupCreate,
    GroupRead,
    GroupUpdate,
    UserPermissions,
    UserWithGroups,
)


class GroupService:
    """Service for managing user groups and permissions"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_group(self, group_data: GroupCreate) -> Group:
        """Create a new group"""
        group = Group(**group_data.model_dump())
        self.db.add(group)
        await self.db.commit()
        await self.db.refresh(group)
        logger.info("Created group %s (%s)", group.guid, group.name)
        return group

    async def get_group(self, group_id: uuid.UUID) -> Group | None:
        """Get a group by ID"""
        result = await self.db.execute(select(Group).where(Group.guid == group_id))
        return result.scalar_one_or_none()

    async def get_group_by_name(self, name: str) -> Group | None:
        """Get a group by name"""
        result = await self.db.execute(select(Group).where(Group.name == name))
        return result.scalar_one_or_none()

    async def list_groups(
        self, skip: int = 0, limit: int = 100, include_inactive: bool = False
    ) -> list[Group]:
        """List all groups"""
        query = select(Group)

        if not include_inactive:
            query = query.where(Group.is_active)

        query = query.offset(skip).limit(limit).order_by(Group.name)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_group(
        self, group_id: uuid.UUID, group_data: GroupUpdate
    ) -> Group | None:
        """Update a group"""
        group = await self.get_group(group_id)
        if not group:
            logger.warning("Group %s not found for update", group_id)
            return None

        # Update only provided fields
        update_data = group_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(group, field, value)

        await self.db.commit()
        await self.db.refresh(group)
        logger.info("Updated group %s (%s)", group.guid, group.name)
        return group

    async def delete_group(self, group_id: uuid.UUID) -> bool:
        """Delete a group and all its user links"""
        group = await self.get_group(group_id)
        if not group:
            logger.warning("Group %s not found for deletion", group_id)
            return False

        logger.info("Deleted group %s (%s)", group.guid, group.name)
        await self.db.delete(group)
        await self.db.commit()
        return True

    async def get_group_member_count(self, group_id: uuid.UUID) -> int:
        """Get the number of users in a group"""
        result = await self.db.execute(
            select(func.count(UserGroupLink.guid)).where(
                UserGroupLink.group_id == group_id
            )
        )
        return result.scalar_one()

    async def add_user_to_group(
        self, user_id: uuid.UUID, group_id: uuid.UUID
    ) -> UserGroupLink | None:
        """Add a user to a group"""
        # Check if link already exists
        result = await self.db.execute(
            select(UserGroupLink)
            .where(UserGroupLink.user_id == user_id)
            .where(UserGroupLink.group_id == group_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            logger.debug("User %s already in group %s", user_id, group_id)
            return existing

        # Create new link
        link = UserGroupLink(user_id=user_id, group_id=group_id)
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(link)
        logger.info("Added user %s to group %s", user_id, group_id)
        return link

    async def add_users_to_group(
        self, user_ids: list[uuid.UUID], group_id: uuid.UUID
    ) -> int:
        """Bulk-add users to a group, skipping any that are already members.

        Returns the number of links newly created.
        """
        if not user_ids:
            return 0

        existing_result = await self.db.execute(
            select(UserGroupLink.user_id).where(
                UserGroupLink.group_id == group_id,
                UserGroupLink.user_id.in_(user_ids),
            )
        )
        existing_user_ids = {row[0] for row in existing_result.all()}

        new_links = [
            UserGroupLink(user_id=uid, group_id=group_id)
            for uid in user_ids
            if uid not in existing_user_ids
        ]
        if not new_links:
            return 0

        self.db.add_all(new_links)
        await self.db.commit()
        return len(new_links)

    async def remove_user_from_group(
        self, user_id: uuid.UUID, group_id: uuid.UUID
    ) -> bool:
        """Remove a user from a group"""
        result = await self.db.execute(
            delete(UserGroupLink)
            .where(UserGroupLink.user_id == user_id)
            .where(UserGroupLink.group_id == group_id)
        )
        await self.db.commit()
        removed = result.rowcount > 0
        if removed:
            logger.info("Removed user %s from group %s", user_id, group_id)
        else:
            logger.warning("User %s not found in group %s for removal", user_id, group_id)
        return removed

    async def get_user_groups(self, user_id: uuid.UUID) -> list[Group]:
        """Get all groups a user belongs to"""
        result = await self.db.execute(
            select(Group)
            .join(UserGroupLink)
            .where(UserGroupLink.user_id == user_id)
            .where(Group.is_active)
            .order_by(Group.name)
        )
        return list(result.scalars().all())

    async def get_group_members(self, group_id: uuid.UUID) -> list[User]:
        """Get all users in a group"""
        result = await self.db.execute(
            select(User)
            .join(UserGroupLink)
            .where(UserGroupLink.group_id == group_id)
            .where(User.is_active)
            .order_by(User.email)
        )
        return list(result.scalars().all())

    async def compute_user_permissions(self, user_id: uuid.UUID) -> UserPermissions:
        """
        Compute effective permissions for a user by merging all their group permissions.

        Merge strategy:
        - allowed_libraries: union of all groups
        - allowed_qualities: union of all groups
        - max_concurrent_streams: maximum of all groups
        - max_game_streams: maximum of all groups
        - offline_download_*, prefetch_*, on_demand_fetch_*: minimum non-None value (most restrictive)
        - max_concurrent_transcodings: maximum of all groups
        - indexer_*: minimum non-None value (most restrictive)
        - playback_*: minimum non-None value (most restrictive)
        """
        groups = await self.get_user_groups(user_id)

        if not groups:
            # No groups = minimal permissions
            return UserPermissions(
                user_id=user_id,
                allowed_libraries=[],
                max_concurrent_streams=0,
                max_game_streams=0,
                offline_download_limit=0,
                offline_download_period_minutes=1440,
                prefetch_limit=0,
                prefetch_period_minutes=1440,
                on_demand_fetch_limit=0,
                on_demand_fetch_period_minutes=1440,
                max_video_quality=None,
                max_audio_quality=None,
                indexer_api_requests_limit=0,
                indexer_api_requests_period_minutes=60,
                indexer_downloads_limit=0,
                indexer_downloads_period_minutes=1440,
                playback_limit=0,
                playback_period_minutes=1440,
                max_concurrent_transcodings=0,
                favorites_permanent=False,
                remote_access_enabled=True,
                access_schedules=[],
                access_schedule_active=True,
                group_names=[],
            )

        # Quality level rankings (higher = better quality)
        video_quality_ranks = {"sd": 1, "hd": 2, "fhd": 3, "uhd": 4}
        audio_quality_ranks = {"lossy": 1, "lossless": 2}

        # Merge permissions from all groups
        allowed_libraries = set()
        max_video_quality = None
        max_audio_quality = None
        max_concurrent_streams = 0
        max_game_streams = 0
        max_concurrent_transcodings = 0
        favorites_permanent = False

        # For rate limits: collect all limits and periods
        api_request_limits = []  # List of (limit, period_minutes) tuples
        download_limits = []  # List of (limit, period_minutes) tuples
        playback_limits = []  # List of (limit, period_minutes) tuples
        offline_download_limits = []  # List of (limit, period_minutes) tuples
        prefetch_limits = []  # List of (limit, period_minutes) tuples
        on_demand_fetch_limits = []  # List of (limit, period_minutes) tuples

        group_names = []

        for group in groups:
            group_names.append(group.name)
            allowed_libraries.update(group.allowed_libraries or [])

            # For video quality: take highest (least restrictive)
            if group.max_video_quality:
                current_rank = video_quality_ranks.get(max_video_quality, 0)
                new_rank = video_quality_ranks.get(group.max_video_quality, 0)
                if new_rank > current_rank:
                    max_video_quality = group.max_video_quality

            # For audio quality: take highest (least restrictive)
            if group.max_audio_quality:
                current_rank = audio_quality_ranks.get(max_audio_quality, 0)
                new_rank = audio_quality_ranks.get(group.max_audio_quality, 0)
                if new_rank > current_rank:
                    max_audio_quality = group.max_audio_quality

            max_concurrent_streams = max(
                max_concurrent_streams, group.max_concurrent_streams
            )
            max_game_streams = max(max_game_streams, group.max_game_streams)
            max_concurrent_transcodings = max(
                max_concurrent_transcodings, group.max_concurrent_transcodings
            )
            # Any group with favorites_permanent=True makes it permanent
            if group.favorites_permanent:
                favorites_permanent = True

            if group.indexer_api_requests_limit is not None:
                api_request_limits.append(
                    (
                        group.indexer_api_requests_limit,
                        group.indexer_api_requests_period_minutes,
                    )
                )
            if group.indexer_downloads_limit is not None:
                download_limits.append(
                    (
                        group.indexer_downloads_limit,
                        group.indexer_downloads_period_minutes,
                    )
                )
            if group.playback_limit is not None:
                playback_limits.append(
                    (group.playback_limit, group.playback_period_minutes)
                )
            if group.offline_download_limit is not None:
                offline_download_limits.append(
                    (
                        group.offline_download_limit,
                        group.offline_download_period_minutes,
                    )
                )
            if group.prefetch_limit is not None:
                prefetch_limits.append(
                    (group.prefetch_limit, group.prefetch_period_minutes)
                )
            if group.on_demand_fetch_limit is not None:
                on_demand_fetch_limits.append(
                    (group.on_demand_fetch_limit, group.on_demand_fetch_period_minutes)
                )

        # For rate limits: normalize to a common period and take minimum
        # Convert all to "per minute" rate, then find most restrictive
        def get_most_restrictive_limit(limits):
            """
            Find the most restrictive rate limit.
            Convert all to rate per minute, find minimum, convert back.
            """
            if not limits:
                return None, 60  # Default period

            # Convert all to per-minute rates
            per_minute_rates = []
            for limit, period in limits:
                rate_per_minute = limit / period
                per_minute_rates.append((rate_per_minute, limit, period))

            # Find most restrictive (lowest rate per minute)
            most_restrictive = min(per_minute_rates, key=lambda x: x[0])
            return most_restrictive[1], most_restrictive[
                2
            ]  # Return original limit and period

        indexer_api_limit, api_period = get_most_restrictive_limit(api_request_limits)
        indexer_download_limit, download_period = get_most_restrictive_limit(
            download_limits
        )
        playback_limit, playback_period = get_most_restrictive_limit(playback_limits)
        offline_download_limit, offline_download_period = get_most_restrictive_limit(
            offline_download_limits
        )
        prefetch_limit, prefetch_period = get_most_restrictive_limit(prefetch_limits)
        on_demand_fetch_limit, on_demand_fetch_period = get_most_restrictive_limit(
            on_demand_fetch_limits
        )

        return UserPermissions(
            user_id=user_id,
            allowed_libraries=sorted(allowed_libraries),
            max_video_quality=max_video_quality,
            max_audio_quality=max_audio_quality,
            max_concurrent_streams=max_concurrent_streams,
            max_game_streams=max_game_streams,
            offline_download_limit=offline_download_limit,
            offline_download_period_minutes=offline_download_period,
            prefetch_limit=prefetch_limit,
            prefetch_period_minutes=prefetch_period,
            on_demand_fetch_limit=on_demand_fetch_limit,
            on_demand_fetch_period_minutes=on_demand_fetch_period,
            max_concurrent_transcodings=max_concurrent_transcodings,
            indexer_api_requests_limit=indexer_api_limit,
            indexer_api_requests_period_minutes=api_period,
            indexer_downloads_limit=indexer_download_limit,
            indexer_downloads_period_minutes=download_period,
            playback_limit=playback_limit,
            playback_period_minutes=playback_period,
            favorites_permanent=favorites_permanent,
            remote_access_enabled=True,
            access_schedules=[],
            access_schedule_active=True,
            group_names=group_names,
        )

    async def create_group_with_count(self, group_data: GroupCreate) -> GroupRead:
        """Create a new group and return it with member count."""
        group = await self.create_group(group_data)
        member_count = await self.get_group_member_count(group.guid)
        return GroupRead(**group.__dict__, member_count=member_count)

    async def list_groups_with_count(
        self, skip: int = 0, limit: int = 100, include_inactive: bool = False
    ) -> list[GroupRead]:
        """List groups with member counts."""
        groups = await self.list_groups(
            skip=skip, limit=limit, include_inactive=include_inactive
        )
        result = []
        for group in groups:
            member_count = await self.get_group_member_count(group.guid)
            result.append(GroupRead(**group.__dict__, member_count=member_count))
        return result

    async def get_group_read_with_count(self, group_id: uuid.UUID) -> GroupRead | None:
        """Get a group as GroupRead with member count, or None if not found."""
        group = await self.get_group(group_id)
        if not group:
            return None
        member_count = await self.get_group_member_count(group.guid)
        return GroupRead(**group.__dict__, member_count=member_count)

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        """Get a user by ID."""
        result = await self.db.execute(select(User).where(User.guid == user_id))
        return result.scalar_one_or_none()

    async def get_user_with_groups(self, user_id: uuid.UUID) -> UserWithGroups | None:
        """Get a user with their group assignments. Returns None if user not found."""
        user = await self.get_user_by_id(user_id)
        if not user:
            return None

        groups = await self.get_user_groups(user_id)
        group_ids = [group.guid for group in groups]

        return UserWithGroups(
            user_id=user.guid,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            group_ids=group_ids,
        )

    async def check_library_access(self, user_id: uuid.UUID, library_type: str) -> bool:
        """Check if user has access to a specific library"""
        permissions = await self.compute_user_permissions(user_id)
        return library_type in permissions.allowed_libraries

    async def check_video_quality_access(
        self, user_id: uuid.UUID, requested_quality: str
    ) -> bool:
        """Check if user can access a specific video quality"""
        permissions = await self.compute_user_permissions(user_id)
        if not permissions.max_video_quality:
            return False

        quality_ranks = {"sd": 1, "hd": 2, "fhd": 3, "uhd": 4}
        max_rank = quality_ranks.get(permissions.max_video_quality, 0)
        requested_rank = quality_ranks.get(requested_quality, 0)
        return requested_rank <= max_rank

    async def check_audio_quality_access(
        self, user_id: uuid.UUID, requested_quality: str
    ) -> bool:
        """Check if user can access a specific audio quality"""
        permissions = await self.compute_user_permissions(user_id)
        if not permissions.max_audio_quality:
            return False

        quality_ranks = {"lossy": 1, "lossless": 2}
        max_rank = quality_ranks.get(permissions.max_audio_quality, 0)
        requested_rank = quality_ranks.get(requested_quality, 0)
        return requested_rank <= max_rank

    async def check_transcoding_allowed(
        self, user_id: uuid.UUID, concurrent_count: int = 1
    ) -> bool:
        """Check if user is allowed to use transcoding with specified concurrent sessions"""
        permissions = await self.compute_user_permissions(user_id)
        return concurrent_count <= permissions.max_concurrent_transcodings
