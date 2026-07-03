"""Server plugin package registry and lifecycle metadata endpoints."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.auth.dependencies import get_current_superuser
from pyrate.database import get_db_session
from pyrate.models.user import User
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.services.activity_log import ActivityLogService
from pyrate.services.settings import SettingsService

router = APIRouter()

PluginStatus = Literal[
    "installed",
    "disabled",
    "update_available",
    "restart_required",
    "failed",
    "uninstalled",
]
PluginRuntimeKind = Literal["metadata", "static", "external"]
_CAPABILITY_PATTERN = re.compile(r"^[a-z0-9_.:-]+$")


class PluginRepository(BaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)


class PluginRepositoriesUpdate(BaseModel):
    repositories: list[PluginRepository] = Field(default_factory=list, max_length=50)


class PluginNotificationEvent(BaseModel):
    event_type: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9_.:-]+$",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    payload_schema: dict = Field(default_factory=dict)
    default_severity: Literal["info", "warning", "error"] = "info"


class PluginPackage(BaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    source_repository_id: str | None = Field(default=None, max_length=100)
    status: PluginStatus = "installed"
    enabled: bool = True
    runtime_kind: PluginRuntimeKind = "metadata"
    entry_point: str | None = Field(default=None, max_length=500)
    requires_restart: bool = False
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    installed_at: datetime | None = None
    updated_at: datetime | None = None
    configuration: dict = Field(default_factory=dict)
    notification_events: list[PluginNotificationEvent] = Field(
        default_factory=list,
        max_length=100,
    )


class PluginPackagesUpdate(BaseModel):
    plugins: list[PluginPackage] = Field(default_factory=list, max_length=200)


class PluginInstallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    source_repository_id: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool = True
    runtime_kind: PluginRuntimeKind = "metadata"
    entry_point: str | None = Field(default=None, max_length=500)
    requires_restart: bool = False
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    configuration: dict = Field(default_factory=dict)
    notification_events: list[PluginNotificationEvent] = Field(
        default_factory=list,
        max_length=100,
    )


class PluginUpdateRequest(BaseModel):
    version: str | None = Field(default=None, min_length=1, max_length=100)
    status: PluginStatus = "restart_required"
    runtime_kind: PluginRuntimeKind | None = None
    entry_point: str | None = Field(default=None, max_length=500)
    requires_restart: bool | None = None
    capabilities: list[str] | None = Field(default=None, max_length=100)
    configuration: dict | None = None
    notification_events: list[PluginNotificationEvent] | None = Field(
        default=None,
        max_length=100,
    )


class PluginRepositorySyncResponse(BaseModel):
    repository_id: str
    status: Literal["queued", "skipped"]
    enabled: bool
    plugin_count: int


class PluginRuntimePolicy(BaseModel):
    executable_packages_enabled: bool = False
    execution_allowed: bool = False
    allowed_runtime_kinds: list[PluginRuntimeKind] = ["metadata", "static", "external"]
    install_strategy: Literal["metadata_only"] = "metadata_only"
    notes: str


class PluginRuntimeSummary(BaseModel):
    policy: PluginRuntimePolicy
    installed_count: int
    enabled_count: int
    restart_required_count: int
    advertised_capabilities: list[str] = Field(default_factory=list)


class PluginValidationIssue(BaseModel):
    plugin_id: str
    plugin_name: str | None = None
    event_type: str | None = None
    capability: str | None = None
    field: str
    severity: Literal["warning", "error"] = "error"
    message: str


class PluginValidationSummary(BaseModel):
    invalid_notification_events: list[PluginValidationIssue] = Field(default_factory=list)
    invalid_capabilities: list[PluginValidationIssue] = Field(default_factory=list)
    runtime_warnings: list[PluginValidationIssue] = Field(default_factory=list)
    valid: bool = True


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ensure_unique_ids(items: list[BaseModel]) -> None:
    seen: set[str] = set()
    for item in items:
        item_id = getattr(item, "id")
        if item_id in seen:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate plugin id '{item_id}'",
            )
        seen.add(item_id)


def _core_notification_event_types() -> set[str]:
    from pyrate.api.v1.notifications import EVENT_DEFINITIONS

    return {definition.event_type for definition in EVENT_DEFINITIONS}


def _validation_summary_for_plugins(plugins: list[PluginPackage]) -> PluginValidationSummary:
    core_event_types = _core_notification_event_types()
    seen_plugin_events: dict[str, str] = {}
    invalid_notification_events: list[PluginValidationIssue] = []
    invalid_capabilities: list[PluginValidationIssue] = []
    runtime_warnings: list[PluginValidationIssue] = []

    for plugin in plugins:
        for event in plugin.notification_events:
            if event.event_type in core_event_types:
                invalid_notification_events.append(
                    PluginValidationIssue(
                        plugin_id=plugin.id,
                        plugin_name=plugin.name,
                        event_type=event.event_type,
                        field="notification_events",
                        message="Plugin event conflicts with the core notification catalog",
                    )
                )
            elif not event.event_type.startswith("plugin."):
                invalid_notification_events.append(
                    PluginValidationIssue(
                        plugin_id=plugin.id,
                        plugin_name=plugin.name,
                        event_type=event.event_type,
                        field="notification_events",
                        message="Plugin notification events must use the plugin. prefix",
                    )
                )
            elif event.event_type in seen_plugin_events:
                invalid_notification_events.append(
                    PluginValidationIssue(
                        plugin_id=plugin.id,
                        plugin_name=plugin.name,
                        event_type=event.event_type,
                        field="notification_events",
                        message=(
                            "Plugin event duplicates event advertised by "
                            f"{seen_plugin_events[event.event_type]}"
                        ),
                    )
                )
            else:
                seen_plugin_events[event.event_type] = plugin.id

        for capability in plugin.capabilities:
            if not isinstance(capability, str) or not _CAPABILITY_PATTERN.fullmatch(capability):
                invalid_capabilities.append(
                    PluginValidationIssue(
                        plugin_id=plugin.id,
                        plugin_name=plugin.name,
                        capability=str(capability),
                        field="capabilities",
                        message="Capability must use lowercase metadata tokens",
                    )
                )

        if plugin.runtime_kind != "metadata":
            runtime_warnings.append(
                PluginValidationIssue(
                    plugin_id=plugin.id,
                    plugin_name=plugin.name,
                    field="runtime_kind",
                    severity="warning",
                    message=(
                        "Runtime metadata is recorded for admins only; pyrate does not "
                        "execute plugin package code"
                    ),
                )
            )

    return PluginValidationSummary(
        invalid_notification_events=invalid_notification_events,
        invalid_capabilities=invalid_capabilities,
        runtime_warnings=runtime_warnings,
        valid=not invalid_notification_events and not invalid_capabilities,
    )


def _raise_for_invalid_plugins(plugins: list[PluginPackage]) -> None:
    summary = _validation_summary_for_plugins(plugins)
    errors = [*summary.invalid_notification_events, *summary.invalid_capabilities]
    if not errors:
        return
    raise HTTPException(
        status_code=422,
        detail=[issue.model_dump(exclude_none=True) for issue in errors],
    )


async def _load_repositories(session: AsyncSession) -> list[PluginRepository]:
    raw_repositories = await SettingsService(session).get("plugins.repositories", [])
    if not isinstance(raw_repositories, list):
        return []
    repositories: list[PluginRepository] = []
    for raw in raw_repositories:
        if not isinstance(raw, dict):
            continue
        try:
            repositories.append(PluginRepository(**raw))
        except Exception:
            continue
    return repositories


async def _load_plugins(session: AsyncSession) -> list[PluginPackage]:
    raw_plugins = await SettingsService(session).get("plugins.installed", [])
    if not isinstance(raw_plugins, list):
        return []
    plugins: list[PluginPackage] = []
    for raw in raw_plugins:
        if not isinstance(raw, dict):
            continue
        try:
            plugins.append(PluginPackage(**raw))
        except Exception:
            continue
    return plugins


async def _load_raw_plugin_dicts(session: AsyncSession) -> list[dict[str, Any]]:
    raw_plugins = await SettingsService(session).get("plugins.installed", [])
    if not isinstance(raw_plugins, list):
        return []
    return [plugin for plugin in raw_plugins if isinstance(plugin, dict)]


async def _save_plugins(session: AsyncSession, plugins: list[PluginPackage]) -> None:
    await SettingsService(session).set(
        "plugins.installed",
        [plugin.model_dump(mode="json", exclude_none=True) for plugin in plugins],
    )


async def _log_plugin_event(
    session: AsyncSession,
    current_user: User,
    event_type: str,
    message: str,
    extra_data: dict,
) -> None:
    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type=event_type,
            message=message,
            entity_type="plugin",
            extra_data=json.dumps(extra_data, sort_keys=True),
        ),
        actor_guid=current_user.guid,
    )


@router.get("/repositories", response_model=list[PluginRepository])
async def list_plugin_repositories(
    current_user: User = Depends(get_current_superuser),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
):
    """List configured plugin update repositories."""
    return sorted(
        await _load_repositories(session),
        key=lambda repository: (repository.priority, repository.name.lower()),
    )


@router.put("/repositories", response_model=list[PluginRepository])
async def update_plugin_repositories(
    update: PluginRepositoriesUpdate,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Replace configured plugin update repositories."""
    _ensure_unique_ids(update.repositories)
    repositories = sorted(
        update.repositories,
        key=lambda repository: (repository.priority, repository.name.lower()),
    )
    await SettingsService(session).set(
        "plugins.repositories",
        [
            repository.model_dump(mode="json", exclude_none=True)
            for repository in repositories
        ],
    )
    await _log_plugin_event(
        session,
        current_user,
        "plugins.repositories_update",
        f"Updated {len(repositories)} plugin repositories",
        {"count": len(repositories)},
    )
    return repositories


