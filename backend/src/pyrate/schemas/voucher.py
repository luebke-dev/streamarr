from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from pyrate.schemas.base import BaseSchema


class VoucherBase(BaseModel):
    package_id: UUID = Field(..., description="Package this voucher grants when redeemed")
    duration_days: int = Field(..., gt=0, le=3650, description="Membership duration in days")
    max_uses: int = Field(1, ge=1, le=100000, description="Maximum number of redemptions")
    expires_at: datetime | None = Field(
        None, description="Date the code itself expires (independent of granted membership)"
    )
    note: str | None = Field(None, max_length=255)
    is_active: bool = Field(True)


class VoucherCreate(VoucherBase):
    """Create a single voucher with an optional custom code."""

    code: str | None = Field(
        None,
        min_length=4,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Optional custom code; auto-generated if omitted",
    )


class VoucherBatchCreate(VoucherBase):
    """Create N vouchers at once (codes are auto-generated)."""

    count: int = Field(..., ge=1, le=1000, description="Number of vouchers to generate")
    prefix: str | None = Field(
        None,
        max_length=16,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Optional prefix prepended to each generated code",
    )


class VoucherUpdate(BaseModel):
    """Update mutable voucher fields. Code/package/duration are immutable."""

    is_active: bool | None = None
    max_uses: int | None = Field(None, ge=1, le=100000)
    expires_at: datetime | None = None
    note: str | None = Field(None, max_length=255)


class VoucherResponse(BaseSchema):
    guid: UUID
    code: str
    package_id: UUID
    package_name: str | None = None
    duration_days: int
    max_uses: int
    current_uses: int
    expires_at: datetime | None = None
    is_active: bool
    note: str | None = None
    created_by_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

class VoucherRedeemRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=64)


class VoucherRedeemResponse(BaseModel):
    """Response after successful redemption."""

    subscription_id: UUID
    package_id: UUID
    package_name: str
    expires_at: datetime
    extended: bool = Field(
        ..., description="True if an existing subscription was extended, False if newly created"
    )
