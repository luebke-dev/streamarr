import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Voucher(Base):
    """Voucher / gift code that grants a full membership for a fixed duration.

    A voucher is bound to a specific :class:`SubscriptionPackage` and grants
    ``duration_days`` of that package's membership when redeemed. Vouchers do
    not interact with Stripe — they create or extend a ``UserSubscription``
    directly and link the user to the package's group.

    Vouchers can be single- or multi-use (``max_uses``) and may have a
    code-level ``expires_at`` (the date the *code itself* becomes invalid,
    independent of the membership it grants).
    """

    __tablename__ = "voucher"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # The redeemable code (case-insensitive on lookup, stored uppercase).
    code: Mapped[str] = mapped_column(types.String(64), unique=True, index=True)

    # Which package is granted on redemption.
    package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscription_package.guid", ondelete="RESTRICT"), index=True
    )

    # Duration of membership granted in days.
    duration_days: Mapped[int] = mapped_column()

    # Multi-use bookkeeping. ``max_uses=1`` makes the voucher single-use.
    max_uses: Mapped[int] = mapped_column(default=1)
    current_uses: Mapped[int] = mapped_column(default=0)

    # When the *code* itself expires (NULL = never). Independent of membership.
    expires_at: Mapped[datetime | None] = mapped_column()

    # Soft-disable without deleting (preserves redemption audit trail).
    is_active: Mapped[bool] = mapped_column(default=True)

    # Optional human-readable note (e.g. "Black Friday 2026", "Gift for Alice").
    note: Mapped[str | None] = mapped_column(types.String(255))

    # Admin who created it (RESTRICT — we don't want to lose attribution
    # silently when a user is removed; explicit cleanup if needed).
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.guid", ondelete="SET NULL")
    )

    # Relationships
    package = relationship("SubscriptionPackage")
    created_by = relationship("User", foreign_keys=[created_by_id])
    redemptions = relationship(
        "VoucherRedemption", back_populates="voucher", cascade="all, delete-orphan"
    )


class VoucherRedemption(Base):
    """Audit record of a voucher being redeemed by a user."""

    __tablename__ = "voucher_redemption"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    redeemed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    voucher_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("voucher.guid", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.guid", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_subscription.guid", ondelete="RESTRICT")
    )

    # Relationships
    voucher = relationship("Voucher", back_populates="redemptions")
    user = relationship("User")
    subscription = relationship("UserSubscription")
