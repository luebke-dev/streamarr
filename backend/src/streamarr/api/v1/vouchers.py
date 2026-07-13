"""Voucher API: admin CRUD + user redemption."""

import csv
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import get_current_superuser, get_current_user
from ...database import get_db_session
from ...models.user import User
from ...schemas.voucher import (
    VoucherBatchCreate,
    VoucherCreate,
    VoucherRedeemRequest,
    VoucherRedeemResponse,
    VoucherResponse,
    VoucherUpdate,
)
from ...services.voucher import (
    VoucherCodeExpiredError,
    VoucherConflictError,
    VoucherError,
    VoucherExhaustedError,
    VoucherInactiveError,
    VoucherNotFoundError,
    VoucherService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


def _to_response(voucher) -> VoucherResponse:
    payload = VoucherResponse.model_validate(voucher)
    if voucher.package is not None:
        payload.package_name = voucher.package.name
    return payload


# ==================== Admin ====================


@router.post(
    "",
    response_model=VoucherResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_voucher(
    data: VoucherCreate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db_session),
) -> VoucherResponse:
    """Create a single voucher (admin only)."""
    service = VoucherService(db)
    try:
        voucher = await service.create_voucher(
            package_id=data.package_id,
            duration_days=data.duration_days,
            max_uses=data.max_uses,
            expires_at=data.expires_at,
            note=data.note,
            is_active=data.is_active,
            code=data.code,
            created_by_id=current_user.guid,
        )
    except VoucherError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    voucher = await service.get_voucher(voucher.guid)  # eager-load package
    return _to_response(voucher)


@router.post(
    "/batch",
    response_model=list[VoucherResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_voucher_batch(
    data: VoucherBatchCreate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db_session),
) -> list[VoucherResponse]:
    """Generate multiple vouchers at once (admin only)."""
    service = VoucherService(db)
    try:
        vouchers = await service.create_batch(
            count=data.count,
            package_id=data.package_id,
            duration_days=data.duration_days,
            max_uses=data.max_uses,
            expires_at=data.expires_at,
            note=data.note,
            is_active=data.is_active,
            prefix=data.prefix,
            created_by_id=current_user.guid,
        )
    except VoucherError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    # Re-fetch with package eager-loaded for the response (single query
    # instead of N round-trips).
    enriched = await service.get_vouchers_by_ids([v.guid for v in vouchers])
    return [_to_response(v) for v in enriched]


@router.get("", response_model=list[VoucherResponse])
async def list_vouchers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    active_only: bool = Query(False),
    _: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db_session),
) -> list[VoucherResponse]:
    """List vouchers (admin only)."""
    service = VoucherService(db)
    vouchers = await service.list_vouchers(
        skip=skip, limit=limit, active_only=active_only
    )
    return [_to_response(v) for v in vouchers]


@router.get("/export.csv")
async def export_vouchers_csv(
    active_only: bool = Query(False),
    _: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Export all vouchers as CSV (admin only)."""
    service = VoucherService(db)
    vouchers = await service.list_vouchers(skip=0, limit=10000, active_only=active_only)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "code",
            "package",
            "duration_days",
            "max_uses",
            "current_uses",
            "expires_at",
            "is_active",
            "note",
            "created_at",
        ]
    )
    for v in vouchers:
        writer.writerow(
            [
                v.code,
                v.package.name if v.package else "",
                v.duration_days,
                v.max_uses,
                v.current_uses,
                v.expires_at.isoformat() if v.expires_at else "",
                "yes" if v.is_active else "no",
                v.note or "",
                v.created_at.isoformat(),
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vouchers.csv"},
    )


@router.patch("/{voucher_id}", response_model=VoucherResponse)
async def update_voucher(
    voucher_id,
    data: VoucherUpdate,
    _: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db_session),
) -> VoucherResponse:
    service = VoucherService(db)
    updates = data.model_dump(exclude_unset=True)
    voucher = await service.update_voucher(voucher_id, **updates)
    if voucher is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voucher not found")
    voucher = await service.get_voucher(voucher.guid)
    return _to_response(voucher)


@router.delete("/{voucher_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voucher(
    voucher_id,
    _: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    service = VoucherService(db)
    deleted = await service.delete_voucher(voucher_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voucher not found")


# ==================== User redemption ====================


@router.post(
    "/redeem",
    response_model=VoucherRedeemResponse,
    status_code=status.HTTP_200_OK,
)
async def redeem_voucher(
    data: VoucherRedeemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VoucherRedeemResponse:
    """Redeem a voucher code for the current user."""
    service = VoucherService(db)
    try:
        subscription, extended = await service.redeem(
            code=data.code, user_id=current_user.guid
        )
    except VoucherNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except VoucherConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        VoucherInactiveError,
        VoucherExhaustedError,
        VoucherCodeExpiredError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    # Fetch the package for name in the response.
    from ...models.subscription import SubscriptionPackage  # local import

    pkg = await db.get(SubscriptionPackage, subscription.package_id)
    return VoucherRedeemResponse(
        subscription_id=subscription.guid,
        package_id=subscription.package_id,
        package_name=pkg.name if pkg else "",
        expires_at=subscription.expires_at,
        extended=extended,
    )
