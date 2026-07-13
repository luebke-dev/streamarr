"""Metadata providers API — configure and manage metadata sources."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from streamarr.api.dependencies import CurrentSuperuser, DatabaseSession
from streamarr.services.metadata import METADATA_PROVIDERS, MetadataService

router = APIRouter()


class ProviderConfigUpdate(BaseModel):
    config: dict[str, Any]


class ProviderInfo(BaseModel):
    domain: str
    name: str
    description: str
    icon: str
    media_types: list[str]
    capabilities: dict[str, bool] = {}
    has_config: bool
    config_schema: dict[str, Any]
    configured: bool = False


class ProviderCapabilities(BaseModel):
    domain: str
    name: str
    media_types: list[str]
    capabilities: dict[str, bool]


class ConnectionTestResult(BaseModel):
    success: bool
    error: str | None = None
    errors: list[str] = []


@router.get("/providers", response_model=list[ProviderInfo])
async def list_providers(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """List all metadata providers with their config status."""
    service = MetadataService(db)
    providers = service.list_providers()

    result = []
    for p in providers:
        configured = await service.is_configured(p["domain"])
        result.append(ProviderInfo(**p, configured=configured))

    return result


@router.get("/providers/{domain}/schema")
async def get_provider_schema(
    domain: str,
    current_user: CurrentSuperuser,
):
    """Get config schema for a metadata provider."""
    if domain not in METADATA_PROVIDERS:
        raise HTTPException(status_code=404, detail="Provider not found")

    service = MetadataService.__new__(MetadataService)
    return service.get_provider_schema(domain)


@router.get("/providers/{domain}/capabilities", response_model=ProviderCapabilities)
async def get_provider_capabilities(
    domain: str,
    current_user: CurrentSuperuser,
):
    """Get declared provider capability flags for admin UI decisions."""
    if domain not in METADATA_PROVIDERS:
        raise HTTPException(status_code=404, detail="Provider not found")

    service = MetadataService.__new__(MetadataService)
    return service.get_provider_capabilities(domain)


@router.get("/providers/{domain}/config")
async def get_provider_config(
    db: DatabaseSession,
    domain: str,
    current_user: CurrentSuperuser,
):
    """Get current config for a metadata provider."""
    if domain not in METADATA_PROVIDERS:
        raise HTTPException(status_code=404, detail="Provider not found")

    service = MetadataService(db)
    config = await service.get_provider_config(domain)
    return {"domain": domain, "config": config}


@router.put("/providers/{domain}/config")
async def update_provider_config(
    db: DatabaseSession,
    domain: str,
    body: ProviderConfigUpdate,
    current_user: CurrentSuperuser,
):
    """Update config for a metadata provider."""
    if domain not in METADATA_PROVIDERS:
        raise HTTPException(status_code=404, detail="Provider not found")

    service = MetadataService(db)

    # Validate first
    validation = await service.validate_provider_config(domain, body.config)
    if not validation.get("valid", True):
        raise HTTPException(
            status_code=400,
            detail={"message": "Invalid configuration", "errors": validation.get("errors", [])},
        )

    await service.set_provider_config(domain, body.config)
    return {"domain": domain, "message": "Configuration saved"}


@router.post("/providers/{domain}/validate")
async def validate_provider_config(
    db: DatabaseSession,
    domain: str,
    body: ProviderConfigUpdate,
    current_user: CurrentSuperuser,
):
    """Validate config for a metadata provider without saving."""
    if domain not in METADATA_PROVIDERS:
        raise HTTPException(status_code=404, detail="Provider not found")

    service = MetadataService(db)
    result = await service.validate_provider_config(domain, body.config)
    return result


@router.post("/providers/{domain}/test", response_model=ConnectionTestResult)
async def test_provider_connection(
    db: DatabaseSession,
    domain: str,
    current_user: CurrentSuperuser,
    body: ProviderConfigUpdate | None = None,
):
    """Test connection to a metadata provider."""
    if domain not in METADATA_PROVIDERS:
        raise HTTPException(status_code=404, detail="Provider not found")

    service = MetadataService(db)
    config = body.config if body else None
    result = await service.test_connection(domain, config)
    return result
