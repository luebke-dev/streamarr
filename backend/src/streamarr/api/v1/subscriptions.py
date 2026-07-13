import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ...auth.dependencies import get_current_superuser, get_current_user
from ...config import settings
from ...database import get_db_session
from ...models.user import User
from ...schemas.subscription import (
    PaymentHistoryResponse,
    StripeConfigResponse,
    StripeInvoiceResponse,
    StripePaymentMethodResponse,
    StripeSetupIntentResponse,
    SubscriptionPackageCreate,
    SubscriptionPackageResponse,
    SubscriptionPackageUpdate,
    SubscriptionStatsResponse,
    SubscriptionValidationResponse,
    UserSessionCreate,
    UserSessionResponse,
    UserSubscriptionCreate,
    UserSubscriptionResponse,
    UserSubscriptionWithUsage,
)
from ...services.subscription import SubscriptionService
from ..dependencies import PaymentServiceDep

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


# Admin routes for managing subscription packages
@router.post(
    "/packages",
    response_model=SubscriptionPackageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
)
async def create_subscription_package(
    package_data: SubscriptionPackageCreate,
    payment_service: PaymentServiceDep,
    db: AsyncSession = Depends(get_db_session),
) -> SubscriptionPackageResponse:
    """Create a new subscription package (Admin only).

    If a payment service (e.g. Stripe) is configured, the package is also
    synced to it (product + price). Otherwise the package is created locally
    only and can be synced later by editing it once payments are configured.
    """
    service = SubscriptionService(db)

    # SubscriptionPackage.currency defaults to EUR; create the Stripe price in
    # the same currency (Stripe defaults to usd otherwise) so the customer is
    # billed exactly what the package/UI advertises.
    currency = "EUR"

    try:
        stripe_product_id: str | None = None
        stripe_price_id: str | None = None

        if payment_service is not None:
            try:
                stripe_product, stripe_price = await payment_service.create_product_and_price(
                    name=package_data.name,
                    description=package_data.description,
                    price=package_data.price,
                    currency=currency.lower(),
                )
                stripe_product_id = stripe_product.id
                stripe_price_id = stripe_price.id
            except Exception as e:
                logger.warning(
                    "Payment service sync failed during package create, "
                    "creating package without provider link: %s",
                    e,
                )

        # Create package in database (permissions live on the linked Group)
        package = await service.create_package(
            name=package_data.name,
            description=package_data.description,
            price_cents=int(package_data.price * 100),
            group_id=package_data.group_id,
            currency=currency,
            stripe_product_id=stripe_product_id,
            stripe_price_id=stripe_price_id,
        )

        return SubscriptionPackageResponse.model_validate(package)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create subscription package: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create subscription package",
        )


@router.get(
    "/packages",
    response_model=list[SubscriptionPackageResponse],
)
async def get_subscription_packages(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db_session),
) -> list[SubscriptionPackageResponse]:
    """Get all subscription packages"""
    service = SubscriptionService(db)
    packages = await service.get_packages(active_only=active_only)
    return [SubscriptionPackageResponse.model_validate(package) for package in packages]


@router.get(
    "/packages/{package_id}",
    response_model=SubscriptionPackageResponse,
)
async def get_subscription_package(
    package_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> SubscriptionPackageResponse:
    """Get a specific subscription package"""
    service = SubscriptionService(db)
    package = await service.get_package(package_id)

    if not package:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription package not found",
        )

    return SubscriptionPackageResponse.model_validate(package)


@router.put(
    "/packages/{package_id}",
    response_model=SubscriptionPackageResponse,
    dependencies=[Depends(get_current_superuser)],
)
async def update_subscription_package(
    package_id: UUID,
    package_data: SubscriptionPackageUpdate,
    db: AsyncSession = Depends(get_db_session),
) -> SubscriptionPackageResponse:
    """Update a subscription package (Admin only)"""
    service = SubscriptionService(db)

    # Check if package exists
    existing_package = await service.get_package(package_id)
    if not existing_package:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription package not found",
        )

    try:
        # Update package
        updated_package = await service.update_package(
            package_id, **package_data.model_dump(exclude_unset=True)
        )
        return SubscriptionPackageResponse.model_validate(updated_package)

    except Exception as e:
        logger.error("Failed to update subscription package: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to update subscription package",
        )


