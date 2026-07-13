from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.auth.dependencies import (
    get_current_superuser,
    get_current_user,
    get_current_user_optional,
)
from streamarr.config import settings
from streamarr.database import get_db_session
from streamarr.models.user import User
from streamarr.payments.base import PaymentProviderPlugin
from streamarr.schemas.group import EffectivePermissions
from streamarr.services.payment import PaymentService
from streamarr.services.permission import PermissionService

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
CurrentSuperuser = Annotated[User, Depends(get_current_superuser)]


def get_payment_provider() -> PaymentProviderPlugin | None:
    """Get the configured payment provider plugin."""
    if not settings.payment.enabled:
        return None

    if settings.payment.provider == "stripe":
        from streamarr.payments.stripe import Stripe

        return Stripe(
            secret_key=settings.payment.stripe_secret_key,
            publishable_key=settings.payment.stripe_publishable_key,
            webhook_secret=settings.payment.stripe_webhook_secret,
        )

    return None


async def get_payment_service(
    db: DatabaseSession,
    provider: Annotated[PaymentProviderPlugin | None, Depends(get_payment_provider)],
) -> PaymentService | None:
    """Get the payment service with configured provider."""
    if provider is None:
        return None
    return PaymentService(db=db, payment_provider=provider)


PaymentServiceDep = Annotated[PaymentService | None, Depends(get_payment_service)]


async def get_user_permissions(
    user: CurrentUser, db: DatabaseSession
) -> EffectivePermissions:
    """Get effective permissions for the current user."""
    service = PermissionService(db)
    return await service.resolve_user_permissions(user.guid)


UserPermissionsDep = Annotated[EffectivePermissions, Depends(get_user_permissions)]
