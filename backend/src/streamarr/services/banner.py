"""Banner service for managing system-wide announcements."""

import logging
import uuid
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.banner import Banner, UserBannerDismissed
from streamarr.schemas.banner import BannerCreate, BannerUpdate


class BannerService:
    """Service for managing banners."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_banner(
        self, banner_data: BannerCreate, created_by_guid: uuid.UUID
    ) -> Banner:
        """Create a new banner."""
        banner = Banner(**banner_data.model_dump(), created_by_guid=created_by_guid)
        self.db.add(banner)
        await self.db.commit()
        await self.db.refresh(banner)
        logger.info("Created banner %s by user %s", banner.guid, created_by_guid)
        return banner

    async def get_banner(self, banner_guid: uuid.UUID) -> Banner | None:
        """Get a banner by GUID."""
        result = await self.db.execute(select(Banner).where(Banner.guid == banner_guid))
        return result.scalar_one_or_none()

    async def get_active_banners(
        self,
        user_guid: uuid.UUID | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[Banner], int]:
        """
        Get active banners with pagination.
        If user_guid is provided, excludes banners dismissed by that user.
        Only returns banners that are within their scheduled time window.
        """
        now = datetime.now(UTC)

        query = select(Banner).where(Banner.is_active == True)  # noqa: E712
        query = query.where(
            and_(
                (Banner.start_date == None) | (Banner.start_date <= now),  # noqa: E711
                (Banner.end_date == None) | (Banner.end_date >= now),  # noqa: E711
            )
        )

        if user_guid:
            dismissed_subquery = (
                select(UserBannerDismissed.banner_guid)
                .where(UserBannerDismissed.user_guid == user_guid)
                .scalar_subquery()
            )
            query = query.where(Banner.guid.not_in(dismissed_subquery))

        # Count
        count_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar() or 0

        # Paginate
        query = query.order_by(Banner.created_at.desc())
        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await self.db.execute(query)
        return list(result.scalars().all()), total

    async def get_all_banners(
        self,
        page: int = 1,
        per_page: int = 50,
        is_active: bool | None = None,
    ) -> tuple[list[Banner], int]:
        """Get all banners with pagination."""
        query = select(Banner)

        if is_active is not None:
            query = query.where(Banner.is_active == is_active)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # Get paginated results
        query = query.order_by(Banner.created_at.desc())
        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await self.db.execute(query)
        banners = list(result.scalars().all())

        return banners, total

    async def update_banner(
        self, banner_guid: uuid.UUID, banner_data: BannerUpdate
    ) -> Banner | None:
        """Update a banner."""
        banner = await self.get_banner(banner_guid)
        if not banner:
            logger.warning("Banner %s not found for update", banner_guid)
            return None

        update_data = banner_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(banner, key, value)

        banner.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(banner)
        logger.info("Updated banner %s", banner_guid)
        return banner

    async def delete_banner(self, banner_guid: uuid.UUID) -> bool:
        """Delete a banner."""
        banner = await self.get_banner(banner_guid)
        if not banner:
            logger.warning("Banner %s not found for deletion", banner_guid)
            return False

        await self.db.delete(banner)
        await self.db.commit()
        logger.info("Deleted banner %s", banner_guid)
        return True

    async def dismiss_banner(
        self, banner_guid: uuid.UUID, user_guid: uuid.UUID
    ) -> bool:
        """Mark a banner as dismissed for a user."""
        # Check if already dismissed
        result = await self.db.execute(
            select(UserBannerDismissed).where(
                and_(
                    UserBannerDismissed.banner_guid == banner_guid,
                    UserBannerDismissed.user_guid == user_guid,
                )
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            return True  # Already dismissed

        # Create dismissal record
        dismissal = UserBannerDismissed(banner_guid=banner_guid, user_guid=user_guid)
        self.db.add(dismissal)
        await self.db.commit()
        logger.info("Banner %s dismissed by user %s", banner_guid, user_guid)
        return True

    async def is_banner_dismissed(
        self, banner_guid: uuid.UUID, user_guid: uuid.UUID
    ) -> bool:
        """Check if a banner has been dismissed by a user."""
        result = await self.db.execute(
            select(func.count())
            .select_from(UserBannerDismissed)
            .where(
                and_(
                    UserBannerDismissed.banner_guid == banner_guid,
                    UserBannerDismissed.user_guid == user_guid,
                )
            )
        )
        count = result.scalar_one()
        return count > 0

    async def get_dismissed_banner_guids(
        self, banner_guids: list[uuid.UUID], user_guid: uuid.UUID
    ) -> set[uuid.UUID]:
        """Return the subset of ``banner_guids`` that the user has already dismissed."""
        if not banner_guids:
            return set()
        result = await self.db.execute(
            select(UserBannerDismissed.banner_guid).where(
                and_(
                    UserBannerDismissed.user_guid == user_guid,
                    UserBannerDismissed.banner_guid.in_(banner_guids),
                )
            )
        )
        return {row[0] for row in result.all()}
