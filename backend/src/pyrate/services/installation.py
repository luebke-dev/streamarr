"""Installation service for initial system setup."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.auth.jwt_handler import jwt_handler
from pyrate.auth.password import validate_password_strength
from pyrate.models.user import User
from pyrate.services.settings import SettingsService

logger = logging.getLogger(__name__)


class InstallationService:
    """Service for performing initial system setup."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def perform_initial_setup(
        self,
        *,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        site_name: str | None = "pyrate.media",
        locale: str | None = "de-DE",
    ) -> User:
        """Create the first admin user and configure basic system settings.

        This method:
        1. Creates the first admin user with hashed password
        2. Configures system settings (site name, locale)
        3. Marks the system as installed

        Args:
            email: Admin user email
            password: Admin user password (plaintext, will be hashed)
            first_name: Admin user first name
            last_name: Admin user last name
            site_name: Site name setting
            locale: System locale setting

        Returns:
            The created admin User object

        Raises:
            Exception: If setup fails (caller should handle rollback)
        """
        logger.info("Starting initial setup for admin email=%s locale=%s", email, locale)

        # Defense-in-depth: enforce password policy at the service layer so
        # direct callers (scripts, admin tooling) can't bypass the API schema.
        validate_password_strength(password)

        # Create the first admin user
        hashed_password = jwt_handler.get_password_hash(password)

        admin_user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            hashed_password=hashed_password,
            is_active=True,
            is_superuser=True,  # First user is always admin
            email_verified=True,  # Admin created during install is auto-verified
            ui_language=locale,
        )

        self.db.add(admin_user)
        await self.db.flush()
        logger.info("Created admin user email=%s id=%s", email, admin_user.guid)

        # Configure system settings
        settings_service = SettingsService(self.db)

        if site_name:
            await settings_service.set("system.site_name", site_name)
            logger.debug("Set system.site_name=%s", site_name)

        if locale:
            await settings_service.set("system.locale", locale)
            logger.debug("Set system.locale=%s", locale)

        # Mark system as installed
        await settings_service.set("system.installed", True)
        logger.debug("Marked system as installed")
        await settings_service.set("system.installed_at", str(admin_user.created_at))

        await self.db.commit()

        logger.info("Initial setup completed. Admin user created: %s", email)

        return admin_user
