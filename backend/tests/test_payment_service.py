"""Tests for the PaymentService (webhook handling + provider delegation)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.subscription import (
    PaymentHistory,
    SubscriptionStatus,
    UserSubscription,
)
from pyrate.models.user import User
from pyrate.services.payment import PaymentService


# ---------------------------------------------------------------------------
# Mock payment provider
# ---------------------------------------------------------------------------

class MockPaymentProvider:
    """Fake payment provider that records calls."""

    def __init__(self):
        self.create_product_and_price = AsyncMock(return_value=("product_1", "price_1"))
        self.create_subscription = AsyncMock(return_value={"id": "sub_provider_1"})
        self.cancel_subscription = AsyncMock(return_value=True)
        self.get_subscription_status = AsyncMock(
            return_value={"status": "active", "id": "sub_provider_1"}
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def provider() -> MockPaymentProvider:
    return MockPaymentProvider()


@pytest_asyncio.fixture
async def service(
    db_session: AsyncSession, provider: MockPaymentProvider
) -> PaymentService:
    return PaymentService(db=db_session, payment_provider=provider)


@pytest_asyncio.fixture
async def user_subscription(
    db_session: AsyncSession, test_user: User
) -> UserSubscription:
    sub = UserSubscription(
        user_id=test_user.guid,
        package_id=uuid.uuid4(),
        starts_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        stripe_subscription_id="sub_stripe_001",
        stripe_customer_id="cus_stripe_001",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


# ---------------------------------------------------------------------------
# Provider delegation
# ---------------------------------------------------------------------------

class TestProviderDelegation:
    @pytest.mark.asyncio
    async def test_create_product_and_price(
        self, service: PaymentService, provider: MockPaymentProvider
    ):
        product, price = await service.create_product_and_price(
            name="Pro Plan", description="Pro", price=19.99
        )
        assert product == "product_1"
        provider.create_product_and_price.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_subscription(
        self, service: PaymentService, provider: MockPaymentProvider
    ):
        result = await service.create_subscription(
            user_email="user@example.com", price_id="price_1"
        )
        assert result["id"] == "sub_provider_1"
        provider.create_subscription.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_subscription(
        self, service: PaymentService, provider: MockPaymentProvider
    ):
        result = await service.cancel_subscription("sub_provider_1")
        assert result is True
        provider.cancel_subscription.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_subscription_status(
        self, service: PaymentService, provider: MockPaymentProvider
    ):
        result = await service.get_subscription_status("sub_provider_1")
        assert result["status"] == "active"


# ---------------------------------------------------------------------------
# Webhook handlers
# ---------------------------------------------------------------------------

class TestWebhookHandlers:
    @pytest.mark.asyncio
    async def test_handle_payment_succeeded(
        self,
        service: PaymentService,
        user_subscription: UserSubscription,
        db_session: AsyncSession,
    ):
        event_data = {
            "subscription": "sub_stripe_001",
            "payment_intent": "pi_001",
            "amount_paid": 999,
            "currency": "usd",
            "id": "inv_001",
        }
        await service.handle_payment_succeeded(event_data)

        # Subscription should be ACTIVE
        await db_session.refresh(user_subscription)
        assert user_subscription.status == SubscriptionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_handle_payment_succeeded_no_subscription_id(
        self, service: PaymentService
    ):
        # Should return early without error
        await service.handle_payment_succeeded({})

    @pytest.mark.asyncio
    async def test_handle_payment_succeeded_unknown_subscription(
        self, service: PaymentService
    ):
        await service.handle_payment_succeeded({"subscription": "sub_unknown"})

    @pytest.mark.asyncio
    async def test_handle_payment_failed(
        self,
        service: PaymentService,
        user_subscription: UserSubscription,
        db_session: AsyncSession,
    ):
        event_data = {
            "subscription": "sub_stripe_001",
            "payment_intent": "pi_002",
            "amount_due": 999,
            "currency": "usd",
            "id": "inv_002",
        }
        await service.handle_payment_failed(event_data)

        await db_session.refresh(user_subscription)
        assert user_subscription.status == SubscriptionStatus.FAILED

    @pytest.mark.asyncio
    async def test_handle_payment_failed_no_subscription_id(
        self, service: PaymentService
    ):
        await service.handle_payment_failed({})

    @pytest.mark.asyncio
    async def test_handle_subscription_updated_active(
        self,
        service: PaymentService,
        user_subscription: UserSubscription,
        db_session: AsyncSession,
    ):
        event_data = {
            "id": "sub_stripe_001",
            "status": "active",
            "current_period_start": int(datetime.now(UTC).timestamp()),
            "current_period_end": int((datetime.now(UTC) + timedelta(days=30)).timestamp()),
        }
        await service.handle_subscription_updated(event_data)

        await db_session.refresh(user_subscription)
        assert user_subscription.status == SubscriptionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_handle_subscription_updated_canceled(
        self,
        service: PaymentService,
        user_subscription: UserSubscription,
        db_session: AsyncSession,
    ):
        event_data = {"id": "sub_stripe_001", "status": "canceled"}
        await service.handle_subscription_updated(event_data)

        await db_session.refresh(user_subscription)
        assert user_subscription.status == SubscriptionStatus.CANCELLED
        assert user_subscription.cancelled_at is not None

    @pytest.mark.asyncio
    async def test_handle_subscription_updated_past_due(
        self,
        service: PaymentService,
        user_subscription: UserSubscription,
        db_session: AsyncSession,
    ):
        # past_due is a transient grace state during Stripe's retry window:
        # access and the current status are retained (not marked FAILED).
        status_before = user_subscription.status
        event_data = {"id": "sub_stripe_001", "status": "past_due"}
        await service.handle_subscription_updated(event_data)

        await db_session.refresh(user_subscription)
        assert user_subscription.status != SubscriptionStatus.FAILED
        assert user_subscription.status == status_before

    @pytest.mark.asyncio
    async def test_handle_subscription_deleted(
        self,
        service: PaymentService,
        user_subscription: UserSubscription,
        db_session: AsyncSession,
    ):
        event_data = {"id": "sub_stripe_001"}
        await service.handle_subscription_deleted(event_data)

        await db_session.refresh(user_subscription)
        assert user_subscription.status == SubscriptionStatus.CANCELLED
        assert user_subscription.cancelled_at is not None

    @pytest.mark.asyncio
    async def test_handle_subscription_deleted_no_id(self, service: PaymentService):
        await service.handle_subscription_deleted({})

    @pytest.mark.asyncio
    async def test_handle_subscription_deleted_unknown(self, service: PaymentService):
        await service.handle_subscription_deleted({"id": "sub_unknown"})
