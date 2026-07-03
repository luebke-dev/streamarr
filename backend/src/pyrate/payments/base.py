"""Base class for payment providers."""

from abc import ABC, abstractmethod
from typing import Any


class PaymentProviderPlugin(ABC):
    """
    Abstract base class for payment provider plugins.

    Payment provider plugins handle subscription payments and
    billing through services like Stripe, PayPal, etc.
    """

    @abstractmethod
    async def create_checkout_session(
        self, user_id: str, plan_id: str, **kwargs
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def cancel_subscription(self, subscription_id: str, **kwargs) -> bool:
        pass

    @abstractmethod
    async def get_subscription_status(self, subscription_id: str) -> dict[str, Any]:
        pass

    @abstractmethod
    async def handle_webhook(
        self, event_type: str, payload: dict[str, Any], **kwargs
    ) -> bool:
        pass
