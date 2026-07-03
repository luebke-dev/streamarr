"""Public branding configuration endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.auth.dependencies import get_current_superuser
from pyrate.database import get_db_session
from pyrate.models.user import User
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.services.activity_log import ActivityLogService
from pyrate.services.settings import SettingsService

router = APIRouter()


class BrandingConfiguration(BaseModel):
    server_name: str = Field(default="pyrate.media", min_length=1, max_length=200)
    login_disclaimer: str = Field(default="", max_length=5000)
    custom_css: str = Field(default="", max_length=100000)
    logo_url: str | None = Field(default=None, max_length=1000)
    splashscreen_enabled: bool = False
    active_theme_id: str | None = Field(default=None, max_length=100)


class BrandingConfigurationUpdate(BaseModel):
    server_name: str | None = Field(default=None, min_length=1, max_length=200)
    login_disclaimer: str | None = Field(default=None, max_length=5000)
    custom_css: str | None = Field(default=None, max_length=100000)
    logo_url: str | None = Field(default=None, max_length=1000)
    splashscreen_enabled: bool | None = None


class BrandingTheme(BaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    dark: bool = False
    enabled: bool = True
    colors: dict[str, str] = Field(default_factory=dict)
    variables: dict[str, str] = Field(default_factory=dict)
    custom_css: str = Field(default="", max_length=100000)


class BrandingThemesUpdate(BaseModel):
    themes: list[BrandingTheme] = Field(default_factory=list, max_length=50)


class ActiveThemeUpdate(BaseModel):
    theme_id: str | None = Field(default=None, max_length=100)


async def _load_branding(session: AsyncSession) -> BrandingConfiguration:
    settings = await SettingsService(session).get_many(
        [
            "branding.server_name",
            "branding.login_disclaimer",
            "branding.custom_css",
            "branding.logo_url",
            "branding.splashscreen_enabled",
            "branding.active_theme_id",
        ]
    )
    return BrandingConfiguration(
        server_name=settings.get("branding.server_name") or "pyrate.media",
        login_disclaimer=settings.get("branding.login_disclaimer") or "",
        custom_css=settings.get("branding.custom_css") or "",
        logo_url=settings.get("branding.logo_url"),
        splashscreen_enabled=bool(settings.get("branding.splashscreen_enabled")),
        active_theme_id=settings.get("branding.active_theme_id"),
    )


async def _load_themes(session: AsyncSession) -> list[BrandingTheme]:
    raw_themes = await SettingsService(session).get("branding.themes", [])
    if not isinstance(raw_themes, list):
        return []
    themes: list[BrandingTheme] = []
    for raw in raw_themes:
        if not isinstance(raw, dict):
            continue
        try:
            themes.append(BrandingTheme(**raw))
        except Exception:
            continue
    return themes


def _ensure_unique_theme_ids(themes: list[BrandingTheme]) -> None:
    seen: set[str] = set()
    for theme in themes:
        if theme.id in seen:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate theme id '{theme.id}'",
            )
        seen.add(theme.id)


@router.get("/configuration", response_model=BrandingConfiguration)
async def get_branding_configuration(
    session: AsyncSession = Depends(get_db_session),
):
    """Return public branding configuration for login and shell screens."""
    return await _load_branding(session)


@router.put("/configuration", response_model=BrandingConfiguration)
async def update_branding_configuration(
    update: BrandingConfigurationUpdate,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Update public branding configuration."""
    service = SettingsService(session)
    update_data = update.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        await service.set(f"branding.{field_name}", value)

    configuration = await _load_branding(session)
    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type="branding.update",
            message="Updated branding configuration",
            entity_type="branding",
            extra_data=json.dumps(
                {"updated_fields": sorted(update_data.keys())},
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )
    return configuration


@router.get("/themes", response_model=list[BrandingTheme])
async def list_branding_themes(
    session: AsyncSession = Depends(get_db_session),
):
    """Return enabled public branding themes."""
    return [
        theme
        for theme in sorted(await _load_themes(session), key=lambda item: item.name)
        if theme.enabled
    ]


@router.put("/themes", response_model=list[BrandingTheme])
async def update_branding_themes(
    update: BrandingThemesUpdate,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Replace configured branding themes."""
    _ensure_unique_theme_ids(update.themes)
    themes = sorted(update.themes, key=lambda item: item.name)
    await SettingsService(session).set(
        "branding.themes",
        [theme.model_dump(mode="json", exclude_none=True) for theme in themes],
    )
    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type="branding.themes_update",
            message=f"Updated {len(themes)} branding themes",
            entity_type="branding",
            extra_data=json.dumps({"count": len(themes)}, sort_keys=True),
        ),
        actor_guid=current_user.guid,
    )
    return themes


@router.get("/themes/active", response_model=BrandingTheme | None)
async def get_active_branding_theme(
    session: AsyncSession = Depends(get_db_session),
):
    """Return the currently active public theme, if configured and enabled."""
    configuration = await _load_branding(session)
    if not configuration.active_theme_id:
        return None
    return next(
        (
            theme
            for theme in await _load_themes(session)
            if theme.id == configuration.active_theme_id and theme.enabled
        ),
        None,
    )


@router.put("/themes/active", response_model=BrandingConfiguration)
async def update_active_branding_theme(
    update: ActiveThemeUpdate,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Set the active branding theme."""
    if update.theme_id is not None:
        theme = next(
            (
                theme
                for theme in await _load_themes(session)
                if theme.id == update.theme_id and theme.enabled
            ),
            None,
        )
        if theme is None:
            raise HTTPException(status_code=404, detail="Branding theme not found")

    await SettingsService(session).set("branding.active_theme_id", update.theme_id)
    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type="branding.active_theme_update",
            message="Updated active branding theme",
            entity_type="branding",
            extra_data=json.dumps({"theme_id": update.theme_id}, sort_keys=True),
        ),
        actor_guid=current_user.guid,
    )
    return await _load_branding(session)


@router.get("/css")
@router.get("/css.css")
async def get_branding_css(
    session: AsyncSession = Depends(get_db_session),
):
    """Return configured custom CSS as text/css."""
    configuration = await _load_branding(session)
    return Response(content=configuration.custom_css, media_type="text/css")
