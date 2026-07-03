import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


def get_available_library_types() -> list[str]:
    """Get available library types from registered library plugins.

    Returns:
        List of library type strings from all registered library plugins.
    """
    from pyrate.libraries import get_registered_plugins

    return list(get_registered_plugins().keys())


class QualityLevel(StrEnum):
    """Quality levels for content"""

    SD = "sd"  # Standard Definition
    HD = "hd"  # High Definition (720p)
    FHD = "fhd"  # Full HD (1080p)
    UHD = "uhd"  # Ultra HD (4K)
    LOSSLESS = "lossless"  # For music


class SubscriptionPackage(Base):
    """Subscription packages that admins can create.

    Each package is linked to a single :class:`Group`. The group is the
    single source of truth for the permissions a subscriber receives
    (allowed libraries, quality caps, concurrent streams, rate limits, ...);
    when a user subscribes the backend creates a ``UserGroupLink`` to that
    group, and removes it again on cancellation/expiry. Quality- and
    library-level details therefore live exclusively on
    :class:`pyrate.models.group.Group`, not on the package itself.
    """

    __tablename__ = "subscription_package"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Package details
    name: Mapped[str] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column()
    price_cents: Mapped[int] = mapped_column()  # Price in cents for Stripe
    currency: Mapped[str] = mapped_column(default="EUR")
    is_active: Mapped[bool] = mapped_column(default=True)

    # Permissions live on the linked Group (1:1). Subscribing creates a
    # UserGroupLink, cancellation removes it. RESTRICT prevents deleting a
    # group that still has packages pointing at it.
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("group.guid", ondelete="RESTRICT"), index=True
    )

    # Stripe integration
    stripe_price_id: Mapped[str | None] = mapped_column(unique=True)  # Stripe Price ID
    stripe_product_id: Mapped[str | None] = mapped_column()  # Stripe Product ID

    # Relationships
    group = relationship("Group")
    subscriptions = relationship("UserSubscription", back_populates="package")


class SubscriptionStatus(StrEnum):
    """Subscription status"""

    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PENDING = "pending"
    FAILED = "failed"


class UserSubscription(Base):
    """User subscriptions to packages"""

    __tablename__ = "user_subscription"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Foreign keys
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.guid", ondelete="CASCADE")
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscription_package.guid", ondelete="RESTRICT")
    )

    # Subscription details
    status: Mapped[SubscriptionStatus] = mapped_column(
        default=SubscriptionStatus.PENDING
    )
    starts_at: Mapped[datetime] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column()
    cancelled_at: Mapped[datetime | None] = mapped_column()

    # Stripe integration
    stripe_subscription_id: Mapped[str | None] = mapped_column(unique=True)
    stripe_customer_id: Mapped[str | None] = mapped_column()

    # Current usage tracking
    current_sessions: Mapped[int] = mapped_column(default=0)

    # Relationships
    user = relationship("User", back_populates="subscriptions")
    package = relationship("SubscriptionPackage", back_populates="subscriptions")
    sessions = relationship("UserSession", back_populates="subscription")


class UserSession(Base):
    """Track active user sessions for concurrent session limits"""

    __tablename__ = "user_session"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Foreign keys
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.guid", ondelete="CASCADE")
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_subscription.guid", ondelete="CASCADE")
    )

    # Session details
    session_token: Mapped[str] = mapped_column(unique=True, index=True)
    device_info: Mapped[str | None] = mapped_column()  # Device/browser info
    ip_address: Mapped[str | None] = mapped_column()
    last_activity: Mapped[datetime] = mapped_column(server_default=func.now())
    is_active: Mapped[bool] = mapped_column(default=True)

    # Content being accessed
    content_type: Mapped[str | None] = mapped_column()  # movie, series, game, etc.
    content_id: Mapped[str | None] = mapped_column()  # ID of the content

    # Relationships
    user = relationship("User", back_populates="sessions")
    subscription = relationship("UserSubscription", back_populates="sessions")


class PaymentHistory(Base):
    """Track payment history for subscriptions"""

    __tablename__ = "payment_history"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Foreign keys — payment history is financial data, so we don't cascade
    # it away when a user or subscription is deleted (explicit admin action).
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.guid", ondelete="RESTRICT")
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_subscription.guid", ondelete="RESTRICT")
    )

    # Payment details. Column sizes keep arbitrary payloads in check.
    amount_cents: Mapped[int] = mapped_column()
    currency: Mapped[str] = mapped_column(types.String(10))
    status: Mapped[str] = mapped_column(types.String(32))  # succeeded, failed, pending, etc.

    # Stripe integration
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(unique=True)
    stripe_invoice_id: Mapped[str | None] = mapped_column()

    # Additional info
    failure_reason: Mapped[str | None] = mapped_column()
    payment_metadata: Mapped[dict | None] = mapped_column(JSON)

    # Relationships
    user = relationship("User")
    subscription = relationship("UserSubscription")
