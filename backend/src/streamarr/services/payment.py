"""
Payment service for handling subscription payments and billing.

This service provides a unified interface for payment operations,
delegating to payment provider plugins (Stripe, PayPal, etc.).
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamarr.models.group import UserGroupLink
from streamarr.models.subscription import (
    PaymentHistory,
    SubscriptionStatus,
    UserSubscription,
)
from streamarr.payments.base import PaymentProviderPlugin

logger = logging.getLogger(__name__)


class PaymentService:
    """
    Service for handling payment operations.

    This service provides a unified interface for payment operations,
    abstracting away the specific payment provider implementation.
    """

    def __init__(
        self,
        db: AsyncSession,
        payment_provider: PaymentProviderPlugin,
    ):
        """
        Initialize the payment service.

        Args:
            db: Database session
            payment_provider: Payment provider plugin instance
        """
        self.db = db
        self.provider = payment_provider

    async def create_product_and_price(
        self,
        name: str,
        description: str,
        price: float,
        currency: str = "usd",
        interval: str = "month",
        metadata: dict[str, str] | None = None,
    ) -> tuple[Any, Any]:
        """
        Create a product and price for a subscription.

        Args:
            name: Product name
            description: Product description
            price: Price in currency units
            currency: Currency code
            interval: Billing interval
            metadata: Additional metadata

        Returns:
            Tuple of (product, price) objects
        """
        return await self.provider.create_product_and_price(
            name=name,
            description=description,
            price=price,
            currency=currency,
            interval=interval,
            metadata=metadata,
        )

    async def create_subscription(
        self,
        user_email: str,
        price_id: str,
        payment_method_id: str | None = None,
        customer_id: str | None = None,
    ) -> Any:
        """
        Create a new subscription for a user.

        Args:
            user_email: User's email address
            price_id: Price ID from payment provider
            payment_method_id: Payment method ID
            customer_id: Existing customer ID

        Returns:
            Subscription object from payment provider
        """
        return await self.provider.create_subscription(
            user_email=user_email,
            price_id=price_id,
            payment_method_id=payment_method_id,
            customer_id=customer_id,
        )

    async def cancel_subscription(
        self,
        subscription_id: str,
        cancel_at_period_end: bool = True,
    ) -> bool:
        """
        Cancel a subscription.

        Args:
            subscription_id: Subscription ID from payment provider
            cancel_at_period_end: Whether to cancel at period end

        Returns:
            bool: True if cancellation was successful
        """
        return await self.provider.cancel_subscription(
            subscription_id=subscription_id,
            cancel_at_period_end=cancel_at_period_end,
        )

    async def get_subscription_status(
        self,
        subscription_id: str,
    ) -> dict[str, Any]:
        """
        Get subscription status from payment provider.

        Args:
            subscription_id: Subscription ID

        Returns:
            dict: Subscription status information
        """
        return await self.provider.get_subscription_status(subscription_id)

    # ------------------------------------------------------------------
    # Stripe.js / Elements support
    # ------------------------------------------------------------------

    async def get_or_create_customer(
        self,
        email: str,
        name: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Look up the Stripe customer for ``email`` or create one."""
        return await self.provider.get_or_create_customer(
            email=email, name=name, metadata=metadata,
        )

    async def create_setup_intent(
        self,
        customer_id: str,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a SetupIntent so the frontend can collect a payment method
        via Stripe Elements without an immediate charge.
        """
        return await self.provider.create_setup_intent(
            customer_id=customer_id, metadata=metadata,
        )

    async def list_payment_methods(
        self, customer_id: str
    ) -> list[dict[str, Any]]:
        """Return saved card payment methods for a customer."""
        return await self.provider.get_payment_methods(customer_id, type="card")

    async def detach_payment_method(self, payment_method_id: str) -> bool:
        """Detach a payment method from its customer."""
        return await self.provider.detach_payment_method(payment_method_id)

    async def set_default_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
    ) -> bool:
        """Mark ``payment_method_id`` as the default for invoices."""
        return await self.provider.set_default_payment_method(
            customer_id=customer_id, payment_method_id=payment_method_id,
        )

    async def list_invoices(
        self, customer_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return Stripe invoices for the customer (billing history)."""
        return await self.provider.get_invoices(customer_id, limit=limit)

    @staticmethod
    def _invoice_period_end(event_data: dict[str, Any]) -> int | None:
        """Extract the paid period end (unix ts) from a Stripe invoice payload."""
        lines = event_data.get("lines", {}).get("data", [])
        if lines:
            end = lines[0].get("period", {}).get("end")
            if end is not None:
                return end
        return event_data.get("period_end")

    async def _grant_group_link(
        self,
        user_subscription: UserSubscription,
    ) -> None:
        """Grant the package's linked group to the subscriber (idempotent)."""
        if user_subscription.package is None:
            return
        existing = await self.db.execute(
            select(UserGroupLink).where(
                UserGroupLink.user_id == user_subscription.user_id,
                UserGroupLink.group_id == user_subscription.package.group_id,
            )
        )
        if existing.scalar_one_or_none() is None:
            self.db.add(
                UserGroupLink(
                    user_id=user_subscription.user_id,
                    group_id=user_subscription.package.group_id,
                )
            )

    async def handle_payment_succeeded(
        self,
        event_data: dict[str, Any],
    ) -> None:
        """
        Handle successful payment webhook.

        Args:
            event_data: Payment event data from provider
        """
        subscription_id = event_data.get("subscription")
        if not subscription_id:
            logger.warning("No subscription ID in payment succeeded event")
            return

        # Find user subscription (eager-load package for group_id)
        result = await self.db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.package))
            .where(UserSubscription.stripe_subscription_id == subscription_id)
        )
        user_subscription = result.scalar_one_or_none()

        if not user_subscription:
            logger.warning("No subscription found for provider subscription %s", subscription_id)
            return

        if user_subscription.status != SubscriptionStatus.CANCELLED:
            user_subscription.status = SubscriptionStatus.ACTIVE
            period_end = self._invoice_period_end(event_data)
            if period_end is not None:
                user_subscription.expires_at = datetime.fromtimestamp(period_end, tz=UTC)
            await self._grant_group_link(user_subscription)

        # Idempotency guard: Stripe may re-deliver invoice.payment_succeeded
        # (and the Redis webhook dedupe fails open when Redis is down). A missing
        # payment_intent means the unique constraint on stripe_payment_intent_id
        # can't catch the duplicate (NULLs are distinct), so guard on the invoice
        # id explicitly and skip the second insert to avoid inflating revenue.
        invoice_id = event_data.get("id")
        if invoice_id is not None:
            existing = await self.db.execute(
                select(PaymentHistory).where(
                    PaymentHistory.stripe_invoice_id == invoice_id,
                    PaymentHistory.status == "succeeded",
                )
            )
            if existing.scalar_one_or_none() is not None:
                logger.info(
                    "Invoice %s already recorded as succeeded; skipping duplicate",
                    invoice_id,
                )
                # Persist the idempotent subscription/group updates made above.
                await self.db.commit()
                return

        # Create payment history record
        payment_history = PaymentHistory(
            user_id=user_subscription.user_id,
            subscription_id=user_subscription.guid,
            stripe_payment_intent_id=event_data.get("payment_intent"),
            amount_cents=event_data.get("amount_paid", 0),
            currency=event_data.get("currency", "usd"),
            status="succeeded",
            stripe_invoice_id=event_data.get("id"),
        )

        self.db.add(payment_history)
        await self.db.commit()

        logger.info("Payment succeeded for subscription %s", user_subscription.guid)

    async def handle_payment_failed(
        self,
        event_data: dict[str, Any],
    ) -> None:
        """
        Handle failed payment webhook.

        Args:
            event_data: Payment event data from provider
        """
        subscription_id = event_data.get("subscription")
        if not subscription_id:
            logger.warning("No subscription ID in payment failed event")
            return

        # Find user subscription
        result = await self.db.execute(
            select(UserSubscription).where(
                UserSubscription.stripe_subscription_id == subscription_id
            )
        )
        user_subscription = result.scalar_one_or_none()

        if not user_subscription:
            logger.warning("No subscription found for provider subscription %s", subscription_id)
            return

        # Update subscription status
        user_subscription.status = SubscriptionStatus.FAILED

        # Create payment history record
        payment_history = PaymentHistory(
            user_id=user_subscription.user_id,
            subscription_id=user_subscription.guid,
            stripe_payment_intent_id=event_data.get("payment_intent"),
            amount_cents=event_data.get("amount_due", 0),
            currency=event_data.get("currency", "usd"),
            status="failed",
            stripe_invoice_id=event_data.get("id"),
        )

        self.db.add(payment_history)
        await self.db.commit()

        logger.warning("Payment failed for subscription %s", user_subscription.guid)

    async def handle_subscription_updated(
        self,
        event_data: dict[str, Any],
    ) -> None:
        """
        Handle subscription updated webhook.

        Args:
            event_data: Subscription event data from provider
        """
        provider_subscription_id = event_data.get("id")
        if not provider_subscription_id:
            logger.warning("No subscription ID in subscription updated event")
            return

        # Find user subscription (eager-load package for group_id)
        result = await self.db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.package))
            .where(
                UserSubscription.stripe_subscription_id == provider_subscription_id
            )
        )
        user_subscription = result.scalar_one_or_none()

        if not user_subscription:
            logger.warning(
                "No subscription found for provider subscription %s",
                provider_subscription_id,
            )
            return

        # Update subscription details
        if event_data.get("current_period_start"):
            user_subscription.starts_at = datetime.fromtimestamp(
                event_data["current_period_start"], tz=UTC
            )
        if event_data.get("current_period_end"):
            user_subscription.expires_at = datetime.fromtimestamp(
                event_data["current_period_end"], tz=UTC
            )

        # Update status based on provider status
        provider_status = event_data.get("status")
        cancel_at_period_end = event_data.get("cancel_at_period_end", False)
        if provider_status in ("active", "trialing"):
            user_subscription.status = SubscriptionStatus.ACTIVE
            if cancel_at_period_end:
                # Scheduled to cancel: keep access until period end.
                if user_subscription.cancelled_at is None:
                    user_subscription.cancelled_at = datetime.now(UTC)
            else:
                user_subscription.cancelled_at = None
                await self._grant_group_link(user_subscription)
        elif provider_status in ("incomplete", "paused"):
            user_subscription.status = SubscriptionStatus.PENDING
        elif provider_status == "incomplete_expired":
            user_subscription.status = SubscriptionStatus.EXPIRED
        elif provider_status == "unpaid":
            user_subscription.status = SubscriptionStatus.FAILED
        elif provider_status == "canceled":
            user_subscription.status = SubscriptionStatus.CANCELLED
            user_subscription.cancelled_at = datetime.now(UTC)
            # Revoke the package's linked group from the user
            if user_subscription.package is not None:
                await self.db.execute(
                    delete(UserGroupLink).where(
                        UserGroupLink.user_id == user_subscription.user_id,
                        UserGroupLink.group_id == user_subscription.package.group_id,
                    )
                )
        # past_due: retain current status/access during the retry grace period.

        await self.db.commit()

        logger.info(
            "Updated subscription %s status to %s",
            user_subscription.guid, user_subscription.status,
        )

    async def handle_subscription_deleted(
        self,
        event_data: dict[str, Any],
    ) -> None:
        """
        Handle subscription deleted webhook.

        Args:
            event_data: Subscription event data from provider
        """
        provider_subscription_id = event_data.get("id")
        if not provider_subscription_id:
            logger.warning("No subscription ID in subscription deleted event")
            return

        # Find user subscription (eager-load package for group_id)
        result = await self.db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.package))
            .where(
                UserSubscription.stripe_subscription_id == provider_subscription_id
            )
        )
        user_subscription = result.scalar_one_or_none()

        if not user_subscription:
            logger.warning(
                "No subscription found for provider subscription %s",
                provider_subscription_id,
            )
            return

        # Update subscription status
        user_subscription.status = SubscriptionStatus.CANCELLED
        user_subscription.cancelled_at = datetime.now(UTC)

        # Revoke the package's linked group from the user
        if user_subscription.package is not None:
            await self.db.execute(
                delete(UserGroupLink).where(
                    UserGroupLink.user_id == user_subscription.user_id,
                    UserGroupLink.group_id == user_subscription.package.group_id,
                )
            )

        await self.db.commit()

        logger.info("Subscription %s deleted", user_subscription.guid)
