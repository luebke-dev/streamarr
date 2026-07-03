"""Service for managing voucher / gift codes that grant memberships."""

import logging
import secrets
import string
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.group import UserGroupLink
from pyrate.models.subscription import (
    SubscriptionPackage,
    SubscriptionStatus,
    UserSubscription,
)
from pyrate.models.voucher import Voucher, VoucherRedemption

logger = logging.getLogger(__name__)

# Unambiguous alphabet (no 0/O/1/I/L) for human-friendly codes.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 12


class VoucherError(Exception):
    """Base exception for voucher operations."""


class VoucherNotFoundError(VoucherError):
    pass


class VoucherInactiveError(VoucherError):
    pass


class VoucherExhaustedError(VoucherError):
    pass


class VoucherCodeExpiredError(VoucherError):
    pass


class VoucherConflictError(VoucherError):
    """User already has an active subscription for a *different* package."""


def _generate_code(prefix: str | None = None) -> str:
    body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    if prefix:
        return f"{prefix.upper()}-{body}"
    return body


def _normalise_code(code: str) -> str:
    return code.strip().upper()


class VoucherService:
    """Service for creating, listing, and redeeming vouchers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== Admin: create / list / update / delete ====================

    async def create_voucher(
        self,
        *,
        package_id: UUID,
        duration_days: int,
        max_uses: int = 1,
        expires_at: datetime | None = None,
        note: str | None = None,
        is_active: bool = True,
        code: str | None = None,
        created_by_id: UUID | None = None,
    ) -> Voucher:
        """Create a single voucher. If ``code`` is None one is generated."""
        # Make sure the package exists and is usable.
        pkg = await self.db.get(SubscriptionPackage, package_id)
        if pkg is None:
            raise VoucherError(f"Subscription package {package_id} not found")

        final_code = _normalise_code(code) if code else _generate_code()

        # Retry a couple of times on collision when auto-generating.
        for attempt in range(5):
            voucher = Voucher(
                code=final_code,
                package_id=package_id,
                duration_days=duration_days,
                max_uses=max_uses,
                current_uses=0,
                expires_at=expires_at,
                is_active=is_active,
                note=note,
                created_by_id=created_by_id,
            )
            self.db.add(voucher)
            try:
                await self.db.commit()
                await self.db.refresh(voucher)
                logger.info(
                    "Created voucher code=%s package_id=%s max_uses=%s",
                    voucher.code,
                    package_id,
                    max_uses,
                )
                return voucher
            except IntegrityError:
                await self.db.rollback()
                if code is not None:
                    # User-supplied code already taken — propagate.
                    raise
                final_code = _generate_code()
        raise VoucherError("Failed to generate unique voucher code after several attempts")

    async def create_batch(
        self,
        *,
        count: int,
        package_id: UUID,
        duration_days: int,
        max_uses: int = 1,
        expires_at: datetime | None = None,
        note: str | None = None,
        is_active: bool = True,
        prefix: str | None = None,
        created_by_id: UUID | None = None,
    ) -> list[Voucher]:
        """Generate ``count`` vouchers in one go (auto-generated codes)."""
        pkg = await self.db.get(SubscriptionPackage, package_id)
        if pkg is None:
            raise VoucherError(f"Subscription package {package_id} not found")

        created: list[Voucher] = []
        for _ in range(count):
            # Per-row commit so a single collision doesn't roll back the batch.
            for _attempt in range(5):
                voucher = Voucher(
                    code=_generate_code(prefix),
                    package_id=package_id,
                    duration_days=duration_days,
                    max_uses=max_uses,
                    current_uses=0,
                    expires_at=expires_at,
                    is_active=is_active,
                    note=note,
                    created_by_id=created_by_id,
                )
                self.db.add(voucher)
                try:
                    await self.db.commit()
                    await self.db.refresh(voucher)
                    created.append(voucher)
                    break
                except IntegrityError:
                    await self.db.rollback()
                    continue
            else:
                logger.warning(
                    "Batch voucher generation: failed to create unique code after retries"
                )
        logger.info(
            "Created %d/%d vouchers in batch (package_id=%s)",
            len(created),
            count,
            package_id,
        )
        return created

    async def list_vouchers(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        active_only: bool = False,
    ) -> list[Voucher]:
        stmt = select(Voucher).options(selectinload(Voucher.package))
        if active_only:
            stmt = stmt.where(Voucher.is_active.is_(True))
        stmt = stmt.order_by(Voucher.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_voucher(self, voucher_id: UUID) -> Voucher | None:
        stmt = (
            select(Voucher)
            .where(Voucher.guid == voucher_id)
            .options(selectinload(Voucher.package))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_vouchers_by_ids(self, voucher_ids: list[UUID]) -> list[Voucher]:
        """Fetch many vouchers with their packages eager-loaded in one round trip."""
        if not voucher_ids:
            return []
        stmt = (
            select(Voucher)
            .where(Voucher.guid.in_(voucher_ids))
            .options(selectinload(Voucher.package))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_voucher(
        self, voucher_id: UUID, **updates
    ) -> Voucher | None:
        voucher = await self.db.get(Voucher, voucher_id)
        if voucher is None:
            return None
        for field, value in updates.items():
            if value is None:
                continue
            if hasattr(voucher, field):
                setattr(voucher, field, value)
        await self.db.commit()
        await self.db.refresh(voucher)
        return voucher

    async def delete_voucher(self, voucher_id: UUID) -> bool:
        voucher = await self.db.get(Voucher, voucher_id)
        if voucher is None:
            return False
        await self.db.delete(voucher)
        await self.db.commit()
        logger.info("Deleted voucher id=%s code=%s", voucher_id, voucher.code)
        return True

    # ==================== User: redeem ====================

    async def redeem(
        self,
        *,
        code: str,
        user_id: UUID,
    ) -> tuple[UserSubscription, bool]:
        """Redeem a voucher for ``user_id``.

        Returns a tuple ``(subscription, extended)`` where ``extended`` is
        True if an existing active subscription was prolonged and False if a
        new one was created.

        Behaviour matrix when the user already holds an active subscription:
        - Same package      -> extend ``expires_at`` by ``duration_days``.
        - Different package -> raise :class:`VoucherConflictError`.

        Raises various :class:`VoucherError` subclasses on validation failure.
        """
        normalised = _normalise_code(code)

        stmt = (
            select(Voucher)
            .where(func.upper(Voucher.code) == normalised)
            .options(selectinload(Voucher.package))
        )
        voucher = (await self.db.execute(stmt)).scalar_one_or_none()
        if voucher is None:
            raise VoucherNotFoundError("Voucher code not found")

        now = datetime.now(UTC)
        if not voucher.is_active:
            raise VoucherInactiveError("Voucher is not active")
        if voucher.expires_at is not None and voucher.expires_at <= now:
            raise VoucherCodeExpiredError("Voucher code has expired")

        # Atomically claim a use so concurrent redemptions can't over-redeem.
        claimed = await self.db.execute(
            update(Voucher)
            .where(
                Voucher.guid == voucher.guid,
                Voucher.current_uses < Voucher.max_uses,
            )
            .values(current_uses=Voucher.current_uses + 1)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount == 0:
            raise VoucherExhaustedError("Voucher has no remaining uses")

        # Look at existing active subscription.
        active_stmt = select(UserSubscription).where(
            UserSubscription.user_id == user_id,
            UserSubscription.status == SubscriptionStatus.ACTIVE,
            UserSubscription.starts_at <= now,
            UserSubscription.expires_at > now,
        )
        active = (await self.db.execute(active_stmt)).scalar_one_or_none()

        extended = False
        if active is not None:
            if active.package_id != voucher.package_id:
                raise VoucherConflictError(
                    "You already have an active subscription for a different package."
                )
            # Same package — extend.
            active.expires_at = active.expires_at + timedelta(days=voucher.duration_days)
            subscription = active
            extended = True
        else:
            subscription = UserSubscription(
                user_id=user_id,
                package_id=voucher.package_id,
                status=SubscriptionStatus.ACTIVE,
                starts_at=now,
                expires_at=now + timedelta(days=voucher.duration_days),
            )
            self.db.add(subscription)
            await self.db.flush()  # populate guid before redemption insert

            # Link user to the package's group (mirrors /subscribe behaviour).
            existing_link = await self.db.execute(
                select(UserGroupLink).where(
                    UserGroupLink.user_id == user_id,
                    UserGroupLink.group_id == voucher.package.group_id,
                )
            )
            if existing_link.scalar_one_or_none() is None:
                self.db.add(
                    UserGroupLink(
                        user_id=user_id,
                        group_id=voucher.package.group_id,
                    )
                )

        # Write audit (the use was already claimed atomically above).
        self.db.add(
            VoucherRedemption(
                voucher_id=voucher.guid,
                user_id=user_id,
                subscription_id=subscription.guid,
            )
        )

        await self.db.commit()
        await self.db.refresh(subscription)
        logger.info(
            "Voucher redeemed code=%s user_id=%s subscription_id=%s extended=%s",
            voucher.code,
            user_id,
            subscription.guid,
            extended,
        )
        return subscription, extended