@router.delete(
    "/packages/{package_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_superuser)],
)
async def deactivate_subscription_package(
    package_id: UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Deactivate a subscription package (Admin only)"""
    service = SubscriptionService(db)

    success = await service.deactivate_package(package_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription package not found",
        )


# User subscription routes
@router.post(
    "/subscribe",
    response_model=UserSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_subscription(
    subscription_data: UserSubscriptionCreate,
    payment_service: PaymentServiceDep,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserSubscriptionResponse:
    """Create a new subscription for the current user"""
    if payment_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service is not configured",
        )

    service = SubscriptionService(db)

    # Check if package exists and is active
    package = await service.get_package(subscription_data.package_id)
    if not package or not package.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription package not found or inactive",
        )

    # Check if user already has an active subscription
    existing_subscription = await service.get_user_active_subscription(current_user.guid)
    if existing_subscription:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has an active subscription",
        )

    try:
        # Create subscription via payment provider
        stripe_subscription = await payment_service.create_subscription(
            user_email=current_user.email,
            price_id=package.stripe_price_id,
            payment_method_id=subscription_data.payment_method_id,
        )

        # Create subscription in database (PENDING until payment confirmed)
        subscription = await service.create_subscription(
            user_id=current_user.guid,
            package_id=subscription_data.package_id,
            stripe_subscription_id=stripe_subscription.id,
            stripe_customer_id=stripe_subscription.customer,
        )

        return UserSubscriptionResponse.model_validate(subscription)

    except Exception as e:
        logger.error("Failed to create subscription: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create subscription",
        )


@router.get(
    "/my-subscription",
    response_model=UserSubscriptionWithUsage | None,
)
async def get_my_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserSubscriptionWithUsage | None:
    """Get current user's active subscription with usage information"""
    service = SubscriptionService(db)

    subscription = await service.get_user_active_subscription(current_user.guid)
    if not subscription:
        return None

    # Get active session count
    active_sessions = await service.get_active_session_count(current_user.guid)
    can_start_session = active_sessions < subscription.package.group.max_concurrent_streams

    # Convert to response model with usage info
    subscription_dict = subscription.__dict__.copy()
    subscription_dict["active_sessions"] = active_sessions
    subscription_dict["can_start_session"] = can_start_session

    return UserSubscriptionWithUsage(**subscription_dict)


@router.get(
    "/my-subscriptions",
    response_model=list[UserSubscriptionResponse],
)
async def get_my_subscriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[UserSubscriptionResponse]:
    """Get all subscriptions for the current user"""
    service = SubscriptionService(db)
    subscriptions = await service.get_user_subscriptions(current_user.guid)
    return [UserSubscriptionResponse.model_validate(sub) for sub in subscriptions]


@router.post(
    "/cancel",
    response_model=UserSubscriptionResponse,
)
async def cancel_my_subscription(
    payment_service: PaymentServiceDep,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserSubscriptionResponse:
    """Cancel current user's active subscription"""
    if payment_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service is not configured",
        )

    service = SubscriptionService(db)

    subscription = await service.get_user_active_subscription(current_user.guid)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active subscription found"
        )

    try:
        await payment_service.cancel_subscription(subscription.stripe_subscription_id)

        updated_subscription = await service.cancel_subscription(subscription.guid)
        if updated_subscription is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active subscription found",
            )

        return UserSubscriptionResponse.model_validate(updated_subscription)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to cancel subscription: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to cancel subscription",
        )


