"""Tests for subscription models at the data layer.

Note: The SubscriptionService has model mismatches (uses .id but models have .guid,
uses is_active but model has status enum). These tests verify the model layer directly.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.group import Group
from pyrate.models.subscription import (
    PaymentHistory,
    QualityLevel,
    SubscriptionPackage,
    SubscriptionStatus,
    UserSession,
    UserSubscription,
)
from pyrate.models.user import User


async def _create_group(
    db_session: AsyncSession,
    *,
    name: str = "Premium Group",
    allowed_libraries: list[str] | None = None,
    max_concurrent_streams: int = 3,
    max_video_quality: str | None = "fhd",
    max_audio_quality: str | None = "lossless",
) -> Group:
    group = Group(
        guid=uuid.uuid4(),
        name=f"{name}-{uuid.uuid4()}",
        allowed_libraries=allowed_libraries or ["MOVIES", "SHOWS", "MUSIC"],
        max_concurrent_streams=max_concurrent_streams,
        max_video_quality=max_video_quality,
        max_audio_quality=max_audio_quality,
    )
    db_session.add(group)
    await db_session.flush()
    return group


@pytest_asyncio.fixture
async def sample_package(db_session: AsyncSession) -> SubscriptionPackage:
    """Create a sample subscription package."""
    group = await _create_group(db_session)
    package = SubscriptionPackage(
        guid=uuid.uuid4(),
        name="Premium",
        description="Premium plan with all features",
        price_cents=999,
        currency="EUR",
        is_active=True,
        group_id=group.guid,
    )
    db_session.add(package)
    await db_session.commit()
    await db_session.refresh(package)
    return package


@pytest_asyncio.fixture
async def sample_subscription(
    db_session: AsyncSession, test_user: User, sample_package: SubscriptionPackage
) -> UserSubscription:
    """Create a sample user subscription."""
    sub = UserSubscription(
        guid=uuid.uuid4(),
        user_id=test_user.guid,
        package_id=sample_package.guid,
        status=SubscriptionStatus.ACTIVE,
        starts_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


class TestSubscriptionPackage:
    """Tests for SubscriptionPackage model."""

    @pytest.mark.asyncio
    async def test_create_package(self, db_session: AsyncSession):
        """Test creating a subscription package."""
        group = await _create_group(db_session, name="Basic Group", allowed_libraries=["MOVIES"])
        package = SubscriptionPackage(
            guid=uuid.uuid4(),
            name="Basic",
            description="Basic plan",
            price_cents=499,
            group_id=group.guid,
        )
        db_session.add(package)
        await db_session.commit()
        await db_session.refresh(package)

        assert package.guid is not None
        assert package.name == "Basic"
        assert package.price_cents == 499
        assert package.group_id == group.guid

    @pytest.mark.asyncio
    async def test_package_defaults(self, db_session: AsyncSession):
        """Test default values on a package."""
        group = await _create_group(db_session, name="Default Group", allowed_libraries=[])
        package = SubscriptionPackage(
            guid=uuid.uuid4(),
            name="Test",
            price_cents=0,
            group_id=group.guid,
        )
        db_session.add(package)
        await db_session.commit()
        await db_session.refresh(package)

        assert package.is_active is True
        assert package.currency == "EUR"
        assert package.group_id == group.guid

    @pytest.mark.asyncio
    async def test_package_with_quality_levels(self, db_session: AsyncSession):
        """Test package with quality level settings."""
        group = await _create_group(
            db_session,
            name="UHD Group",
            allowed_libraries=["MOVIES", "SHOWS"],
            max_video_quality=QualityLevel.UHD,
            max_audio_quality=QualityLevel.LOSSLESS,
        )
        package = SubscriptionPackage(
            guid=uuid.uuid4(),
            name="UHD Plan",
            price_cents=1999,
            group_id=group.guid,
        )
        db_session.add(package)
        await db_session.commit()
        await db_session.refresh(package)

        assert package.group.max_video_quality == "uhd"
        assert package.group.max_audio_quality == "lossless"

    @pytest.mark.asyncio
    async def test_package_with_stripe(self, db_session: AsyncSession):
        """Test package with Stripe integration fields."""
        group = await _create_group(db_session, name="Stripe Group", allowed_libraries=["MOVIES"])
        package = SubscriptionPackage(
            guid=uuid.uuid4(),
            name="Stripe Plan",
            price_cents=999,
            group_id=group.guid,
            stripe_product_id="prod_test123",
            stripe_price_id="price_test456",
        )
        db_session.add(package)
        await db_session.commit()
        await db_session.refresh(package)

        assert package.stripe_product_id == "prod_test123"
        assert package.stripe_price_id == "price_test456"

    @pytest.mark.asyncio
    async def test_deactivate_package(
        self, db_session: AsyncSession, sample_package: SubscriptionPackage
    ):
        """Test deactivating a package."""
        sample_package.is_active = False
        await db_session.commit()
        await db_session.refresh(sample_package)

        assert sample_package.is_active is False

    @pytest.mark.asyncio
    async def test_query_active_packages(self, db_session: AsyncSession):
        """Test querying only active packages."""
        active_group = await _create_group(db_session, name="Active Group", allowed_libraries=["MOVIES"])
        inactive_group = await _create_group(
            db_session,
            name="Inactive Group",
            allowed_libraries=["MOVIES"],
        )
        active = SubscriptionPackage(
            guid=uuid.uuid4(),
            name="Active",
            price_cents=999,
            is_active=True,
            group_id=active_group.guid,
        )
        inactive = SubscriptionPackage(
            guid=uuid.uuid4(),
            name="Inactive",
            price_cents=999,
            is_active=False,
            group_id=inactive_group.guid,
        )
        db_session.add_all([active, inactive])
        await db_session.commit()

        stmt = select(SubscriptionPackage).where(SubscriptionPackage.is_active)
        result = await db_session.execute(stmt)
        packages = list(result.scalars().all())

        names = [p.name for p in packages]
        assert "Active" in names
        assert "Inactive" not in names


class TestUserSubscription:
    """Tests for UserSubscription model."""

    @pytest.mark.asyncio
    async def test_create_subscription(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_package: SubscriptionPackage,
    ):
        """Test creating a user subscription."""
        sub = UserSubscription(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            package_id=sample_package.guid,
            status=SubscriptionStatus.ACTIVE,
            starts_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db_session.add(sub)
        await db_session.commit()
        await db_session.refresh(sub)

        assert sub.guid is not None
        assert sub.user_id == test_user.guid
        assert sub.package_id == sample_package.guid
        assert sub.status == SubscriptionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_subscription_defaults(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_package: SubscriptionPackage,
    ):
        """Test subscription default values."""
        sub = UserSubscription(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            package_id=sample_package.guid,
            starts_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db_session.add(sub)
        await db_session.commit()
        await db_session.refresh(sub)

        assert sub.current_sessions == 0
        assert sub.cancelled_at is None
        assert sub.stripe_subscription_id is None

    @pytest.mark.asyncio
    async def test_cancel_subscription(
        self, db_session: AsyncSession, sample_subscription: UserSubscription
    ):
        """Test cancelling a subscription."""
        sample_subscription.status = SubscriptionStatus.CANCELLED
        sample_subscription.cancelled_at = datetime.now(UTC)
        await db_session.commit()
        await db_session.refresh(sample_subscription)

        assert sample_subscription.status == SubscriptionStatus.CANCELLED
        assert sample_subscription.cancelled_at is not None

    @pytest.mark.asyncio
    async def test_expire_subscription(
        self, db_session: AsyncSession, sample_subscription: UserSubscription
    ):
        """Test setting subscription to expired."""
        sample_subscription.status = SubscriptionStatus.EXPIRED
        await db_session.commit()
        await db_session.refresh(sample_subscription)

        assert sample_subscription.status == SubscriptionStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_extend_subscription(
        self, db_session: AsyncSession, sample_subscription: UserSubscription
    ):
        """Test extending subscription expiry."""
        original_expires = sample_subscription.expires_at
        sample_subscription.expires_at = original_expires + timedelta(days=30)
        await db_session.commit()
        await db_session.refresh(sample_subscription)

        diff = (sample_subscription.expires_at - original_expires).days
        assert diff == 30

    @pytest.mark.asyncio
    async def test_query_active_subscriptions(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_package: SubscriptionPackage,
    ):
        """Test querying active subscriptions for a user."""
        now = datetime.now(UTC)
        active = UserSubscription(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            package_id=sample_package.guid,
            status=SubscriptionStatus.ACTIVE,
            starts_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=29),
        )
        cancelled = UserSubscription(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            package_id=sample_package.guid,
            status=SubscriptionStatus.CANCELLED,
            starts_at=now - timedelta(days=60),
            expires_at=now - timedelta(days=30),
            cancelled_at=now - timedelta(days=35),
        )
        db_session.add_all([active, cancelled])
        await db_session.commit()

        stmt = select(UserSubscription).where(
            UserSubscription.user_id == test_user.guid,
            UserSubscription.status == SubscriptionStatus.ACTIVE,
        )
        result = await db_session.execute(stmt)
        subs = list(result.scalars().all())

        assert len(subs) == 1
        assert subs[0].status == SubscriptionStatus.ACTIVE


class TestUserSession:
    """Tests for UserSession model."""

    @pytest.mark.asyncio
    async def test_create_session(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        """Test creating a user session."""
        session = UserSession(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            session_token=str(uuid.uuid4()),
            device_info="Chrome/Windows",
            ip_address="192.168.1.1",
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        assert session.guid is not None
        assert session.session_token is not None
        assert session.is_active is True

    @pytest.mark.asyncio
    async def test_session_defaults(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        """Test session default values."""
        session = UserSession(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            session_token=str(uuid.uuid4()),
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        assert session.is_active is True
        assert session.device_info is None
        assert session.ip_address is None
        assert session.content_type is None
        assert session.content_id is None

    @pytest.mark.asyncio
    async def test_end_session(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        """Test ending a session by setting is_active=False."""
        session = UserSession(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            session_token=str(uuid.uuid4()),
        )
        db_session.add(session)
        await db_session.commit()

        session.is_active = False
        await db_session.commit()
        await db_session.refresh(session)

        assert session.is_active is False

    @pytest.mark.asyncio
    async def test_session_with_content(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        """Test session tracking content being watched."""
        session = UserSession(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            session_token=str(uuid.uuid4()),
            content_type="movie",
            content_id=str(uuid.uuid4()),
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        assert session.content_type == "movie"
        assert session.content_id is not None

    @pytest.mark.asyncio
    async def test_query_active_sessions(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        """Test querying active sessions for a user."""
        active = UserSession(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            session_token=str(uuid.uuid4()),
            is_active=True,
        )
        ended = UserSession(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            session_token=str(uuid.uuid4()),
            is_active=False,
        )
        db_session.add_all([active, ended])
        await db_session.commit()

        stmt = select(UserSession).where(
            UserSession.user_id == test_user.guid,
            UserSession.is_active,
        )
        result = await db_session.execute(stmt)
        sessions = list(result.scalars().all())

        assert len(sessions) == 1
        assert sessions[0].is_active is True


class TestPaymentHistory:
    """Tests for PaymentHistory model."""

    @pytest.mark.asyncio
    async def test_create_payment(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        """Test creating a payment record."""
        payment = PaymentHistory(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=999,
            currency="EUR",
            status="succeeded",
        )
        db_session.add(payment)
        await db_session.commit()
        await db_session.refresh(payment)

        assert payment.guid is not None
        assert payment.amount_cents == 999
        assert payment.currency == "EUR"
        assert payment.status == "succeeded"

    @pytest.mark.asyncio
    async def test_payment_with_stripe(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        """Test payment with Stripe fields."""
        payment = PaymentHistory(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=999,
            currency="EUR",
            status="succeeded",
            stripe_payment_intent_id="pi_test123",
            stripe_invoice_id="inv_test456",
        )
        db_session.add(payment)
        await db_session.commit()
        await db_session.refresh(payment)

        assert payment.stripe_payment_intent_id == "pi_test123"
        assert payment.stripe_invoice_id == "inv_test456"

    @pytest.mark.asyncio
    async def test_failed_payment(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        """Test recording a failed payment."""
        payment = PaymentHistory(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=999,
            currency="EUR",
            status="failed",
            failure_reason="Card declined",
        )
        db_session.add(payment)
        await db_session.commit()
        await db_session.refresh(payment)

        assert payment.status == "failed"
        assert payment.failure_reason == "Card declined"

    @pytest.mark.asyncio
    async def test_payment_metadata(
        self,
        db_session: AsyncSession,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        """Test payment with metadata JSON field."""
        payment = PaymentHistory(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=999,
            currency="EUR",
            status="succeeded",
            payment_metadata={"coupon": "SAVE10", "discount_pct": 10},
        )
        db_session.add(payment)
        await db_session.commit()
        await db_session.refresh(payment)

        assert payment.payment_metadata["coupon"] == "SAVE10"
        assert payment.payment_metadata["discount_pct"] == 10

    @pytest.mark.asyncio
    async def test_query_payments_by_user(
        self,
        db_session: AsyncSession,
        test_user: User,
        test_user2: User,
        sample_subscription: UserSubscription,
    ):
        """Test querying payments for a specific user."""
        p1 = PaymentHistory(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=999,
            currency="EUR",
            status="succeeded",
        )
        # Create a subscription for user2 to reference
        sub2_group = await _create_group(db_session, name="Basic2 Group", allowed_libraries=["MOVIES"])
        sub2_package = SubscriptionPackage(
            guid=uuid.uuid4(),
            name="Basic2",
            price_cents=499,
            group_id=sub2_group.guid,
        )
        db_session.add(sub2_package)
        await db_session.flush()

        sub2 = UserSubscription(
            guid=uuid.uuid4(),
            user_id=test_user2.guid,
            package_id=sub2_package.guid,
            starts_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db_session.add(sub2)
        await db_session.flush()

        p2 = PaymentHistory(
            guid=uuid.uuid4(),
            user_id=test_user2.guid,
            subscription_id=sub2.guid,
            amount_cents=499,
            currency="EUR",
            status="succeeded",
        )
        db_session.add_all([p1, p2])
        await db_session.commit()

        stmt = select(PaymentHistory).where(
            PaymentHistory.user_id == test_user.guid
        )
        result = await db_session.execute(stmt)
        payments = list(result.scalars().all())

        assert len(payments) == 1
        assert payments[0].amount_cents == 999


class TestSubscriptionStatus:
    """Tests for SubscriptionStatus enum."""

    def test_all_statuses(self):
        assert SubscriptionStatus.ACTIVE == "active"
        assert SubscriptionStatus.CANCELLED == "cancelled"
        assert SubscriptionStatus.EXPIRED == "expired"
        assert SubscriptionStatus.PENDING == "pending"
        assert SubscriptionStatus.FAILED == "failed"


class TestQualityLevel:
    """Tests for QualityLevel enum."""

    def test_all_quality_levels(self):
        assert QualityLevel.SD == "sd"
        assert QualityLevel.HD == "hd"
        assert QualityLevel.FHD == "fhd"
        assert QualityLevel.UHD == "uhd"
        assert QualityLevel.LOSSLESS == "lossless"
