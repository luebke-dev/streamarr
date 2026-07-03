"""Tests for the SubscriptionService."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.group import Group
from pyrate.models.subscription import SubscriptionPackage, UserSubscription
from pyrate.models.user import User
from pyrate.services.subscription import SubscriptionService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def service(db_session: AsyncSession) -> SubscriptionService:
    return SubscriptionService(db_session)


async def _create_group(
    db_session: AsyncSession,
    *,
    name: str = "Subscription Group",
    allowed_libraries: list[str] | None = None,
    max_concurrent_streams: int = 2,
) -> Group:
    group = Group(
        guid=uuid.uuid4(),
        name=f"{name}-{uuid.uuid4()}",
        allowed_libraries=allowed_libraries or ["MOVIES", "SHOWS"],
        max_concurrent_streams=max_concurrent_streams,
    )
    db_session.add(group)
    await db_session.flush()
    return group


@pytest_asyncio.fixture
async def sample_package(service: SubscriptionService) -> SubscriptionPackage:
    group = await _create_group(service.db)
    return await service.create_package(
        name="Basic",
        description="Basic plan",
        price_cents=999,
        group_id=group.guid,
    )


@pytest_asyncio.fixture
async def sample_subscription(
    service: SubscriptionService, test_user: User, sample_package: SubscriptionPackage
) -> UserSubscription:
    return await service.create_subscription(
        user_id=test_user.guid, package_id=sample_package.guid
    )


# ---------------------------------------------------------------------------
# Package CRUD
# ---------------------------------------------------------------------------

class TestPackageCRUD:
    @pytest.mark.asyncio
    async def test_create_package(self, service: SubscriptionService):
        group = await _create_group(
            service.db,
            name="Premium Group",
            allowed_libraries=["MOVIES", "SHOWS", "GAMES"],
            max_concurrent_streams=5,
        )
        pkg = await service.create_package(
            name="Premium",
            description="Premium plan",
            price_cents=1999,
            group_id=group.guid,
        )
        assert pkg.name == "Premium"
        assert pkg.price_cents == 1999
        assert pkg.group_id == group.guid
        assert pkg.is_active is True

    @pytest.mark.asyncio
    async def test_get_package(
        self, service: SubscriptionService, sample_package: SubscriptionPackage
    ):
        result = await service.get_package(sample_package.guid)
        assert result is not None
        assert result.name == "Basic"

    @pytest.mark.asyncio
    async def test_get_package_not_found(self, service: SubscriptionService):
        result = await service.get_package(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_packages(
        self, service: SubscriptionService, sample_package: SubscriptionPackage
    ):
        group = await _create_group(service.db, name="Premium Group", allowed_libraries=["MOVIES"])
        await service.create_package(
            name="Premium",
            description="Premium plan",
            price_cents=1999,
            group_id=group.guid,
        )
        packages = await service.get_packages()
        assert len(packages) == 2

    @pytest.mark.asyncio
    async def test_get_packages_active_only(self, service: SubscriptionService):
        old_group = await _create_group(service.db, name="Old Group", allowed_libraries=["MOVIES"])
        pkg = await service.create_package(
            name="Old Plan",
            description="Deprecated",
            price_cents=499,
            group_id=old_group.guid,
        )
        await service.deactivate_package(pkg.guid)

        active_group = await _create_group(service.db, name="Active Group", allowed_libraries=["MOVIES"])
        await service.create_package(
            name="Active Plan",
            description="Active",
            price_cents=999,
            group_id=active_group.guid,
        )

        active = await service.get_packages(active_only=True)
        assert len(active) == 1
        assert active[0].name == "Active Plan"

    @pytest.mark.asyncio
    async def test_update_package(
        self, service: SubscriptionService, sample_package: SubscriptionPackage
    ):
        updated = await service.update_package(
            sample_package.guid, name="Basic+", price_cents=1299
        )
        assert updated is not None
        assert updated.name == "Basic+"
        assert updated.price_cents == 1299

    @pytest.mark.asyncio
    async def test_update_package_not_found(self, service: SubscriptionService):
        result = await service.update_package(uuid.uuid4(), name="Ghost")
        assert result is None

    @pytest.mark.asyncio
    async def test_deactivate_package(
        self, service: SubscriptionService, sample_package: SubscriptionPackage
    ):
        result = await service.deactivate_package(sample_package.guid)
        assert result is True
        pkg = await service.get_package(sample_package.guid)
        assert pkg.is_active is False

    @pytest.mark.asyncio
    async def test_deactivate_package_not_found(self, service: SubscriptionService):
        result = await service.deactivate_package(uuid.uuid4())
        assert result is False


# ---------------------------------------------------------------------------
# User subscriptions
# ---------------------------------------------------------------------------

class TestUserSubscription:
    @pytest.mark.asyncio
    async def test_create_subscription(
        self, service: SubscriptionService, test_user: User, sample_package: SubscriptionPackage
    ):
        sub = await service.create_subscription(
            user_id=test_user.guid, package_id=sample_package.guid
        )
        assert sub.user_id == test_user.guid
        assert sub.package_id == sample_package.guid
        assert sub.starts_at is not None
        assert sub.expires_at > sub.starts_at

    @pytest.mark.asyncio
    async def test_get_user_subscription(
        self, service: SubscriptionService, sample_subscription: UserSubscription
    ):
        result = await service.get_user_subscription(sample_subscription.guid)
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_user_active_subscription(
        self,
        service: SubscriptionService,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        result = await service.get_user_active_subscription(test_user.guid)
        assert result is not None
        assert result.guid == sample_subscription.guid

    @pytest.mark.asyncio
    async def test_get_user_subscriptions(
        self,
        service: SubscriptionService,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        subs = await service.get_user_subscriptions(test_user.guid)
        assert len(subs) >= 1

    @pytest.mark.asyncio
    async def test_cancel_subscription(
        self, service: SubscriptionService, sample_subscription: UserSubscription
    ):
        result = await service.cancel_subscription(sample_subscription.guid)
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_subscription_not_found(self, service: SubscriptionService):
        result = await service.cancel_subscription(uuid.uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_extend_subscription(
        self, service: SubscriptionService, sample_subscription: UserSubscription
    ):
        original_expiry = sample_subscription.expires_at
        extended = await service.extend_subscription(sample_subscription.guid, days=15)
        assert extended is not None
        assert extended.expires_at > original_expiry

    @pytest.mark.asyncio
    async def test_extend_subscription_not_found(self, service: SubscriptionService):
        result = await service.extend_subscription(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_update_subscription(
        self, service: SubscriptionService, sample_subscription: UserSubscription
    ):
        result = await service.update_subscription(
            sample_subscription.guid, stripe_subscription_id="sub_123"
        )
        assert result is not None
        assert result.stripe_subscription_id == "sub_123"

    @pytest.mark.asyncio
    async def test_update_subscription_not_found(self, service: SubscriptionService):
        result = await service.update_subscription(uuid.uuid4(), stripe_subscription_id="sub_x")
        assert result is None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class TestUserSessions:
    @pytest.mark.asyncio
    async def test_create_session(
        self, service: SubscriptionService, test_user: User, sample_subscription: UserSubscription
    ):
        session = await service.create_session(
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            device_info="Chrome on Linux",
            ip_address="127.0.0.1",
        )
        assert session.user_id == test_user.guid
        assert session.device_info == "Chrome on Linux"

    @pytest.mark.asyncio
    async def test_get_active_sessions(
        self, service: SubscriptionService, test_user: User, sample_subscription: UserSubscription
    ):
        await service.create_session(user_id=test_user.guid, subscription_id=sample_subscription.guid)
        await service.create_session(user_id=test_user.guid, subscription_id=sample_subscription.guid)
        sessions = await service.get_active_sessions(test_user.guid)
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_get_active_session_count(
        self, service: SubscriptionService, test_user: User, sample_subscription: UserSubscription
    ):
        await service.create_session(user_id=test_user.guid, subscription_id=sample_subscription.guid)
        count = await service.get_active_session_count(test_user.guid)
        assert count == 1

    @pytest.mark.asyncio
    async def test_end_session(
        self, service: SubscriptionService, test_user: User, sample_subscription: UserSubscription
    ):
        session = await service.create_session(
            user_id=test_user.guid, subscription_id=sample_subscription.guid
        )
        result = await service.end_session(session.guid)
        assert result is True
        count = await service.get_active_session_count(test_user.guid)
        assert count == 0

    @pytest.mark.asyncio
    async def test_end_session_not_found(self, service: SubscriptionService):
        result = await service.end_session(uuid.uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_end_all_user_sessions(
        self, service: SubscriptionService, test_user: User, sample_subscription: UserSubscription
    ):
        await service.create_session(user_id=test_user.guid, subscription_id=sample_subscription.guid)
        await service.create_session(user_id=test_user.guid, subscription_id=sample_subscription.guid)
        count = await service.end_all_user_sessions(test_user.guid)
        assert count == 2
        active = await service.get_active_session_count(test_user.guid)
        assert active == 0

    @pytest.mark.asyncio
    async def test_cleanup_old_sessions(
        self, service: SubscriptionService, test_user: User, sample_subscription: UserSubscription, db_session: AsyncSession
    ):
        session = await service.create_session(
            user_id=test_user.guid, subscription_id=sample_subscription.guid
        )
        # Mark session as inactive and set created_at to be old
        session.is_active = False
        session.created_at = datetime.now(UTC) - timedelta(days=60)
        await db_session.commit()

        deleted = await service.cleanup_old_sessions(days_old=30)
        assert deleted == 1


# ---------------------------------------------------------------------------
# Payment history
# ---------------------------------------------------------------------------

class TestPaymentHistory:
    @pytest.mark.asyncio
    async def test_create_payment_record(
        self,
        service: SubscriptionService,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        payment = await service.create_payment_record(
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=999,
            currency="eur",
            stripe_payment_intent_id="pi_test123",
            status="succeeded",
        )
        assert payment.amount_cents == 999
        assert payment.currency == "eur"
        assert payment.status == "succeeded"

    @pytest.mark.asyncio
    async def test_get_payment_by_stripe_id(
        self,
        service: SubscriptionService,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        await service.create_payment_record(
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=999,
            stripe_payment_intent_id="pi_unique",
        )
        result = await service.get_payment_by_stripe_id("pi_unique")
        assert result is not None
        assert result.stripe_payment_intent_id == "pi_unique"

    @pytest.mark.asyncio
    async def test_get_payment_by_stripe_id_not_found(
        self, service: SubscriptionService
    ):
        result = await service.get_payment_by_stripe_id("pi_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_payments(
        self,
        service: SubscriptionService,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        await service.create_payment_record(
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=999,
        )
        await service.create_payment_record(
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=1999,
        )
        payments = await service.get_user_payments(test_user.guid)
        assert len(payments) == 2

    @pytest.mark.asyncio
    async def test_update_payment_status(
        self,
        service: SubscriptionService,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        payment = await service.create_payment_record(
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=999,
            status="pending",
        )
        updated = await service.update_payment_status(payment.guid, "succeeded")
        assert updated is not None
        assert updated.status == "succeeded"

    @pytest.mark.asyncio
    async def test_update_payment_status_not_found(self, service: SubscriptionService):
        result = await service.update_payment_status(uuid.uuid4(), "succeeded")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_subscription_payments(
        self,
        service: SubscriptionService,
        test_user: User,
        sample_subscription: UserSubscription,
    ):
        await service.create_payment_record(
            user_id=test_user.guid,
            subscription_id=sample_subscription.guid,
            amount_cents=999,
        )
        payments = await service.get_subscription_payments(sample_subscription.guid)
        assert len(payments) == 1