# Session management routes
@router.post(
    "/sessions",
    response_model=UserSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_session(
    session_data: UserSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserSessionResponse:
    """Start a new user session"""
    service = SubscriptionService(db)

    # Check if user has active subscription
    subscription = await service.get_user_active_subscription(current_user.guid)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No active subscription found"
        )

    # Check session limit
    active_sessions = await service.get_active_session_count(current_user.guid)
    if active_sessions >= subscription.package.group.max_concurrent_streams:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Maximum concurrent sessions reached",
        )

    # Create new session
    session = await service.create_session(
        user_id=current_user.guid,
        subscription_id=subscription.guid,
        device_info=session_data.device_info,
        ip_address=session_data.ip_address,
    )

    return UserSessionResponse.model_validate(session)


@router.get(
    "/sessions",
    response_model=list[UserSessionResponse],
)
async def get_my_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[UserSessionResponse]:
    """Get current user's active sessions"""
    service = SubscriptionService(db)
    sessions = await service.get_active_sessions(current_user.guid)
    return [UserSessionResponse.model_validate(session) for session in sessions]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def end_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """End a specific session"""
    service = SubscriptionService(db)

    # Scope to the caller so a user can only end their own session (IDOR guard).
    success = await service.end_session(session_id, user_id=current_user.guid)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )


@router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def end_all_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """End all active sessions for the current user"""
    service = SubscriptionService(db)
    await service.end_all_user_sessions(current_user.guid)


# Payment history routes
@router.get(
    "/payments",
    response_model=list[PaymentHistoryResponse],
)
async def get_my_payments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[PaymentHistoryResponse]:
    """Get current user's payment history"""
    service = SubscriptionService(db)
    payments = await service.get_user_payments(current_user.guid)
    return [PaymentHistoryResponse.model_validate(payment) for payment in payments]


@router.get(
    "/payments/subscription/{subscription_id}",
    response_model=list[PaymentHistoryResponse],
)
async def get_subscription_payments(
    subscription_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[PaymentHistoryResponse]:
    """Get payments for a specific subscription"""
    service = SubscriptionService(db)

    # Verify subscription belongs to current user
    subscription = await service.get_user_subscription(subscription_id)
    if not subscription or subscription.user_id != current_user.guid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found"
        )

    payments = await service.get_subscription_payments(subscription_id)
    return [PaymentHistoryResponse.model_validate(payment) for payment in payments]


# Subscription validation routes
@router.get(
    "/validate",
    response_model=SubscriptionValidationResponse,
)
async def validate_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SubscriptionValidationResponse:
    """Validate current user's subscription status"""
    service = SubscriptionService(db)

    subscription = await service.get_user_active_subscription(current_user.guid)

    if not subscription:
        return SubscriptionValidationResponse(
            is_valid=False,
            subscription_id=None,
            package_name=None,
            expires_at=None,
            allowed_libraries=[],
            max_quality_movies=None,
            max_quality_series=None,
            max_quality_music=None,
            max_concurrent_sessions=0,
            active_sessions=0,
            can_start_session=False,
        )

    active_sessions = await service.get_active_session_count(current_user.guid)
    group = subscription.package.group

    return SubscriptionValidationResponse(
        is_valid=True,
        subscription_id=subscription.guid,
        package_name=subscription.package.name,
        expires_at=subscription.expires_at,
        allowed_libraries=group.allowed_libraries,
        max_quality_movies=group.max_video_quality,
        max_quality_series=group.max_video_quality,
        max_quality_music=group.max_audio_quality,
        max_concurrent_sessions=group.max_concurrent_streams,
        active_sessions=active_sessions,
        can_start_session=active_sessions < group.max_concurrent_streams,
    )


