"""
Stripe payment provider plugin for pyrate.

This plugin handles subscription payments and billing through Stripe.
"""

import functools
import logging
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import anyio
import stripe

from pyrate.payments.base import PaymentProviderPlugin

logger = logging.getLogger(__name__)

# Webhook events this plugin has already processed, keyed by event id with a
# TTL so Stripe can't deliver the same event twice and double-credit an account.
_WEBHOOK_IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60  # 24h, matches Stripe's retry window


async def _stripe_call(func, /, *args, **kwargs):
    """Run a blocking synchronous Stripe SDK call in a worker thread.

    The ``stripe`` SDK is synchronous and performs network round-trips; calling
    it directly from an async method blocks the whole asyncio event loop for the
    duration of the request. Offloading to a thread keeps the loop responsive.
    """
    return await anyio.to_thread.run_sync(functools.partial(func, *args, **kwargs))


def _validate_checkout_url(url: str | None, field: str) -> str | None:
    """Reject ``javascript:`` / data URLs and schemes other than http(s)."""
    if url is None:
        return None
    if not isinstance(url, str):
        raise ValueError(f"{field} must be a string")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"{field} must be an http(s) URL: {url!r}")
    if not parsed.netloc:
        raise ValueError(f"{field} must include a host: {url!r}")
    return url


