"""Subscription service for managing subscription packages, user subscriptions, sessions, and payments."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from pyrate.models.subscription import (
    PaymentHistory,
    SubscriptionPackage,
    SubscriptionStatus,
    UserSession,
    UserSubscription,
)


class SubscriptionService:
    """Service for managing all subscription-related operations."""

    def __init__(self, db: AsyncSession):
        """Initialize the subscription service.

        Args:
            db: Database session
        """
        self.db = db

    # ==================== Subscription Package Operations ====================

    async def create_package(
        self,
        name: str,
        description: str,
        price_cents: int,
        group_id: UUID,
        currency: str = "EUR",
        stripe_product_id: str | None = None,
        stripe_price_id: str | None = None,
    ) -> SubscriptionPackage:
        """Create a new subscription package.

        Permissions are sourced from the linked group (1:1 link); the package
        only stores pricing/branding/Stripe identifiers.

        Args:
            name: Package name
            description: Package description
            price_cents: Price in cents
            group_id: ID of the group whose permissions this package grants
            currency: ISO currency code the package is billed in; must match the
                currency used to create the Stripe price
            stripe_product_id: Stripe product ID
            stripe_price_id: Stripe price ID

        Returns:
            The created subscription package
        """
        package = SubscriptionPackage(
            name=name,
            description=description,
            price_cents=price_cents,
            group_id=group_id,
            currency=currency,
            stripe_product_id=stripe_product_id,
            stripe_price_id=stripe_price_id,
        )
        self.db.add(package)
        await self.db.commit()
        await self.db.refresh(package)
        logger.info(
            "Created subscription package name=%s id=%s group_id=%s price_cents=%d",
            name, package.guid, group_id, price_cents,
        )
        return package

    async def get_package(self, package_id: UUID) -> SubscriptionPackage | None:
        """Get a subscription package by ID.

        The linked Group is eagerly loaded so callers can read permission
        details (allowed libraries, quality caps, ...) without triggering a
        lazy-load round trip.

        Args:
            package_id: The package ID

        Returns:
            The package if found, None otherwise
        """
        result = await self.db.execute(
            select(SubscriptionPackage)
            .options(selectinload(SubscriptionPackage.group))
            .where(SubscriptionPackage.guid == package_id)
        )
        return result.scalar_one_or_none()

    async def get_packages(
        self, skip: int = 0, limit: int = 100, active_only: bool = True
    ) -> list[SubscriptionPackage]:
        """Get all subscription packages.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            active_only: Whether to only return active packages

        Returns:
            List of subscription packages
        """
        query = select(SubscriptionPackage).options(
            selectinload(SubscriptionPackage.group)
        )
        if active_only:
            query = query.where(SubscriptionPackage.is_active)
        query = query.offset(skip).limit(limit).order_by(SubscriptionPackage.created_at)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_package(
        self,
        package_id: UUID,
        **updates,
    ) -> SubscriptionPackage | None:
        """Update a subscription package.

        Args:
            package_id: The package ID
            **updates: Fields to update

        Returns:
            The updated package if found, None otherwise
        """
        result = await self.db.execute(
            select(SubscriptionPackage).where(SubscriptionPackage.guid == package_id)
        )
        package = result.scalar_one_or_none()
        if not package:
            logger.warning("Package not found for update: %s", package_id)
            return None

        for key, value in updates.items():
            if hasattr(package, key):
                setattr(package, key, value)

        package.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(package)
        logger.info("Updated subscription package id=%s fields=%s", package_id, list(updates.keys()))
        return package

    async def deactivate_package(self, package_id: UUID) -> bool:
        """Deactivate a subscription package.

        Args:
            package_id: The package ID

        Returns:
            True if package was deactivated, False if not found
        """
        result = await self.db.execute(
            select(SubscriptionPackage).where(SubscriptionPackage.guid == package_id)
        )
        package = result.scalar_one_or_none()
        if not package:
            logger.warning("Package not found for deactivation: %s", package_id)
            return False

        package.is_active = False
        package.updated_at = datetime.now(UTC)
        await self.db.commit()
        logger.info("Deactivated subscription package id=%s", package_id)
        return True

    # ==================== User Subscription Operations ====================

    async def create_subscription(
        self,
        user_id: UUID,
        package_id: UUID,
        stripe_subscription_id: str | None = None,
        stripe_customer_id: str | None = None,
    ) -> UserSubscription:
        """Create a new user subscription.

        Args:
            user_id: The user ID
            package_id: The package ID
            stripe_subscription_id: Stripe subscription ID
            stripe_customer_id: Stripe customer ID

        Returns:
            The created user subscription
        """
        now = datetime.now(UTC)
        subscription = UserSubscription(
            user_id=user_id,
            package_id=package_id,
            status=SubscriptionStatus.PENDING,
            starts_at=now,
            expires_at=now,
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
        )
        self.db.add(subscription)
        await self.db.commit()
        await self.db.refresh(subscription)
        logger.info("Created subscription user_id=%s package_id=%s id=%s", user_id, package_id, subscription.guid)
        return subscription

    async def get_user_subscription(
        self, subscription_id: UUID
    ) -> UserSubscription | None:
        """Get a user subscription by ID.

        Args:
            subscription_id: The subscription ID

        Returns:
            The subscription if found, None otherwise
        """
        result = await self.db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.package).selectinload(SubscriptionPackage.group))
            .where(UserSubscription.guid == subscription_id)
        )
        return result.scalar_one_or_none()

    async def get_user_active_subscription(
        self, user_id: UUID
    ) -> UserSubscription | None:
        """Get user's active subscription.

        Args:
            user_id: The user ID

        Returns:
            The active subscription if found, None otherwise
        """
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.package).selectinload(SubscriptionPackage.group))
            .where(
                and_(
                    UserSubscription.user_id == user_id,
                    UserSubscription.status == SubscriptionStatus.ACTIVE,
                    UserSubscription.starts_at <= now,
                    UserSubscription.expires_at > now,
                )
            )
            .order_by(UserSubscription.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_user_subscriptions(
        self, user_id: UUID, include_inactive: bool = False
    ) -> list[UserSubscription]:
        """Get all subscriptions for a user.

        Args:
            user_id: The user ID
            include_inactive: Whether to include inactive subscriptions

        Returns:
            List of user subscriptions
        """
        query = (
            select(UserSubscription)
            .options(selectinload(UserSubscription.package).selectinload(SubscriptionPackage.group))
            .where(UserSubscription.user_id == user_id)
        )
        if not include_inactive:
            query = query.where(UserSubscription.status == SubscriptionStatus.ACTIVE)
        query = query.order_by(UserSubscription.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_subscription(
        self,
        subscription_id: UUID,
        **updates,
    ) -> UserSubscription | None:
        """Update a user subscription.

        Args:
            subscription_id: The subscription ID
            **updates: Fields to update

        Returns:
            The updated subscription if found, None otherwise
        """
        result = await self.db.execute(
            select(UserSubscription).where(UserSubscription.guid == subscription_id)
        )
        subscription = result.scalar_one_or_none()
        if not subscription:
            logger.warning("Subscription not found for update: %s", subscription_id)
            return None

        for key, value in updates.items():
            if hasattr(subscription, key):
                setattr(subscription, key, value)

        subscription.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(subscription)
        logger.info("Updated subscription id=%s fields=%s", subscription_id, list(updates.keys()))
        return subscription

    async def cancel_subscription(
        self, subscription_id: UUID
    ) -> UserSubscription | None:
        """Mark a user subscription for cancellation at period end.

        Access is retained until ``expires_at``; the provider's
        subscription.deleted webhook revokes the group at period end.

        Args:
            subscription_id: The subscription ID

        Returns:
            The subscription if found, None otherwise
        """
        result = await self.db.execute(
            select(UserSubscription).where(UserSubscription.guid == subscription_id)
        )
        subscription = result.scalar_one_or_none()
        if not subscription:
            logger.warning("Subscription not found for cancellation: %s", subscription_id)
            return None

        subscription.cancelled_at = datetime.now(UTC)
        subscription.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(subscription)
        logger.info("Marked subscription for cancellation id=%s user_id=%s", subscription_id, subscription.user_id)
        return subscription

    async def extend_subscription(
        self, subscription_id: UUID, days: int = 30
    ) -> UserSubscription | None:
        """Extend a subscription by specified days.

        Args:
            subscription_id: The subscription ID
            days: Number of days to extend

        Returns:
            The extended subscription if found, None otherwise
        """
        result = await self.db.execute(
            select(UserSubscription).where(UserSubscription.guid == subscription_id)
        )
        subscription = result.scalar_one_or_none()
        if not subscription:
            logger.warning("Subscription not found for extension: %s", subscription_id)
            return None

        subscription.expires_at = subscription.expires_at + timedelta(days=days)
        subscription.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(subscription)
        logger.info("Extended subscription id=%s by %d days, new_expiry=%s", subscription_id, days, subscription.expires_at)
        return subscription

    # ==================== User Session Operations ====================

    async def create_session(
        self,
        user_id: UUID,
        subscription_id: UUID | None = None,
        device_info: str | None = None,
        ip_address: str | None = None,
    ) -> UserSession:
        """Create a new user session.

        Args:
            user_id: The user ID
            device_info: Device information
            ip_address: IP address

        Returns:
            The created user session
        """
        import secrets
        session = UserSession(
            user_id=user_id,
            subscription_id=subscription_id,
            device_info=device_info,
            ip_address=ip_address,
            session_token=secrets.token_urlsafe(32),
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def get_active_sessions(self, user_id: UUID) -> list[UserSession]:
        """Get all active sessions for a user.

        Args:
            user_id: The user ID

        Returns:
            List of active user sessions
        """
        result = await self.db.execute(
            select(UserSession).where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.is_active,
                )
            )
        )
        return list(result.scalars().all())

    async def get_active_session_count(self, user_id: UUID) -> int:
        """Get count of active sessions for a user.

        Args:
            user_id: The user ID

        Returns:
            Number of active sessions
        """
        result = await self.db.execute(
            select(func.count(UserSession.guid)).where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.is_active,
                )
            )
        )
        return result.scalar() or 0

    async def end_session(
        self, session_id: UUID, user_id: UUID | None = None
    ) -> bool:
        """End a user session.

        Args:
            session_id: The session ID
            user_id: If provided, only end the session when it belongs to this
                user (prevents one user from ending another user's session).

        Returns:
            True if session was ended, False if not found (or not owned by
            ``user_id`` when that is supplied)
        """
        query = select(UserSession).where(UserSession.guid == session_id)
        if user_id is not None:
            query = query.where(UserSession.user_id == user_id)
        result = await self.db.execute(query)
        session = result.scalar_one_or_none()
        if not session:
            logger.warning("Session not found for termination: %s", session_id)
            return False

        session.is_active = False
        await self.db.commit()
        logger.info("Ended session id=%s", session_id)
        return True

    async def end_all_user_sessions(self, user_id: UUID) -> int:
        """End all active sessions for a user.

        Args:
            user_id: The user ID

        Returns:
            Count of ended sessions
        """
        active_sessions = await self.get_active_sessions(user_id)
        count = 0
        for session in active_sessions:
            session.is_active = False
            count += 1

        if count > 0:
            await self.db.commit()
            logger.info("Ended all sessions for user_id=%s count=%d", user_id, count)
        return count

    async def cleanup_old_sessions(self, days_old: int = 30) -> int:
        """Clean up sessions older than specified days.

        Args:
            days_old: Age threshold in days

        Returns:
            Count of deleted sessions
        """
        cutoff_date = datetime.now(UTC) - timedelta(days=days_old)
        result = await self.db.execute(
            select(UserSession).where(
                and_(
                    UserSession.created_at < cutoff_date,
                    UserSession.is_active.is_(False),
                )
            )
        )
        old_sessions = result.scalars().all()
        count = len(old_sessions)

        for session in old_sessions:
            await self.db.delete(session)

        if count > 0:
            await self.db.commit()
            logger.info("Cleaned up %d old sessions older than %d days", count, days_old)
        return count

    # ==================== Payment History Operations ====================

    async def create_payment_record(
        self,
        user_id: UUID,
        subscription_id: UUID,
        amount_cents: int,
        currency: str = "usd",
        stripe_payment_intent_id: str | None = None,
        stripe_invoice_id: str | None = None,
        status: str = "pending",
    ) -> PaymentHistory:
        """Create a new payment history record.

        Args:
            user_id: The user ID
            subscription_id: The subscription ID
            amount_cents: Payment amount in cents
            currency: Currency code (default: usd)
            stripe_payment_intent_id: Stripe payment intent ID
            stripe_invoice_id: Stripe invoice ID
            status: Payment status

        Returns:
            The created payment record
        """
        payment = PaymentHistory(
            user_id=user_id,
            subscription_id=subscription_id,
            amount_cents=amount_cents,
            currency=currency,
            stripe_payment_intent_id=stripe_payment_intent_id,
            stripe_invoice_id=stripe_invoice_id,
            status=status,
        )
        self.db.add(payment)
        await self.db.commit()
        await self.db.refresh(payment)
        logger.info("Created payment record id=%s user_id=%s amount_cents=%d status=%s", payment.guid, user_id, amount_cents, status)
        return payment

    async def get_payment_by_stripe_id(
        self, stripe_payment_intent_id: str
    ) -> PaymentHistory | None:
        """Get payment record by Stripe payment intent ID.

        Args:
            stripe_payment_intent_id: The Stripe payment intent ID

        Returns:
            The payment record if found, None otherwise
        """
        result = await self.db.execute(
            select(PaymentHistory).where(
                PaymentHistory.stripe_payment_intent_id == stripe_payment_intent_id
            )
        )
        return result.scalar_one_or_none()

    async def get_user_payments(
        self, user_id: UUID, skip: int = 0, limit: int = 50
    ) -> list[PaymentHistory]:
        """Get payment history for a user.

        Args:
            user_id: The user ID
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List of payment records
        """
        result = await self.db.execute(
            select(PaymentHistory)
            .where(PaymentHistory.user_id == user_id)
            .order_by(PaymentHistory.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_payment_status(
        self, payment_id: UUID, status: str
    ) -> PaymentHistory | None:
        """Update payment status.

        Args:
            payment_id: The payment ID
            status: New payment status

        Returns:
            The updated payment record if found, None otherwise
        """
        result = await self.db.execute(
            select(PaymentHistory).where(PaymentHistory.guid == payment_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.warning("Payment not found for status update: %s", payment_id)
            return None

        payment.status = status
        payment.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(payment)
        logger.info("Updated payment status id=%s new_status=%s", payment_id, status)
        return payment

    async def get_subscription_payments(
        self, subscription_id: UUID
    ) -> list[PaymentHistory]:
        """Get all payments for a subscription.

        Args:
            subscription_id: The subscription ID

        Returns:
            List of payment records
        """
        result = await self.db.execute(
            select(PaymentHistory)
            .where(PaymentHistory.subscription_id == subscription_id)
            .order_by(PaymentHistory.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_stats(self) -> dict:
        """Aggregate subscription statistics (package/subscription counts, revenue).

        Returns a dict with ``total_packages``, ``active_subscriptions``,
        ``total_subscriptions``, ``total_revenue`` and ``monthly_revenue``
        (revenues as ``Decimal`` euros).
        """
        from decimal import Decimal

        total_packages = (
            await self.db.execute(
                select(func.count(SubscriptionPackage.guid)).where(
                    SubscriptionPackage.is_active
                )
            )
        ).scalar() or 0

        active_subscriptions = (
            await self.db.execute(
                select(func.count(UserSubscription.guid)).where(
                    UserSubscription.status == SubscriptionStatus.ACTIVE
                )
            )
        ).scalar() or 0

        total_subscriptions = (
            await self.db.execute(select(func.count(UserSubscription.guid)))
        ).scalar() or 0

        total_revenue_cents = (
            await self.db.execute(
                select(func.sum(PaymentHistory.amount_cents)).where(
                    PaymentHistory.status == "succeeded"
                )
            )
        ).scalar() or 0

        month_start = datetime.now(UTC).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        monthly_revenue_cents = (
            await self.db.execute(
                select(func.sum(PaymentHistory.amount_cents)).where(
                    PaymentHistory.status == "succeeded",
                    PaymentHistory.created_at >= month_start,
                )
            )
        ).scalar() or 0

        return {
            "total_packages": total_packages,
            "active_subscriptions": active_subscriptions,
            "total_subscriptions": total_subscriptions,
            "total_revenue": Decimal(total_revenue_cents) / Decimal(100),
            "monthly_revenue": Decimal(monthly_revenue_cents) / Decimal(100),
        }