# Admin statistics routes
@router.get(
    "/stats",
    response_model=SubscriptionStatsResponse,
    dependencies=[Depends(get_current_superuser)],
)
async def get_subscription_stats(
    db: AsyncSession = Depends(get_db_session),
) -> SubscriptionStatsResponse:
    """Get subscription statistics (Admin only)"""
    service = SubscriptionService(db)
    stats = await service.get_stats()
    return SubscriptionStatsResponse(**stats)


# Payment provider webhook routes
@router.post(
    "/webhooks/stripe",
    status_code=status.HTTP_200_OK,
)
async def handle_stripe_webhook(
    request: Request,
    payment_service: PaymentServiceDep,
    db: AsyncSession = Depends(get_db_session),
):
    """Handle Stripe webhook events"""
    if payment_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service is not configured",
        )
    if not settings.payment.stripe_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret is not configured",
        )

    payload = await request.body()
    signature = request.headers.get("Stripe-Signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header",
        )

    try:
        event = await payment_service.provider.verify_webhook_signature(
            payload, signature
        )
    except ValueError as e:
        logger.warning("Stripe webhook verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook signature verification failed",
        )

    event_type = event.get("type")
    event_data = event.get("data", {}).get("object", {})
    event_id = event.get("id")

    try:
        if event_type == "invoice.payment_succeeded":
            await payment_service.handle_payment_succeeded(event_data)
        elif event_type == "invoice.payment_failed":
            await payment_service.handle_payment_failed(event_data)
        elif event_type == "customer.subscription.updated":
            await payment_service.handle_subscription_updated(event_data)
        elif event_type == "customer.subscription.deleted":
            await payment_service.handle_subscription_deleted(event_data)

    except Exception as e:
        # Do NOT record the idempotency marker: returning 400 makes Stripe retry
        # the event, and the retry must be allowed to re-run the handler.
        logger.error("Webhook processing failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook processing failed",
        )

    # Handler committed successfully — only now mark the event processed so a
    # Stripe retry of this same event id is treated as a duplicate.
    await payment_service.provider.mark_event_processed(event_id)

    return {"status": "success"}


# Utility routes
@router.post(
    "/extend/{subscription_id}",
    response_model=UserSubscriptionResponse,
    dependencies=[Depends(get_current_superuser)],
)
async def extend_subscription(
    subscription_id: UUID,
    days: int,
    db: AsyncSession = Depends(get_db_session),
) -> UserSubscriptionResponse:
    """Extend a subscription by specified days (Admin only)"""
    service = SubscriptionService(db)

    try:
        subscription = await service.extend_subscription(subscription_id, days)
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found"
            )

        return UserSubscriptionResponse.model_validate(subscription)

    except Exception as e:
        logger.error("Failed to extend subscription: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to extend subscription",
        )


# ----------------------------------------------------------------------
# Stripe.js / Elements support
# ----------------------------------------------------------------------


@router.get(
    "/stripe-config",
    response_model=StripeConfigResponse,
)
async def get_stripe_config() -> StripeConfigResponse:
    """
    Public endpoint returning the Stripe publishable key the frontend
    needs to boot Stripe.js. Returns ``publishable_key=null`` when payments
    are disabled or not configured, so the frontend can hide payment UI.
    """
    if not settings.payment.enabled:
        return StripeConfigResponse(publishable_key=None)
    return StripeConfigResponse(
        publishable_key=settings.payment.stripe_publishable_key,
    )


@router.post(
    "/setup-intent",
    response_model=StripeSetupIntentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_setup_intent(
    payment_service: PaymentServiceDep,
    current_user: User = Depends(get_current_user),
) -> StripeSetupIntentResponse:
    """
    Create a SetupIntent so the browser can attach a card via Stripe
    Elements without an immediate charge. The Stripe customer is created
    on demand (and reused across calls) using the user's email.
    """
    if payment_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service is not configured",
        )

    try:
        customer_id = await payment_service.get_or_create_customer(
            email=current_user.email,
            name=current_user.preferred_username,
            metadata={"user_id": str(current_user.guid)},
        )
        intent = await payment_service.create_setup_intent(
            customer_id=customer_id,
            metadata={"user_id": str(current_user.guid)},
        )
    except Exception as e:
        logger.error("Failed to create setup intent: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create setup intent",
        )

    return StripeSetupIntentResponse(
        client_secret=intent["client_secret"],
        customer_id=customer_id,
    )


