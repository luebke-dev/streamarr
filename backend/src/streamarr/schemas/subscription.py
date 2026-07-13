from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from streamarr.schemas.base import BaseSchema

from ..models.subscription import QualityLevel


# Base schemas for SubscriptionPackage
class SubscriptionPackageBase(BaseModel):
    """Common fields for creating / updating a subscription package.

    Permissions (allowed libraries, quality caps, concurrency limits, ...)
    live exclusively on the linked Group, identified by ``group_id``. The
    package itself only carries pricing, naming and the Stripe linkage.
    """

    name: str = Field(..., min_length=1, max_length=100, description="Package name")
    description: str | None = Field(
        None, max_length=500, description="Package description"
    )
    price: Decimal = Field(..., gt=0, description="Monthly price in main currency unit")
    group_id: UUID = Field(..., description="Group whose permissions this package grants")
    is_active: bool = Field(True, description="Whether the package is active")


class SubscriptionPackageCreate(SubscriptionPackageBase):
    """Schema for creating a new subscription package"""

    pass


class SubscriptionPackageUpdate(BaseModel):
    """Schema for updating a subscription package"""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    price: Decimal | None = Field(None, gt=0)
    group_id: UUID | None = Field(None, description="Group whose permissions this package grants")
    is_active: bool | None = None


class SubscriptionPackageResponse(BaseSchema):
    """Schema for subscription package responses.

    The response embeds the linked group identifier so the frontend can fetch
    its permissions from the group endpoints when it needs to render
    feature lists.
    """

    guid: UUID
    name: str
    description: str | None = None
    price_cents: int
    currency: str = "EUR"
    group_id: UUID
    is_active: bool
    stripe_product_id: str | None = None
    stripe_price_id: str | None = None
    created_at: datetime
    updated_at: datetime

# Base schemas for UserSubscription
class UserSubscriptionBase(BaseModel):
    package_id: UUID = Field(..., description="ID of the subscription package")


class UserSubscriptionCreate(UserSubscriptionBase):
    """Schema for creating a new user subscription"""

    payment_method_id: str | None = Field(None, description="Stripe payment method ID")


class UserSubscriptionResponse(BaseSchema):
    """Schema for user subscription responses"""

    guid: UUID
    user_id: UUID
    package_id: UUID
    stripe_subscription_id: str | None = None
    stripe_customer_id: str | None = None
    status: str
    starts_at: datetime
    expires_at: datetime
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

class UserSubscriptionWithUsage(UserSubscriptionResponse):
    """Extended subscription response with usage information"""

    active_sessions: int = Field(..., description="Current number of active sessions")
    can_start_session: bool = Field(
        ..., description="Whether user can start a new session"
    )


# Schemas for PaymentHistory
class PaymentHistoryResponse(BaseSchema):
    """Schema for payment history responses"""

    guid: UUID
    user_id: UUID
    subscription_id: UUID
    stripe_payment_intent_id: str | None = None
    stripe_invoice_id: str | None = None
    amount_cents: int
    currency: str
    status: str
    failure_reason: str | None = None
    created_at: datetime

# Schemas for UserSession
class UserSessionResponse(BaseSchema):
    """Schema for user session responses"""

    guid: UUID
    user_id: UUID
    device_info: str | None = None
    ip_address: str | None = None
    last_activity: datetime
    is_active: bool

class UserSessionCreate(BaseModel):
    """Schema for creating a new user session"""

    device_info: str | None = Field(None, max_length=200)
    ip_address: str | None = Field(None, max_length=45)
    user_agent: str | None = Field(None, max_length=500)


# Subscription validation schemas
class SubscriptionValidationResponse(BaseModel):
    """Schema for subscription validation responses.

    Permission fields are sourced from the package's linked Group; for
    quality caps Movies and Series share the group's ``max_video_quality``
    (the package model no longer distinguishes between them) and
    ``max_quality_music`` mirrors ``max_audio_quality``.
    """

    is_valid: bool
    subscription_id: UUID | None = None
    package_name: str | None = None
    expires_at: datetime | None = None
    allowed_libraries: list[str] = []
    max_quality_movies: QualityLevel | None = None
    max_quality_series: QualityLevel | None = None
    max_quality_music: QualityLevel | None = None
    max_concurrent_sessions: int = 0
    active_sessions: int = 0
    can_start_session: bool = False


# Stripe webhook schemas
class StripeWebhookEvent(BaseModel):
    """Schema for Stripe webhook events"""

    id: str
    type: str
    data: dict
    created: int


# Subscription statistics schemas
class SubscriptionStatsResponse(BaseModel):
    """Schema for subscription statistics"""

    total_packages: int
    active_subscriptions: int
    total_subscriptions: int
    total_revenue: Decimal
    monthly_revenue: Decimal


# ----------------------------------------------------------------------
# Stripe.js / Elements
# ----------------------------------------------------------------------


class StripeConfigResponse(BaseModel):
    """Public Stripe configuration the frontend needs to boot Stripe.js."""

    publishable_key: str | None = Field(
        None,
        description="Stripe publishable API key. ``null`` when payments are not configured.",
    )


class StripeSetupIntentResponse(BaseModel):
    """A SetupIntent the frontend uses with ``stripe.confirmSetup``."""

    client_secret: str = Field(..., description="SetupIntent client secret")
    customer_id: str = Field(..., description="Stripe customer the intent is bound to")


class StripeCardDetails(BaseModel):
    """Card metadata exposed to the UI."""

    brand: str | None = None
    last4: str | None = None
    exp_month: int | None = None
    exp_year: int | None = None


class StripePaymentMethodResponse(BaseModel):
    """Saved Stripe payment method."""

    id: str
    type: str
    card: StripeCardDetails | None = None
    is_default: bool = False


class StripeInvoiceResponse(BaseModel):
    """A historical Stripe invoice (billing history)."""

    id: str
    amount_paid: Decimal
    amount_due: Decimal
    currency: str
    status: str | None = None
    created: int
    invoice_pdf: str | None = None
