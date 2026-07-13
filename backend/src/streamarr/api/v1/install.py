"""Installation API Endpoints

This module provides endpoints for initial system setup and installation.
These endpoints are only accessible when the system has not been installed yet
(i.e., no users exist in the database).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select

from streamarr.api.dependencies import DatabaseSession
from streamarr.auth.dependencies import get_current_user_optional
from streamarr.auth.jwt_handler import jwt_handler
from streamarr.models.library import Library
from streamarr.models.user import User
from streamarr.services.installation import InstallationService
from streamarr.services.settings import SettingsService

router = APIRouter()

logger = logging.getLogger(__name__)


class InstallationStatus(BaseModel):
    """Response model for installation status check."""

    installed: bool
    has_users: bool
    site_name: str | None = None


class InstallWizardStep(BaseModel):
    id: str
    label: str
    complete: bool
    required: bool = True
    details: dict = Field(default_factory=dict)


class InstallWizardStatus(BaseModel):
    installed: bool
    current_step: str | None = None
    steps: list[InstallWizardStep]


class InstallWizardConfiguration(BaseModel):
    server_name: str | None = None
    ui_culture: str | None = None
    metadata_country_code: str | None = None
    preferred_metadata_language: str | None = None


class InstallWizardRemoteAccess(BaseModel):
    enable_remote_access: bool


class InstallWizardUser(BaseModel):
    name: str | None = None
    password: str | None = None


class InitialSetupRequest(BaseModel):
    """Request model for initial system setup."""

    # Admin user details
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)

    # Optional site configuration
    site_name: str | None = Field(default="Streamarr", max_length=100)
    locale: str | None = Field(default="de-DE")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password complexity."""
        import re

        if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)", v):
            raise ValueError(
                "Password must contain at least one lowercase letter, "
                "one uppercase letter, and one digit"
            )
        return v


class InitialSetupResponse(BaseModel):
    """Response model for successful initial setup."""

    success: bool
    message: str
    user_email: str
    site_name: str


async def _count_users(db: DatabaseSession) -> int:
    result = await db.execute(select(func.count()).select_from(User))
    return result.scalar() or 0


async def _require_install_wizard_access(
    db: DatabaseSession,
    current_user: User | None,
) -> None:
    user_count = await _count_users(db)
    if user_count == 0:
        return
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )


async def _get_first_user(db: DatabaseSession) -> User | None:
    result = await db.execute(select(User).order_by(User.created_at.asc()))
    return result.scalars().first()


@router.get("/status", response_model=InstallationStatus)
async def get_installation_status(db: DatabaseSession):
    """
    Check if the system has been installed.

    Returns the installation status, including whether any users exist.
    This endpoint is publicly accessible.
    """
    # Count users in the database
    user_count = await _count_users(db)

    has_users = user_count > 0

    # Get site name if configured
    site_name = None
    if has_users:
        settings_service = SettingsService(db)
        site_name = await settings_service.get("system.site_name", "Streamarr")

    return InstallationStatus(
        installed=has_users,
        has_users=has_users,
        site_name=site_name,
    )