@router.get(
    "/payment-methods",
    response_model=list[StripePaymentMethodResponse],
)
async def list_payment_methods(
    payment_service: PaymentServiceDep,
    current_user: User = Depends(get_current_user),
) -> list[StripePaymentMethodResponse]:
    """List the current user's saved Stripe payment methods (cards)."""
    if payment_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service is not configured",
        )

    try:
        customer_id = await payment_service.get_or_create_customer(
            email=current_user.email,
            name=current_user.preferred_username,
            metadata={"user_id": str(current_user.guid)},
        )
        methods = await payment_service.list_payment_methods(customer_id)
    except Exception as e:
        logger.error("Failed to list payment methods: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to list payment methods",
        )

    # We don't currently track ``default`` separately — the Stripe Customer's
    # ``invoice_settings.default_payment_method`` would need an extra retrieve.
    # The frontend can treat the first method as default for now; a follow-up
    # can expose the real flag.
    return [StripePaymentMethodResponse(**m) for m in methods]


@router.delete(
    "/payment-methods/{payment_method_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_payment_method(
    payment_method_id: str,
    payment_service: PaymentServiceDep,
    current_user: User = Depends(get_current_user),
) -> None:
    """Detach a payment method from the current user's Stripe customer."""
    if payment_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service is not configured",
        )

    try:
        # Authorisation: make sure the payment method belongs to *this* user
        # by checking it appears in their customer's list.
        customer_id = await payment_service.get_or_create_customer(
            email=current_user.email,
            name=current_user.preferred_username,
            metadata={"user_id": str(current_user.guid)},
        )
        owned = await payment_service.list_payment_methods(customer_id)
        if not any(m["id"] == payment_method_id for m in owned):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment method not found",
            )
        await payment_service.detach_payment_method(payment_method_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to detach payment method %s: %s", payment_method_id, e
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to detach payment method",
        )


@router.post(
    "/payment-methods/{payment_method_id}/default",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def set_default_payment_method(
    payment_method_id: str,
    payment_service: PaymentServiceDep,
    current_user: User = Depends(get_current_user),
) -> None:
    """Mark ``payment_method_id`` as the default for future invoices."""
    if payment_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service is not configured",
        )

    try:
        customer_id = await payment_service.get_or_create_customer(
            email=current_user.email,
            name=current_user.preferred_username,
            metadata={"user_id": str(current_user.guid)},
        )
        owned = await payment_service.list_payment_methods(customer_id)
        if not any(m["id"] == payment_method_id for m in owned):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment method not found",
            )
        await payment_service.set_default_payment_method(
            customer_id=customer_id,
            payment_method_id=payment_method_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to set default payment method %s: %s", payment_method_id, e
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to set default payment method",
        )


@router.get(
    "/invoices",
    response_model=list[StripeInvoiceResponse],
)
async def list_my_invoices(
    payment_service: PaymentServiceDep,
    current_user: User = Depends(get_current_user),
    limit: int = 20,
) -> list[StripeInvoiceResponse]:
    """Return the user's Stripe invoices for the billing-history view."""
    if payment_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment service is not configured",
        )

    try:
        customer_id = await payment_service.get_or_create_customer(
            email=current_user.email,
            name=current_user.preferred_username,
            metadata={"user_id": str(current_user.guid)},
        )
        invoices = await payment_service.list_invoices(customer_id, limit=limit)
    except Exception as e:
        logger.error("Failed to list invoices: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to list invoices",
        )

    return [StripeInvoiceResponse(**inv) for inv in invoices]

