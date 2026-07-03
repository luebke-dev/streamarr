"""Tests for the BannerService."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.banner import Banner, UserBannerDismissed
from pyrate.models.user import User
from pyrate.schemas.banner import BannerCreate, BannerUpdate
from pyrate.services.banner import BannerService


class TestBannerCRUD:
    """Test basic CRUD operations for banners."""

    @pytest.mark.asyncio
    async def test_create_banner(self, db_session: AsyncSession, test_user: User):
        """Test creating a banner."""
        service = BannerService(db_session)

        banner_data = BannerCreate(
            title="Test Banner",
            message="This is a test banner message",
            banner_type="info",
            is_active=True,
            dismissible=True,
        )

        created_banner = await service.create_banner(banner_data, test_user.guid)

        assert created_banner.title == "Test Banner"
        assert created_banner.message == "This is a test banner message"
        assert created_banner.banner_type == "info"
        assert created_banner.is_active is True
        assert created_banner.dismissible is True
        assert created_banner.created_by_guid == test_user.guid
        assert created_banner.guid is not None

    @pytest.mark.asyncio
    async def test_create_banner_with_dates(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test creating a banner with start and end dates."""
        service = BannerService(db_session)

        start_date = datetime.now()
        end_date = datetime.now() + timedelta(days=7)

        banner_data = BannerCreate(
            title="Scheduled Banner",
            message="This banner has a schedule",
            banner_type="warning",
            is_active=True,
            dismissible=True,
            start_date=start_date,
            end_date=end_date,
        )

        created_banner = await service.create_banner(banner_data, test_user.guid)

        assert created_banner.start_date is not None
        assert created_banner.end_date is not None
        # Compare just the dates since times might differ slightly
        assert created_banner.start_date.date() == start_date.date()
        assert created_banner.end_date.date() == end_date.date()

    @pytest.mark.asyncio
    async def test_get_banner(self, db_session: AsyncSession, test_user: User):
        """Test retrieving a banner by GUID."""
        service = BannerService(db_session)

        banner_data = BannerCreate(
            title="Test Banner",
            message="Test message",
            banner_type="info",
        )
        created = await service.create_banner(banner_data, test_user.guid)

        retrieved = await service.get_banner(created.guid)

        assert retrieved is not None
        assert retrieved.guid == created.guid
        assert retrieved.title == "Test Banner"

    @pytest.mark.asyncio
    async def test_get_banner_not_found(self, db_session: AsyncSession):
        """Test retrieving a non-existent banner."""
        service = BannerService(db_session)

        retrieved = await service.get_banner(uuid.uuid4())

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_update_banner(self, db_session: AsyncSession, test_user: User):
        """Test updating a banner."""
        service = BannerService(db_session)

        banner_data = BannerCreate(
            title="Original Title",
            message="Original message",
            banner_type="info",
            is_active=True,
        )
        created = await service.create_banner(banner_data, test_user.guid)

        update_data = BannerUpdate(
            title="Updated Title",
            message="Updated message",
            banner_type="warning",
            is_active=False,
        )

        updated = await service.update_banner(created.guid, update_data)

        assert updated is not None
        assert updated.title == "Updated Title"
        assert updated.message == "Updated message"
        assert updated.banner_type == "warning"
        assert updated.is_active is False
        assert updated.updated_at is not None

    @pytest.mark.asyncio
    async def test_update_banner_partial(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test partial update of a banner."""
        service = BannerService(db_session)

        banner_data = BannerCreate(
            title="Original Title",
            message="Original message",
            banner_type="info",
        )
        created = await service.create_banner(banner_data, test_user.guid)

        # Only update the title
        update_data = BannerUpdate(title="New Title")

        updated = await service.update_banner(created.guid, update_data)

        assert updated is not None
        assert updated.title == "New Title"
        assert updated.message == "Original message"  # Unchanged
        assert updated.banner_type == "info"  # Unchanged

    @pytest.mark.asyncio
    async def test_update_banner_not_found(self, db_session: AsyncSession):
        """Test updating a non-existent banner."""
        service = BannerService(db_session)

        update_data = BannerUpdate(title="New Title")

        updated = await service.update_banner(uuid.uuid4(), update_data)

        assert updated is None

    @pytest.mark.asyncio
    async def test_delete_banner(self, db_session: AsyncSession, test_user: User):
        """Test deleting a banner."""
        service = BannerService(db_session)

        banner_data = BannerCreate(
            title="To Delete",
            message="This will be deleted",
            banner_type="info",
        )
        created = await service.create_banner(banner_data, test_user.guid)

        result = await service.delete_banner(created.guid)
        assert result is True

        retrieved = await service.get_banner(created.guid)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_banner_not_found(self, db_session: AsyncSession):
        """Test deleting a non-existent banner."""
        service = BannerService(db_session)

        result = await service.delete_banner(uuid.uuid4())
        assert result is False


class TestActiveBanners:
    """Test retrieving active banners."""

    @pytest.mark.asyncio
    async def test_get_active_banners_basic(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test getting active banners."""
        service = BannerService(db_session)

        # Create active banner
        await service.create_banner(
            BannerCreate(
                title="Active Banner",
                message="This is active",
                banner_type="info",
                is_active=True,
            ),
            test_user.guid,
        )

        # Create inactive banner
        await service.create_banner(
            BannerCreate(
                title="Inactive Banner",
                message="This is inactive",
                banner_type="info",
                is_active=False,
            ),
            test_user.guid,
        )

        active_banners, _ = await service.get_active_banners()

        assert len(active_banners) == 1
        assert active_banners[0].title == "Active Banner"

    @pytest.mark.asyncio
    async def test_get_active_banners_scheduled_current(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test getting banners that are currently scheduled."""
        service = BannerService(db_session)

        # Banner that's currently active (started yesterday, ends tomorrow)
        await service.create_banner(
            BannerCreate(
                title="Current Banner",
                message="Currently visible",
                banner_type="info",
                is_active=True,
                start_date=datetime.now() - timedelta(days=1),
                end_date=datetime.now() + timedelta(days=1),
            ),
            test_user.guid,
        )

        active_banners, _ = await service.get_active_banners()

        assert len(active_banners) == 1
        assert active_banners[0].title == "Current Banner"

    @pytest.mark.asyncio
    async def test_get_active_banners_scheduled_future(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that future banners are not shown."""
        service = BannerService(db_session)

        # Banner that starts in the future
        await service.create_banner(
            BannerCreate(
                title="Future Banner",
                message="Not yet visible",
                banner_type="info",
                is_active=True,
                start_date=datetime.now() + timedelta(days=1),
                end_date=datetime.now() + timedelta(days=7),
            ),
            test_user.guid,
        )

        active_banners, _ = await service.get_active_banners()

        assert len(active_banners) == 0

    @pytest.mark.asyncio
    async def test_get_active_banners_scheduled_past(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that expired banners are not shown."""
        service = BannerService(db_session)

        # Banner that ended in the past
        await service.create_banner(
            BannerCreate(
                title="Past Banner",
                message="Already expired",
                banner_type="info",
                is_active=True,
                start_date=datetime.now() - timedelta(days=7),
                end_date=datetime.now() - timedelta(days=1),
            ),
            test_user.guid,
        )

        active_banners, _ = await service.get_active_banners()

        assert len(active_banners) == 0

    @pytest.mark.asyncio
    async def test_get_active_banners_no_start_date(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test banner with no start date (always started)."""
        service = BannerService(db_session)

        await service.create_banner(
            BannerCreate(
                title="No Start Banner",
                message="Always started",
                banner_type="info",
                is_active=True,
                start_date=None,
                end_date=datetime.now() + timedelta(days=1),
            ),
            test_user.guid,
        )

        active_banners, _ = await service.get_active_banners()

        assert len(active_banners) == 1

    @pytest.mark.asyncio
    async def test_get_active_banners_no_end_date(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test banner with no end date (never expires)."""
        service = BannerService(db_session)

        await service.create_banner(
            BannerCreate(
                title="No End Banner",
                message="Never expires",
                banner_type="info",
                is_active=True,
                start_date=datetime.now() - timedelta(days=1),
                end_date=None,
            ),
            test_user.guid,
        )

        active_banners, _ = await service.get_active_banners()

        assert len(active_banners) == 1

    @pytest.mark.asyncio
    async def test_get_active_banners_excludes_dismissed(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test that dismissed banners are excluded for the user."""
        service = BannerService(db_session)

        banner = await service.create_banner(
            BannerCreate(
                title="Dismissible Banner",
                message="Can be dismissed",
                banner_type="info",
                is_active=True,
                dismissible=True,
            ),
            test_user.guid,
        )

        # Dismiss for test_user2
        await service.dismiss_banner(banner.guid, test_user2.guid)

        # Get active banners without user context
        all_active, _ = await service.get_active_banners()
        assert len(all_active) == 1

        # Get active banners for test_user (should see it)
        user1_active, _ = await service.get_active_banners(test_user.guid)
        assert len(user1_active) == 1

        # Get active banners for test_user2 (should not see it)
        user2_active, _ = await service.get_active_banners(test_user2.guid)
        assert len(user2_active) == 0


class TestBannerPagination:
    """Test banner pagination functionality."""

    @pytest.mark.asyncio
    async def test_get_all_banners_pagination(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test pagination of all banners."""
        service = BannerService(db_session)

        # Create 5 banners
        for i in range(5):
            await service.create_banner(
                BannerCreate(
                    title=f"Banner {i}",
                    message=f"Message {i}",
                    banner_type="info",
                ),
                test_user.guid,
            )

        # Get first page
        banners_page1, total = await service.get_all_banners(page=1, per_page=2)
        assert len(banners_page1) == 2
        assert total == 5

        # Get second page
        banners_page2, total = await service.get_all_banners(page=2, per_page=2)
        assert len(banners_page2) == 2
        assert total == 5

        # Ensure different banners
        page1_guids = {str(b.guid) for b in banners_page1}
        page2_guids = {str(b.guid) for b in banners_page2}
        assert page1_guids.isdisjoint(page2_guids)

    @pytest.mark.asyncio
    async def test_get_all_banners_filter_active(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test filtering banners by active status."""
        service = BannerService(db_session)

        # Create active banners
        await service.create_banner(
            BannerCreate(
                title="Active 1",
                message="Active banner",
                banner_type="info",
                is_active=True,
            ),
            test_user.guid,
        )
        await service.create_banner(
            BannerCreate(
                title="Active 2",
                message="Active banner",
                banner_type="info",
                is_active=True,
            ),
            test_user.guid,
        )

        # Create inactive banner
        await service.create_banner(
            BannerCreate(
                title="Inactive 1",
                message="Inactive banner",
                banner_type="info",
                is_active=False,
            ),
            test_user.guid,
        )

        # Get only active banners
        active_banners, total = await service.get_all_banners(is_active=True)
        assert len(active_banners) == 2
        assert total == 2

        # Get only inactive banners
        inactive_banners, total = await service.get_all_banners(is_active=False)
        assert len(inactive_banners) == 1
        assert total == 1

        # Get all banners
        all_banners, total = await service.get_all_banners()
        assert len(all_banners) == 3
        assert total == 3


class TestBannerDismissal:
    """Test banner dismissal functionality."""

    @pytest.mark.asyncio
    async def test_dismiss_banner(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test dismissing a banner."""
        service = BannerService(db_session)

        banner = await service.create_banner(
            BannerCreate(
                title="Dismissible Banner",
                message="Can be dismissed",
                banner_type="info",
                dismissible=True,
            ),
            test_user.guid,
        )

        result = await service.dismiss_banner(banner.guid, test_user2.guid)
        assert result is True

        # Verify it's dismissed
        is_dismissed = await service.is_banner_dismissed(banner.guid, test_user2.guid)
        assert is_dismissed is True

    @pytest.mark.asyncio
    async def test_dismiss_banner_idempotent(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test that dismissing a banner twice is idempotent."""
        service = BannerService(db_session)

        banner = await service.create_banner(
            BannerCreate(
                title="Dismissible Banner",
                message="Can be dismissed",
                banner_type="info",
                dismissible=True,
            ),
            test_user.guid,
        )

        result1 = await service.dismiss_banner(banner.guid, test_user2.guid)
        assert result1 is True

        result2 = await service.dismiss_banner(banner.guid, test_user2.guid)
        assert result2 is True

        is_dismissed = await service.is_banner_dismissed(banner.guid, test_user2.guid)
        assert is_dismissed is True

    @pytest.mark.asyncio
    async def test_is_banner_dismissed_false(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test checking if a banner is dismissed when it's not."""
        service = BannerService(db_session)

        banner = await service.create_banner(
            BannerCreate(
                title="Banner",
                message="Message",
                banner_type="info",
            ),
            test_user.guid,
        )

        is_dismissed = await service.is_banner_dismissed(banner.guid, test_user2.guid)
        assert is_dismissed is False

    @pytest.mark.asyncio
    async def test_dismiss_banner_user_specific(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test that dismissal is user-specific."""
        service = BannerService(db_session)

        banner = await service.create_banner(
            BannerCreate(
                title="Banner",
                message="Message",
                banner_type="info",
                dismissible=True,
            ),
            test_user.guid,
        )

        # Dismiss for user2
        await service.dismiss_banner(banner.guid, test_user2.guid)

        # Check user2 dismissed it
        is_dismissed_user2 = await service.is_banner_dismissed(
            banner.guid, test_user2.guid
        )
        assert is_dismissed_user2 is True

        # Check user1 has not dismissed it
        is_dismissed_user1 = await service.is_banner_dismissed(
            banner.guid, test_user.guid
        )
        assert is_dismissed_user1 is False


class TestBannerTypes:
    """Test different banner types."""

    @pytest.mark.asyncio
    async def test_create_banner_types(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test creating banners with different types."""
        service = BannerService(db_session)

        types = ["info", "warning", "error", "success"]

        for banner_type in types:
            banner = await service.create_banner(
                BannerCreate(
                    title=f"{banner_type.capitalize()} Banner",
                    message=f"This is a {banner_type} message",
                    banner_type=banner_type,
                ),
                test_user.guid,
            )

            assert banner.banner_type == banner_type

    @pytest.mark.asyncio
    async def test_banner_ordering(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that banners are returned in descending created_at order."""
        service = BannerService(db_session)

        # Create banners in sequence
        banner1 = await service.create_banner(
            BannerCreate(title="First", message="First banner", banner_type="info"),
            test_user.guid,
        )
        banner2 = await service.create_banner(
            BannerCreate(title="Second", message="Second banner", banner_type="info"),
            test_user.guid,
        )
        banner3 = await service.create_banner(
            BannerCreate(title="Third", message="Third banner", banner_type="info"),
            test_user.guid,
        )

        active_banners, _ = await service.get_active_banners()

        # Should be in reverse order (newest first)
        assert len(active_banners) == 3
        assert active_banners[0].guid == banner3.guid
        assert active_banners[1].guid == banner2.guid
        assert active_banners[2].guid == banner1.guid