class Stripe(PaymentProviderPlugin):
    """
    Stripe payment provider plugin.

    Handles subscription management, payment processing, and webhook
    handling through the Stripe API.
    """

    def __init__(
        self,
        secret_key: str,
        publishable_key: str | None = None,
        webhook_secret: str | None = None,
    ):
        """
        Initialize the Stripe plugin.

        Args:
            secret_key: Stripe secret API key
            publishable_key: Stripe publishable API key (for frontend)
            webhook_secret: Stripe webhook signing secret
        """
        self.secret_key = secret_key
        self.publishable_key = publishable_key
        self.webhook_secret = webhook_secret
        stripe.api_key = secret_key

    def get_name(self) -> str:
        """Get the plugin name."""
        return "Stripe"

    async def setup(self) -> None:
        """Initialize the plugin."""
        logger.info("Stripe plugin initialized")

    async def close(self) -> None:
        """Clean up plugin resources."""
        pass

    async def create_customer(
        self,
        email: str,
        name: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new Stripe customer.

        Args:
            email: Customer email
            name: Customer name
            metadata: Additional metadata

        Returns:
            dict: Customer information including ID
        """
        customer = await _stripe_call(
            stripe.Customer.create,
            email=email,
            name=name,
            metadata=metadata or {},
        )
        return {
            "id": customer.id,
            "email": customer.email,
            "name": customer.name,
        }

    async def create_product_and_price(
        self,
        name: str,
        description: str,
        price: float,
        currency: str = "usd",
        interval: str = "month",
        interval_count: int = 1,
        metadata: dict[str, str] | None = None,
    ) -> tuple[Any, Any]:
        """
        Create a Stripe product and price for a subscription.

        Args:
            name: Product name
            description: Product description
            price: Price in currency units (not cents)
            currency: Currency code
            interval: Billing interval (month, year)
            interval_count: Number of intervals between billings
            metadata: Additional metadata

        Returns:
            Tuple of (product, price) Stripe objects
        """
        product = await _stripe_call(
            stripe.Product.create,
            name=name,
            description=description,
            metadata=metadata or {},
        )

        stripe_price = await _stripe_call(
            stripe.Price.create,
            product=product.id,
            unit_amount=int(price * 100),  # Convert to cents
            currency=currency,
            recurring={
                "interval": interval,
                "interval_count": interval_count,
            },
        )

        logger.info("Created Stripe product %s and price %s", product.id, stripe_price.id)
        return product, stripe_price

    async def create_checkout_session(
        self,
        user_id: str,
        plan_id: str,
        price_id: str | None = None,
        success_url: str | None = None,
        cancel_url: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Create a checkout session for a subscription.

        Args:
            user_id: The user ID
            plan_id: The subscription plan ID
            price_id: Stripe price ID (optional if plan_id maps to price)
            success_url: URL to redirect on success
            cancel_url: URL to redirect on cancel
            **kwargs: Additional checkout parameters

        Returns:
            dict: Checkout session information including URL
        """
        session_params: dict[str, Any] = {
            "mode": "subscription",
            "metadata": {
                "user_id": user_id,
                "plan_id": plan_id,
            },
        }

        if price_id:
            session_params["line_items"] = [{"price": price_id, "quantity": 1}]

        if success_url:
            session_params["success_url"] = _validate_checkout_url(
                success_url, "success_url"
            )
        if cancel_url:
            session_params["cancel_url"] = _validate_checkout_url(
                cancel_url, "cancel_url"
            )

        session_params.update(kwargs)

        session = await _stripe_call(stripe.checkout.Session.create, **session_params)

        return {
            "id": session.id,
            "url": session.url,
            "status": session.status,
        }

    async def create_subscription(
        self,
        user_email: str,
        price_id: str,
        payment_method_id: str | None = None,
        customer_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Any:
        """
        Create a new subscription for a user.

        Args:
            user_email: User's email address
            price_id: Stripe price ID
            payment_method_id: Stripe payment method ID
            customer_id: Existing Stripe customer ID
            metadata: Additional metadata

        Returns:
            Stripe subscription object
        """
        # Get or create customer
        if not customer_id:
            customers = await _stripe_call(
                stripe.Customer.list, email=user_email, limit=1
            )
            if customers.data:
                customer_id = customers.data[0].id
            else:
                customer = await _stripe_call(
                    stripe.Customer.create, email=user_email
                )
                customer_id = customer.id

        # Attach payment method if provided
        if payment_method_id:
            await _stripe_call(
                stripe.PaymentMethod.attach,
                payment_method_id,
                customer=customer_id,
            )
            await _stripe_call(
                stripe.Customer.modify,
                customer_id,
                invoice_settings={"default_payment_method": payment_method_id},
            )

        # Create subscription
        subscription = await _stripe_call(
            stripe.Subscription.create,
            customer=customer_id,
            items=[{"price": price_id}],
            payment_behavior="default_incomplete",
            payment_settings={"save_default_payment_method": "on_subscription"},
            expand=["latest_invoice.payment_intent"],
            metadata=metadata or {},
        )

        logger.info("Created Stripe subscription %s", subscription.id)
        return subscription

    async def cancel_subscription(
        self,
        subscription_id: str,
        cancel_at_period_end: bool = True,
        **kwargs,
    ) -> bool:
        """
        Cancel a subscription.

        Args:
            subscription_id: The Stripe subscription ID to cancel
            cancel_at_period_end: Whether to cancel at period end
            **kwargs: Additional parameters

        Returns:
            bool: True if cancellation was successful
        """
        try:
            if cancel_at_period_end:
                await _stripe_call(
                    stripe.Subscription.modify,
                    subscription_id,
                    cancel_at_period_end=True,
                )
            else:
                await _stripe_call(stripe.Subscription.delete, subscription_id)

            logger.info("Cancelled Stripe subscription %s", subscription_id)
            return True

        except stripe.StripeError as e:
            logger.error("Failed to cancel subscription %s: %s", subscription_id, e)
            raise

    async def get_subscription_status(
        self,
        subscription_id: str,
    ) -> dict[str, Any]:
        """
        Get subscription status.

        Args:
            subscription_id: The Stripe subscription ID

        Returns:
            dict: Subscription status information
        """
        subscription = await _stripe_call(
            stripe.Subscription.retrieve, subscription_id
        )

        return {
            "id": subscription.id,
            "status": subscription.status,
            "current_period_start": subscription.current_period_start,
            "current_period_end": subscription.current_period_end,
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "canceled_at": subscription.canceled_at,
            "customer": subscription.customer,
        }

    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
    ) -> dict[str, Any]:
        """
        Verify a webhook signature and return the event.

        Args:
            payload: Raw request body
            signature: Stripe signature header

        Returns:
            dict: Verified webhook event

        Raises:
            ValueError: If signature verification fails
        """
        if not self.webhook_secret:
            raise ValueError("Webhook secret not configured")

        try:
            event = await _stripe_call(
                stripe.Webhook.construct_event,
                payload,
                signature,
                self.webhook_secret,
            )
        except stripe.SignatureVerificationError as e:
            logger.error("Webhook signature verification failed: %s", e)
            raise ValueError("Invalid signature")

        # Replay protection: Stripe retries failed deliveries with the same
        # event ``id``. We only *read* the processed-marker here and refuse
        # events that were already handled successfully; the marker is written
        # by :meth:`mark_event_processed` *after* the handler commits (see the
        # webhook router). Marking on receipt would permanently drop an event
        # whose handler later raised (DB hiccup, deploy restart), because the
        # Stripe retry would then be rejected as a duplicate before it is ever
        # applied.
        event_id = event.get("id") if isinstance(event, dict) else getattr(event, "id", None)
        if event_id:
            try:
                from pyrate.services.rate_limiter import _get_redis

                redis = await _get_redis()
                key = f"pyrate:stripe_event:{event_id}"
                if await redis.get(key):
                    logger.warning(
                        "Refusing replayed Stripe webhook event id=%s", event_id,
                    )
                    raise ValueError("Duplicate webhook event")
            except ValueError:
                raise
            except Exception as e:
                # Redis down → fail open on idempotency (accept the event) but
                # warn so ops notices. Signature is still verified above.
                logger.warning(
                    "Webhook idempotency check unavailable (%s); accepting event %s",
                    e, event_id,
                )

        return event

    async def mark_event_processed(self, event_id: str | None) -> None:
        """Record a webhook event id as successfully processed.

        Called by the webhook router only after the handler has committed its
        state change, so a transient handler failure leaves the event eligible
        for Stripe's retry. Best-effort: if Redis is unavailable we skip the
        marker (the DB-level idempotency guards still prevent double writes).
        """
        if not event_id:
            return
        try:
            from pyrate.services.rate_limiter import _get_redis

            redis = await _get_redis()
            key = f"pyrate:stripe_event:{event_id}"
            await redis.set(
                key, "1", nx=True, ex=_WEBHOOK_IDEMPOTENCY_TTL_SECONDS,
            )
        except Exception as e:
            logger.warning(
                "Failed to record Stripe webhook idempotency marker for %s: %s",
                event_id, e,
            )

    async def handle_webhook(
        self,
        event_type: str,
        payload: dict[str, Any],
        **kwargs,
    ) -> bool:
        """
        Handle webhook events from Stripe.

        Args:
            event_type: The type of webhook event
            payload: The webhook payload
            **kwargs: Additional parameters

        Returns:
            bool: True if webhook was processed successfully
        """
        handlers = {
            "invoice.payment_succeeded": self._handle_payment_succeeded,
            "invoice.payment_failed": self._handle_payment_failed,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
        }

        handler = handlers.get(event_type)
        if handler:
            return await handler(payload, **kwargs)

        logger.debug("Unhandled webhook event type: %s", event_type)
        return True

    async def _handle_payment_succeeded(
        self,
        invoice: dict[str, Any],
        **kwargs,
    ) -> bool:
        """Handle successful payment webhook."""
        logger.info("Payment succeeded for invoice %s", invoice.get('id'))
        # Return payment data for service layer to process
        return True

    async def _handle_payment_failed(
        self,
        invoice: dict[str, Any],
        **kwargs,
    ) -> bool:
        """Handle failed payment webhook."""
        logger.warning("Payment failed for invoice %s", invoice.get('id'))
        return True

    async def _handle_subscription_updated(
        self,
        subscription: dict[str, Any],
        **kwargs,
    ) -> bool:
        """Handle subscription updated webhook."""
        logger.info("Subscription updated: %s", subscription.get('id'))
        return True

    async def _handle_subscription_deleted(
        self,
        subscription: dict[str, Any],
        **kwargs,
    ) -> bool:
        """Handle subscription deleted webhook."""
        logger.info("Subscription deleted: %s", subscription.get('id'))
        return True

    async def get_customer(self, customer_id: str) -> dict[str, Any]:
        """
        Get a Stripe customer by ID.

        Args:
            customer_id: Stripe customer ID

        Returns:
            dict: Customer information
        """
        customer = await _stripe_call(stripe.Customer.retrieve, customer_id)
        return {
            "id": customer.id,
            "email": customer.email,
            "name": customer.name,
            "metadata": dict(customer.metadata) if customer.metadata else {},
        }

    async def update_customer(
        self,
        customer_id: str,
        email: str | None = None,
        name: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Update a Stripe customer.

        Args:
            customer_id: Stripe customer ID
            email: New email (optional)
            name: New name (optional)
            metadata: Additional metadata (optional)

        Returns:
            dict: Updated customer information
        """
        update_params: dict[str, Any] = {}
        if email:
            update_params["email"] = email
        if name:
            update_params["name"] = name
        if metadata:
            update_params["metadata"] = metadata

        customer = await _stripe_call(
            stripe.Customer.modify, customer_id, **update_params
        )
        return {
            "id": customer.id,
            "email": customer.email,
            "name": customer.name,
        }

    async def get_payment_methods(
        self,
        customer_id: str,
        type: str = "card",
    ) -> list[dict[str, Any]]:
        """
        Get payment methods for a customer.

        Args:
            customer_id: Stripe customer ID
            type: Payment method type (card, bank_account, etc.)

        Returns:
            list: Payment methods
        """
        payment_methods = await _stripe_call(
            stripe.PaymentMethod.list,
            customer=customer_id,
            type=type,
        )
        return [
            {
                "id": pm.id,
                "type": pm.type,
                "card": {
                    "brand": pm.card.brand,
                    "last4": pm.card.last4,
                    "exp_month": pm.card.exp_month,
                    "exp_year": pm.card.exp_year,
                }
                if pm.card
                else None,
            }
            for pm in payment_methods.data
        ]

    async def get_or_create_customer(
        self,
        email: str,
        name: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """
        Look up a Stripe customer by email, creating one if none exists.

        Args:
            email: Customer email
            name: Optional customer name (used only when creating)
            metadata: Optional metadata (used only when creating)

        Returns:
            str: Stripe customer ID
        """
        existing = await _stripe_call(stripe.Customer.list, email=email, limit=1)
        if existing.data:
            return existing.data[0].id
        customer = await _stripe_call(
            stripe.Customer.create,
            email=email,
            name=name,
            metadata=metadata or {},
        )
        return customer.id

    async def create_setup_intent(
        self,
        customer_id: str,
        usage: str = "off_session",
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a SetupIntent for collecting a payment method via Stripe Elements.

        The frontend uses ``client_secret`` with ``stripe.confirmSetup`` to
        attach a card to the customer without immediately charging it.

        Args:
            customer_id: Stripe customer ID the payment method will be attached to
            usage: ``off_session`` for future subscription charges, ``on_session``
                otherwise
            metadata: Optional metadata stored on the SetupIntent

        Returns:
            dict: ``{id, client_secret, status}``
        """
        intent = await _stripe_call(
            stripe.SetupIntent.create,
            customer=customer_id,
            usage=usage,
            payment_method_types=["card"],
            metadata=metadata or {},
        )
        return {
            "id": intent.id,
            "client_secret": intent.client_secret,
            "status": intent.status,
        }

    async def detach_payment_method(self, payment_method_id: str) -> bool:
        """
        Detach a payment method from its customer.

        Args:
            payment_method_id: Stripe PaymentMethod ID

        Returns:
            bool: True on success
        """
        try:
            await _stripe_call(stripe.PaymentMethod.detach, payment_method_id)
            logger.info("Detached Stripe payment method %s", payment_method_id)
            return True
        except stripe.StripeError as e:
            logger.error(
                "Failed to detach payment method %s: %s", payment_method_id, e
            )
            raise

    async def set_default_payment_method(
        self,
        customer_id: str,
        payment_method_id: str,
    ) -> bool:
        """
        Mark a payment method as the customer's default for invoices.

        Args:
            customer_id: Stripe customer ID
            payment_method_id: Stripe PaymentMethod ID (must already be attached)

        Returns:
            bool: True on success
        """
        await _stripe_call(
            stripe.Customer.modify,
            customer_id,
            invoice_settings={"default_payment_method": payment_method_id},
        )
        return True

    async def create_payment_intent(
        self,
        amount: int,
        currency: str = "usd",
        customer_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a payment intent for one-time payments.

        Args:
            amount: Amount in cents
            currency: Currency code
            customer_id: Stripe customer ID (optional)
            metadata: Additional metadata

        Returns:
            dict: Payment intent information
        """
        params: dict[str, Any] = {
            "amount": amount,
            "currency": currency,
            "metadata": metadata or {},
        }
        if customer_id:
            params["customer"] = customer_id

        intent = await _stripe_call(stripe.PaymentIntent.create, **params)
        return {
            "id": intent.id,
            "client_secret": intent.client_secret,
            "status": intent.status,
        }

    async def get_invoices(
        self,
        customer_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Get invoices for a customer.

        Args:
            customer_id: Stripe customer ID
            limit: Maximum number of invoices to return

        Returns:
            list: Invoice information
        """
        invoices = await _stripe_call(
            stripe.Invoice.list, customer=customer_id, limit=limit
        )
        # Decimal division avoids float rounding on amounts; the callers that
        # serialise this into JSON will get e.g. "19.99" not 19.989999....
        return [
            {
                "id": inv.id,
                "amount_paid": Decimal(inv.amount_paid) / Decimal(100),
                "amount_due": Decimal(inv.amount_due) / Decimal(100),
                "currency": inv.currency,
                "status": inv.status,
                "created": inv.created,
                "invoice_pdf": inv.invoice_pdf,
            }
            for inv in invoices.data
        ]