@router.get("/wizard", response_model=InstallWizardStatus)
async def get_install_wizard_status(
    db: DatabaseSession,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Return setup checklist state for install/onboarding UIs."""
    await _require_install_wizard_access(db, current_user)
    settings_service = SettingsService(db)
    user_count = await _count_users(db)
    library_count_result = await db.execute(select(func.count()).select_from(Library))
    library_count = library_count_result.scalar() or 0

    site_name = await settings_service.get("system.site_name", "Streamarr")
    locale = await settings_service.get("system.locale", "de-DE")
    app_url = await settings_service.get("system.app_url", "")
    public_hostname = await settings_service.get("network.public_hostname")
    metadata_keys = await settings_service.get_many(
        [
            "plugin.tmdb.api_key",
            "plugin.tvdb.api_key",
            "plugin.igdb.client_id",
            "plugin.spotify.client_id",
        ]
    )
    configured_metadata = sorted(
        key.removeprefix("plugin.").split(".", 1)[0]
        for key, value in metadata_keys.items()
        if value
    )
    steps = [
        InstallWizardStep(
            id="admin_user",
            label="Create administrator",
            complete=user_count > 0,
            details={"user_count": user_count},
        ),
        InstallWizardStep(
            id="system_settings",
            label="Configure system",
            complete=bool(site_name and locale),
            details={"site_name": site_name, "locale": locale},
        ),
        InstallWizardStep(
            id="libraries",
            label="Add media libraries",
            complete=library_count > 0,
            details={"library_count": library_count},
        ),
        InstallWizardStep(
            id="network",
            label="Configure public access",
            complete=bool(app_url or public_hostname),
            required=False,
            details={"app_url": app_url, "public_hostname": public_hostname},
        ),
        InstallWizardStep(
            id="metadata",
            label="Configure metadata providers",
            complete=bool(configured_metadata),
            required=False,
            details={"configured_providers": configured_metadata},
        ),
    ]
    incomplete_required = next(
        (step for step in steps if step.required and not step.complete),
        None,
    )
    return InstallWizardStatus(
        installed=user_count > 0,
        current_step=incomplete_required.id if incomplete_required else None,
        steps=steps,
    )


@router.post("/setup", response_model=InitialSetupResponse)
async def initial_setup(db: DatabaseSession, setup_data: InitialSetupRequest):
    """
    Perform initial system setup.

    This endpoint creates the first admin user and configures basic system settings.
    It can only be called when no users exist in the system.

    **Security Note**: This endpoint is only available before the first user is created.
    After the initial setup, this endpoint will return a 403 Forbidden error.
    """
    # Check if system is already installed
    user_count = await _count_users(db)

    if user_count > 0:
        logger.warning("Installation setup attempted but system is already installed")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System is already installed. Initial setup cannot be performed again.",
        )

    # Check if email is already taken (shouldn't happen, but be safe)
    email_check = select(User).where(User.email == setup_data.email)
    existing_user = await db.execute(email_check)
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address is already in use",
        )

    try:
        await InstallationService(db).perform_initial_setup(
            email=setup_data.email,
            password=setup_data.password,
            first_name=setup_data.first_name,
            last_name=setup_data.last_name,
            site_name=setup_data.site_name,
            locale=setup_data.locale,
        )

        return InitialSetupResponse(
            success=True,
            message="Initial setup completed successfully",
            user_email=setup_data.email,
            site_name=setup_data.site_name or "Streamarr",
        )

    except Exception as e:
        await db.rollback()
        logger.error("Initial setup failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete initial setup",
        )


@router.get("/wizard/configuration", response_model=InstallWizardConfiguration)
async def get_install_wizard_configuration(
    db: DatabaseSession,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Return initial server configuration through the install wizard route."""
    await _require_install_wizard_access(db, current_user)
    settings_service = SettingsService(db)
    return InstallWizardConfiguration(
        server_name=await settings_service.get("system.site_name", "Streamarr"),
        ui_culture=await settings_service.get("system.locale", "de-DE"),
        metadata_country_code=await settings_service.get(
            "metadata.country_code", "DE"
        ),
        preferred_metadata_language=await settings_service.get(
            "metadata.preferred_language", "de"
        ),
    )


@router.post("/wizard/configuration", status_code=status.HTTP_204_NO_CONTENT)
async def update_install_wizard_configuration(
    db: DatabaseSession,
    config: InstallWizardConfiguration,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Update initial server configuration through the install wizard route."""
    await _require_install_wizard_access(db, current_user)
    settings_service = SettingsService(db)
    await settings_service.set_many(
        {
            "system.site_name": config.server_name or "",
            "system.locale": config.ui_culture or "",
            "metadata.country_code": config.metadata_country_code or "",
            "metadata.preferred_language": config.preferred_metadata_language or "",
        }
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/wizard/remote-access", status_code=status.HTTP_204_NO_CONTENT)
async def update_install_wizard_remote_access(
    db: DatabaseSession,
    config: InstallWizardRemoteAccess,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Update remote access through the install wizard route."""
    await _require_install_wizard_access(db, current_user)
    await SettingsService(db).set(
        "network.remote_access_enabled", config.enable_remote_access
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/wizard/user", response_model=InstallWizardUser)
async def get_install_wizard_user(
    db: DatabaseSession,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Return the first local user for install/onboarding UIs."""
    await _require_install_wizard_access(db, current_user)
    user = await _get_first_user(db)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return InstallWizardUser(name=user.preferred_username or user.first_name)


@router.post("/wizard/user", status_code=status.HTTP_204_NO_CONTENT)
async def update_install_wizard_user(
    db: DatabaseSession,
    user_data: InstallWizardUser,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Update the first local user's name and password."""
    await _require_install_wizard_access(db, current_user)
    user = await _get_first_user(db)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user_data.password or not user_data.password.strip():
        raise HTTPException(status_code=400, detail="Password must not be empty")

    if user_data.name is not None:
        name = user_data.name.strip()
        if name:
            user.first_name = name
            user.preferred_username = name

    user.hashed_password = jwt_handler.get_password_hash(user_data.password)
    db.add(user)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/wizard/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_install_wizard(
    db: DatabaseSession,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Mark the install wizard as completed in system settings."""
    await _require_install_wizard_access(db, current_user)
    await SettingsService(db).set("system.install_wizard_completed", True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
