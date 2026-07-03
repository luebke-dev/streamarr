"""System information endpoints."""

from __future__ import annotations

import platform
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from ipaddress import ip_address

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from pyrate.api.dependencies import (
    CurrentSuperuser,
    DatabaseSession,
    UserPermissionsDep,
)
from pyrate.config import connection_settings
from pyrate.services.cache_control import (
    artwork_cache_stats,
    cleanup_artwork_cache,
    clear_rendered_layout_cache,
    rendered_layout_cache_stats,
)
from pyrate.services.page_layout import PageLayoutService
from pyrate.services.system_settings import SystemSettingsService

router = APIRouter()


class SystemEndpointInfo(BaseModel):
    is_local: bool
    is_in_network: bool
    remote_address: str | None = None
    forwarded_for: str | None = None


class UtcTimeResponse(BaseModel):
    request_reception_time: datetime
    response_transmission_time: datetime


class SystemDiagnosticsResponse(BaseModel):
    generated_at: datetime
    product_name: str
    version: str
    python_version: str
    platform: str
    database_configured: bool
    redis_configured: bool
    elasticsearch_configured: bool
    app_url_configured: bool
    timezone: str
    authenticated_as: str


class CacheDiagnosticsResponse(BaseModel):
    generated_at: datetime
    rendered_layouts: dict
    artwork: dict


class CacheCleanupResponse(BaseModel):
    path: str
    deleted_files: int
    deleted_bytes: int
    remaining_files: int
    remaining_bytes: int
    dry_run: bool


class HomepageSmokeResponse(BaseModel):
    generated_at: datetime
    layout_found: bool
    layout_slug: str | None = None
    sections: int = 0
    enabled_sections: int = 0
    rendered_cache: dict
    artwork_cache: dict


def _is_private_or_local(address: str | None) -> tuple[bool, bool]:
    if not address:
        return False, False
    if address == "localhost":
        return True, True
    try:
        parsed = ip_address(address)
    except ValueError:
        return False, False
    return parsed.is_loopback, parsed.is_loopback or parsed.is_private


def _app_version() -> str:
    try:
        return version("pyrate")
    except PackageNotFoundError:
        return "unknown"


@router.get("/ping", response_model=str)
async def ping_system():
    """Return a lightweight public health response."""
    return "pyrate.media"


@router.get("/endpoint", response_model=SystemEndpointInfo)
async def get_system_endpoint(request: Request):
    """Return public client endpoint information without exposing server secrets."""
    forwarded_for = request.headers.get("x-forwarded-for")
    remote_address = None
    if forwarded_for:
        remote_address = forwarded_for.split(",", 1)[0].strip()
    elif request.client:
        remote_address = request.client.host

    is_local, is_in_network = _is_private_or_local(remote_address)

    return SystemEndpointInfo(
        is_local=is_local,
        is_in_network=is_in_network,
        remote_address=remote_address,
        forwarded_for=forwarded_for,
    )


def utc_time_payload() -> UtcTimeResponse:
    """Build a clock-sync response with receive/transmit timestamps."""
    request_reception_time = datetime.now(UTC)
    response_transmission_time = datetime.now(UTC)
    return UtcTimeResponse(
        request_reception_time=request_reception_time,
        response_transmission_time=response_transmission_time,
    )


@router.get("/utc-time", response_model=UtcTimeResponse)
async def get_utc_time():
    """Return current UTC timestamps for client clock synchronization."""
    return utc_time_payload()


@router.get("/info/public")
async def get_public_system_info(db: DatabaseSession):
    """Return public, non-sensitive server identity information."""
    system_settings = await SystemSettingsService(db).get_system_settings()
    return {
        "product_name": "pyrate.media",
        "version": _app_version(),
        "site_name": system_settings["site_name"],
        "locale": system_settings["locale"],
        "app_url": system_settings["app_url"],
    }


@router.get("/info")
async def get_system_info(db: DatabaseSession, current_user: CurrentSuperuser):
    """Return admin-only runtime information without secrets."""
    public_info = await get_public_system_info(db)
    return {
        **public_info,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "database_configured": bool(connection_settings.database_url),
        "redis_configured": bool(connection_settings.redis_url),
        "elasticsearch": {
            "host": connection_settings.elasticsearch.host,
            "port": connection_settings.elasticsearch.port,
            "use_ssl": connection_settings.elasticsearch.use_ssl,
        },
        "authenticated_as": str(current_user.guid),
    }


@router.get("/diagnostics", response_model=SystemDiagnosticsResponse)
async def get_system_diagnostics(
    db: DatabaseSession, current_user: CurrentSuperuser
):
    """Return admin runtime diagnostics without secrets."""
    system_settings = await SystemSettingsService(db).get_system_settings()
    return SystemDiagnosticsResponse(
        generated_at=datetime.now(UTC),
        product_name="pyrate.media",
        version=_app_version(),
        python_version=platform.python_version(),
        platform=platform.platform(),
        database_configured=bool(connection_settings.database_url),
        redis_configured=bool(connection_settings.redis_url),
        elasticsearch_configured=bool(connection_settings.elasticsearch.host),
        app_url_configured=bool(system_settings.get("app_url")),
        timezone=str(system_settings.get("timezone") or "UTC"),
        authenticated_as=str(current_user.guid),
    )


@router.get("/cache", response_model=CacheDiagnosticsResponse)
async def get_cache_diagnostics(current_user: CurrentSuperuser):
    """Return admin cache diagnostics and update Prometheus artwork gauges."""
    return CacheDiagnosticsResponse(
        generated_at=datetime.now(UTC),
        rendered_layouts=await rendered_layout_cache_stats(),
        artwork=artwork_cache_stats(),
    )


@router.post("/cache/layouts/clear")
async def clear_layout_cache(current_user: CurrentSuperuser):
    """Clear rendered layout caches after operational changes."""
    return await clear_rendered_layout_cache("manual")


@router.post("/cache/artwork/cleanup", response_model=CacheCleanupResponse)
async def cleanup_artwork_cache_endpoint(
    current_user: CurrentSuperuser,
    max_bytes: int | None = Query(None, ge=1),
    max_age_days: int | None = Query(None, ge=1),
    dry_run: bool = Query(False),
):
    """Apply max-size and/or max-age cleanup to the optional artwork cache."""
    return CacheCleanupResponse(
        **cleanup_artwork_cache(
            max_bytes=max_bytes,
            max_age_days=max_age_days,
            dry_run=dry_run,
        )
    )


@router.get("/smoke/homepage", response_model=HomepageSmokeResponse)
async def homepage_smoke(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    permissions: UserPermissionsDep,
):
    """Cheap admin smoke check for homepage layout/cache/artwork readiness."""
    layout = await PageLayoutService(db).get_layout_by_slug("home")
    sections = layout.sections if layout else []
    return HomepageSmokeResponse(
        generated_at=datetime.now(UTC),
        layout_found=layout is not None,
        layout_slug=layout.slug if layout else None,
        sections=len(sections),
        enabled_sections=len([section for section in sections if section.is_enabled]),
        rendered_cache=await rendered_layout_cache_stats(),
        artwork_cache=artwork_cache_stats(),
    )