@router.post(
    "/repositories/{repository_id}/sync",
    response_model=PluginRepositorySyncResponse,
)
async def sync_plugin_repository(
    repository_id: str,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Queue a metadata refresh for a configured plugin repository."""
    repository = next(
        (
            repository
            for repository in await _load_repositories(session)
            if repository.id == repository_id
        ),
        None,
    )
    if not repository:
        raise HTTPException(status_code=404, detail="Plugin repository not found")

    plugin_count = sum(
        1
        for plugin in await _load_plugins(session)
        if plugin.source_repository_id == repository.id
    )
    status: Literal["queued", "skipped"] = (
        "queued" if repository.enabled else "skipped"
    )
    await _log_plugin_event(
        session,
        current_user,
        "plugins.repository_sync",
        f"Queued plugin repository sync for {repository.name}",
        {
            "repository_id": repository.id,
            "enabled": repository.enabled,
            "status": status,
            "plugin_count": plugin_count,
        },
    )
    return PluginRepositorySyncResponse(
        repository_id=repository.id,
        status=status,
        enabled=repository.enabled,
        plugin_count=plugin_count,
    )


@router.get("/installed", response_model=list[PluginPackage])
async def list_installed_plugins(
    current_user: User = Depends(get_current_superuser),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
):
    """List installed server plugin package metadata."""
    return sorted(await _load_plugins(session), key=lambda plugin: plugin.name.lower())


@router.get("/runtime-policy", response_model=PluginRuntimeSummary)
async def get_plugin_runtime_policy(
    current_user: User = Depends(get_current_superuser),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
):
    """Return the safe plugin runtime contract supported by this server."""
    plugins = await _load_plugins(session)
    capabilities = sorted(
        {
            capability
            for plugin in plugins
            for capability in plugin.capabilities
            if isinstance(capability, str) and capability
        }
    )
    return PluginRuntimeSummary(
        policy=PluginRuntimePolicy(
            notes=(
                "pyrate currently stores plugin repository, lifecycle, UI/static, "
                "external integration, and notification metadata. It does not "
                "download or execute arbitrary plugin code."
            )
        ),
        installed_count=len(plugins),
        enabled_count=sum(1 for plugin in plugins if plugin.enabled),
        restart_required_count=sum(
            1 for plugin in plugins if plugin.status == "restart_required"
        ),
        advertised_capabilities=capabilities,
    )


@router.get("/validation", response_model=PluginValidationSummary)
async def validate_plugin_metadata(
    current_user: User = Depends(get_current_superuser),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
):
    """Validate stored plugin metadata against pyrate's safe runtime contract."""
    raw_plugins = await _load_raw_plugin_dicts(session)
    plugins: list[PluginPackage] = []
    raw_issues: list[PluginValidationIssue] = []
    for raw in raw_plugins:
        plugin_id = str(raw.get("id") or "unknown")
        try:
            plugins.append(PluginPackage(**raw))
        except Exception as exc:
            raw_issues.append(
                PluginValidationIssue(
                    plugin_id=plugin_id,
                    plugin_name=raw.get("name") if isinstance(raw.get("name"), str) else None,
                    field="plugin",
                    message=f"Stored plugin metadata is invalid: {exc}",
                )
            )

    summary = _validation_summary_for_plugins(plugins)
    summary.invalid_notification_events = [
        *raw_issues,
        *summary.invalid_notification_events,
    ]
    summary.valid = (
        not summary.invalid_notification_events
        and not summary.invalid_capabilities
    )
    return summary


@router.put("/installed", response_model=list[PluginPackage])
async def update_installed_plugins(
    update: PluginPackagesUpdate,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Replace installed plugin lifecycle metadata."""
    _ensure_unique_ids(update.plugins)
    _raise_for_invalid_plugins(update.plugins)
    plugins = sorted(update.plugins, key=lambda plugin: plugin.name.lower())
    await _save_plugins(session, plugins)
    await _log_plugin_event(
        session,
        current_user,
        "plugins.installed_update",
        f"Updated {len(plugins)} installed plugins",
        {"count": len(plugins)},
    )
    return plugins


@router.post("/installed/{plugin_id}", response_model=PluginPackage)
async def install_plugin_metadata(
    plugin_id: str,
    request: PluginInstallRequest,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Create or replace metadata for an installed plugin package."""
    plugins = await _load_plugins(session)
    now = _utcnow()
    existing = next((plugin for plugin in plugins if plugin.id == plugin_id), None)
    plugin = PluginPackage(
        id=plugin_id,
        name=request.name,
        version=request.version,
        source_repository_id=request.source_repository_id,
        status="installed" if request.enabled else "disabled",
        enabled=request.enabled,
        runtime_kind=request.runtime_kind,
        entry_point=request.entry_point,
        requires_restart=request.requires_restart,
        capabilities=request.capabilities,
        description=request.description,
        installed_at=existing.installed_at if existing else now,
        updated_at=now,
        configuration=request.configuration,
        notification_events=request.notification_events,
    )
    _raise_for_invalid_plugins([plugin])
    plugins = [candidate for candidate in plugins if candidate.id != plugin_id]
    plugins.append(plugin)
    await _save_plugins(session, sorted(plugins, key=lambda item: item.name.lower()))
    await _log_plugin_event(
        session,
        current_user,
        "plugins.install",
        f"Installed plugin metadata for {plugin.name}",
        {"plugin_id": plugin.id, "version": plugin.version},
    )
    return plugin


@router.post("/installed/{plugin_id}/enable", response_model=PluginPackage)
async def enable_plugin(
    plugin_id: str,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Mark an installed plugin package enabled."""
    plugin, plugins = await _mutate_plugin(session, plugin_id)
    plugin.enabled = True
    plugin.status = "installed"
    plugin.updated_at = _utcnow()
    await _save_plugins(session, plugins)
    await _log_plugin_event(
        session,
        current_user,
        "plugins.enable",
        f"Enabled plugin {plugin.name}",
        {"plugin_id": plugin.id},
    )
    return plugin


@router.post("/installed/{plugin_id}/disable", response_model=PluginPackage)
async def disable_plugin(
    plugin_id: str,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Mark an installed plugin package disabled."""
    plugin, plugins = await _mutate_plugin(session, plugin_id)
    plugin.enabled = False
    plugin.status = "disabled"
    plugin.updated_at = _utcnow()
    await _save_plugins(session, plugins)
    await _log_plugin_event(
        session,
        current_user,
        "plugins.disable",
        f"Disabled plugin {plugin.name}",
        {"plugin_id": plugin.id},
    )
    return plugin


@router.post("/installed/{plugin_id}/update", response_model=PluginPackage)
async def update_plugin_metadata(
    plugin_id: str,
    request: PluginUpdateRequest,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Update lifecycle metadata for an installed plugin package."""
    plugin, plugins = await _mutate_plugin(session, plugin_id)
    if request.version is not None:
        plugin.version = request.version
    if request.runtime_kind is not None:
        plugin.runtime_kind = request.runtime_kind
    if request.entry_point is not None:
        plugin.entry_point = request.entry_point
    if request.requires_restart is not None:
        plugin.requires_restart = request.requires_restart
    if request.capabilities is not None:
        plugin.capabilities = request.capabilities
    if request.configuration is not None:
        plugin.configuration = request.configuration
    if request.notification_events is not None:
        plugin.notification_events = request.notification_events
    _raise_for_invalid_plugins(plugins)
    plugin.status = request.status
    plugin.enabled = request.status != "disabled"
    plugin.updated_at = _utcnow()
    await _save_plugins(session, plugins)
    await _log_plugin_event(
        session,
        current_user,
        "plugins.update",
        f"Updated plugin metadata for {plugin.name}",
        {"plugin_id": plugin.id, "version": plugin.version, "status": plugin.status},
    )
    return plugin


@router.delete("/installed/{plugin_id}", response_model=PluginPackage)
async def uninstall_plugin_metadata(
    plugin_id: str,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Remove metadata for an installed plugin package."""
    plugin, plugins = await _mutate_plugin(session, plugin_id)
    remaining = [candidate for candidate in plugins if candidate.id != plugin_id]
    await _save_plugins(session, remaining)
    plugin.status = "uninstalled"
    plugin.enabled = False
    plugin.updated_at = _utcnow()
    await _log_plugin_event(
        session,
        current_user,
        "plugins.uninstall",
        f"Removed plugin metadata for {plugin.name}",
        {"plugin_id": plugin.id},
    )
    return plugin


async def _mutate_plugin(
    session: AsyncSession, plugin_id: str
) -> tuple[PluginPackage, list[PluginPackage]]:
    plugins = await _load_plugins(session)
    plugin = next(
        (candidate for candidate in plugins if candidate.id == plugin_id),
        None,
    )
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin, plugins
