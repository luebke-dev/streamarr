"""Unified Libraries API.

Provides both CRUD operations for library entities and configuration management.

Routes:
    POST   /libraries                           - Create new library
    GET    /libraries                           - List all libraries
    GET    /libraries/{guid}                    - Get library by GUID
    PUT    /libraries/{guid}                    - Update library
    DELETE /libraries/{guid}                    - Delete library
    POST   /libraries/{guid}/import-trending    - Import trending items from metadata provider
    POST   /libraries/{guid}/import-by-external-id - Import item by TMDB ID

    GET    /libraries/{type}/config             - Get library type configuration
    PUT    /libraries/{type}/config             - Update library type configuration
    POST   /libraries/{type}/preview-naming     - Preview naming templates
"""

import logging
import json
import uuid
import inspect
from pathlib import Path

import pyrate.plugins as plugin_facade
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.api.dependencies import DatabaseSession, get_db_session
from pyrate.auth.dependencies import get_current_superuser, get_current_user
from pyrate.libraries import get_plugin_instance
from pyrate.models.user import User
from pyrate.plugins import get_registry, get_registered_plugins
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.schemas.scoring import (
    MovieScoringConfig,
    QualityProfile,
    ShowScoringConfig,
)
from pyrate.services.activity_log import ActivityLogService
from pyrate.services.library import LibraryConfigService, LibraryService
from pyrate.services.library_imports import LibraryImportError, LibraryImportService
from pyrate.services.settings import SettingsService
from pyrate.api.utils import get_user_locale


logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# LIBRARY CRUD MODELS
# ============================================================================


class LibraryCreate(BaseModel):
    """Request model for creating a library."""

    name: str
    type: str
    plugin_id: str
    path: str | None = None
    enabled: bool = True
    settings: dict | None = None
    description: str | None = None


class LibraryUpdate(BaseModel):
    """Request model for updating a library."""

    name: str | None = None
    plugin_id: str | None = None
    path: str | None = None
    enabled: bool | None = None
    settings: dict | None = None
    description: str | None = None


class LibraryRead(BaseModel):
    """Response model for a library."""

    guid: uuid.UUID
    name: str
    type: str  # Changed from LibraryType enum to str
    plugin_id: str
    path: str | None = None
    enabled: bool
    settings: dict | None = None
    description: str | None = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @field_validator("settings", mode="before")
    @classmethod
    def _coerce_settings(cls, value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return value


class LibraryUIConfig(BaseModel):
    """UI configuration for a library plugin."""

    library_icon: str
    item_icon: str
    play_button_icon: str
    play_button_label: str


class LibraryPhysicalPathResponse(BaseModel):
    """Physical storage path information for a library."""

    library_guid: uuid.UUID
    path: str
    exists: bool
    is_directory: bool


class LibraryFolderEntry(BaseModel):
    """One filesystem entry under a library path."""

    name: str
    relative_path: str
    path: str
    is_directory: bool
    size_bytes: int | None = None
    modified_at: str | None = None


class LibraryFolderResponse(BaseModel):
    """Folder listing under a library path."""

    library_guid: uuid.UUID
    root_path: str
    relative_path: str
    entries: list[LibraryFolderEntry]


class LibraryMediaFolder(BaseModel):
    """Configured media folder path for a library."""

    path: str
    exists: bool
    is_directory: bool
    primary: bool = False


class LibraryMediaFoldersResponse(BaseModel):
    """Configured media folders for a library."""

    library_guid: uuid.UUID
    folders: list[LibraryMediaFolder]
    total: int


class LibraryMediaFolderAdd(BaseModel):
    """Media folder to attach to a library."""

    path: str = Field(min_length=1, max_length=4096)


class LibraryFolderPolicy(BaseModel):
    """Per-library folder validation policy."""

    require_existing_paths: bool = True
    require_readable_paths: bool = True
    require_writable_paths: bool = False
    allow_nested_folders: bool = True
    excluded_folder_names: list[str] = Field(default_factory=list)
    allowed_file_extensions: list[str] = Field(default_factory=list)


class LibraryFolderValidationRequest(BaseModel):
    """Folder path to validate for library use."""

    path: str = Field(min_length=1, max_length=4096)


class LibraryFolderValidationResponse(BaseModel):
    """Validation result for a candidate library folder path."""

    library_guid: uuid.UUID
    path: str
    normalized_path: str
    exists: bool
    is_directory: bool
    is_readable: bool
    is_writable: bool
    parent_exists: bool
    parent_writable: bool
    is_duplicate: bool
    is_primary: bool
    is_valid: bool
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LibraryPathMigrationRequest(BaseModel):
    """Primary library path migration request."""

    path: str = Field(min_length=1, max_length=4096)
    keep_existing_as_media_folder: bool = True
    validate_only: bool = False


class LibraryPathMigrationResponse(BaseModel):
    """Result of a primary library path migration or preview."""

    library_guid: uuid.UUID
    previous_path: str
    new_path: str
    migrated: bool
    validation: LibraryFolderValidationResponse
    media_folders: list[str] = Field(default_factory=list)


class LibraryOptions(BaseModel):
    """Per-library metadata/image/subtitle/trickplay options."""

    metadata_providers: list[str] = Field(default_factory=list)
    image_providers: list[str] = Field(default_factory=list)
    image_fetch_enabled: bool = True
    subtitle_download_enabled: bool = False
    subtitle_languages: list[str] = Field(default_factory=list)
    trickplay_enabled: bool = True
    custom: dict = Field(default_factory=dict)


class LibraryScanRequest(BaseModel):
    """Request body for library scan/refresh operations."""

    include_files: bool = False
    max_files: int = Field(50, ge=1, le=500)


class LibraryScanResponse(BaseModel):
    """Scan/refresh result for a library."""

    library_guid: uuid.UUID
    status: str
    discovered_count: int
    files: list[dict] = Field(default_factory=list)


# ============================================================================
# LIBRARY CONFIGURATION MODELS (per type)
# ============================================================================


class NamingVariable(BaseModel):
    """A single naming variable with description and example."""

    name: str
    description: str
    example: str


class NamingSchema(BaseModel):
    """Complete naming schema from plugin."""

    variables: list[NamingVariable]
    defaults: dict[str, str]
    options: dict[str, bool | str]


class NamingConfig(BaseModel):
    """Current naming configuration with schema."""

    model_config = ConfigDict(populate_by_name=True)

    naming_schema: NamingSchema = Field(alias="schema")
    current: dict[str, str | bool]


# Library Configuration Models
class MovieLibraryConfig(BaseModel):
    """Complete movie library configuration."""

    library_path: str
    enable_library: bool
    enable_on_demand_downloads: bool
    naming: NamingConfig
    allowed_languages: list[str] = []


class ShowLibraryConfig(BaseModel):
    """Complete show library configuration."""

    library_path: str
    enable_library: bool
    enable_on_demand_downloads: bool
    enable_prefetch_downloads: bool
    hide_season_zero: bool
    naming: NamingConfig
    allowed_languages: list[str] = []


class SimpleLibraryConfig(BaseModel):
    """Configuration for simple libraries."""

    library_path: str
    enable_library: bool
    enable_on_demand_downloads: bool
    naming: NamingConfig


# Update Models
class MovieLibraryUpdate(BaseModel):
    """Update movie library configuration."""

    library_path: str | None = None
    enable_library: bool | None = None
    enable_on_demand_downloads: bool | None = None
    naming: dict[str, str | bool] | None = None
    allowed_languages: list[str] | None = None


class ShowLibraryUpdate(BaseModel):
    """Update show library configuration."""

    library_path: str | None = None
    enable_library: bool | None = None
    enable_on_demand_downloads: bool | None = None
    enable_prefetch_downloads: bool | None = None
    hide_season_zero: bool | None = None
    naming: dict[str, str | bool] | None = None
    allowed_languages: list[str] | None = None


class SimpleLibraryUpdate(BaseModel):
    """Update simple library configuration."""

    library_path: str | None = None
    enable_library: bool | None = None
    enable_on_demand_downloads: bool | None = None
    naming: dict[str, str | bool] | None = None
    allowed_platforms: list[str] | None = None  # For games: filter by platform


# Preview Models
class NamingPreviewResponse(BaseModel):
    """Preview of generated folder/file names."""

    folder: str | None = None
    season_folder: str | None = None
    file: str | None = None
    full_path: str | None = None


# Helper Functions
async def _load_naming_config(
    settings_service: SettingsService, plugin_instance, prefix: str
) -> NamingConfig:
    """Load naming configuration with schema and current templates."""
    schema_dict = plugin_instance.get_naming_schema()

    variables = [
        NamingVariable(
            name=var["name"], description=var["description"], example=var["example"]
        )
        for var in schema_dict.get("variables", [])
    ]

    schema = NamingSchema(
        variables=variables,
        defaults=schema_dict.get("defaults", {}),
        options=schema_dict.get("options", {}),
    )

    current_templates = {}
    for key in schema_dict.get("defaults", {}).keys():
        setting_key = f"{prefix}.naming.{key}"
        value = await settings_service.get(setting_key)
        if value:
            current_templates[key] = value
        else:
            current_templates[key] = schema_dict.get("defaults", {}).get(key, "")

    replace_illegal = await settings_service.get(
        f"{prefix}.naming.replace_illegal_characters"
    )
    colon_replacement = await settings_service.get(f"{prefix}.naming.colon_replacement")

    current_templates["replace_illegal_characters"] = (
        replace_illegal if replace_illegal is not None else True
    )
    current_templates["colon_replacement"] = (
        colon_replacement if colon_replacement is not None else " - "
    )

    return NamingConfig(schema=schema, current=current_templates)


async def _save_naming_config(
    settings_service: SettingsService, prefix: str, naming_update: dict
):
    """Save naming configuration to database."""
    for key, value in naming_update.items():
        await settings_service.set(f"{prefix}.naming.{key}", value)


# ============================================================================
# LIBRARY PLUGINS ENDPOINT
# ============================================================================


class PluginInfo(BaseModel):
    """Information about a library plugin."""

    id: str
    name: str
    version: str
    description: str
    library_type: str
    builtin: bool = False


class LibraryTypeInfo(BaseModel):
    """Information about an available library type."""

    type: str
    label: str
    description: str | None = None
    plugin_id: str
    plugin_name: str


def _library_type_name_description(plugin_class, plugin_info, locale: str) -> tuple[str, str]:
    translations = (
        plugin_info.load_translations(locale)
        if plugin_info and hasattr(plugin_info, "load_translations")
        else None
    )
    if translations:
        name = translations.get("name") or getattr(plugin_info, "name", None)
        description = translations.get("description")
    elif plugin_info:
        name = getattr(plugin_info, "name", None)
        manifest = getattr(plugin_info, "manifest", None)
        description = getattr(manifest, "description", None)
    else:
        name = None
        description = None

    if not name:
        plugin_instance = plugin_class()
        name = plugin_instance.get_name()
        description = getattr(
            plugin_instance,
            "get_description",
            lambda: f"{name} Library",
        )()
    return name, description or f"{name} Library"


def _library_type_entries(
    *,
    request: Request,
    registered: dict,
    registry_plugins: dict,
    existing_types: set,
) -> list[LibraryTypeInfo]:
    entries = []
    locale = get_user_locale(request)
    for library_type_str, plugin_class in registered.items():
        if library_type_str in existing_types:
            logger.debug("Skipping library type %s - already exists", library_type_str)
            continue

        plugin_id = library_type_str.lower()
        plugin_info = registry_plugins.get(plugin_id)
        if registry_plugins and plugin_info is None:
            logger.debug("Skipping library type %s - no registry metadata", library_type_str)
            continue

        try:
            name, description = _library_type_name_description(
                plugin_class,
                plugin_info,
                locale,
            )
            entries.append(
                LibraryTypeInfo(
                    type=library_type_str,
                    label=name,
                    description=description,
                    plugin_id=plugin_id,
                    plugin_name=name,
                )
            )
        except Exception as e:
            logger.warning("Failed to load plugin for type %s: %s", library_type_str, e)
    return entries


@router.get("/types", response_model=list[LibraryTypeInfo])
async def list_library_types(
    request: Request,
    db: DatabaseSession,
    current_user=Depends(get_current_user),
):
    """
    List available library types from installed library plugins.
    Only returns types that don't already have an enabled library.
    Returns translated names and descriptions based on Accept-Language header.

    Returns:
        List of available library types with metadata
    """
    registry = plugin_facade.get_registry()
    registry_plugins = getattr(registry, "_plugins", {})
    registered = plugin_facade.get_registered_plugins()

    service = LibraryService(db)
    existing_libraries = await service.list_libraries(enabled_only=True)
    existing_types = {lib.type for lib in existing_libraries}

    logger.info("Found %s registered library plugins", len(registered))
    logger.info("Existing library types: %s", existing_types)

    library_types = _library_type_entries(
        request=request,
        registered=registered,
        registry_plugins=registry_plugins,
        existing_types=existing_types,
    )

    logger.info(
        "Returning %s library types (filtered from %s)",
        len(library_types), len(registered),
    )
    return library_types


@router.get("/plugins", response_model=list[PluginInfo])
async def list_library_plugins(
    request: Request,
    library_type: str | None = None,
    current_user=Depends(get_current_superuser),
):
    """
    List available library plugins with translated names and descriptions.

    Args:
        request: Request object for locale detection
        library_type: Optional filter by library type (MOVIES, SHOWS, etc.)

    Returns:
        List of available plugins with translations
    """
    plugins = []
    registry = get_registry()
    locale = get_user_locale(request)
    for plugin_id, plugin_class in get_registered_plugins().items():
        try:
            plugin_instance = plugin_class()
            plugin_lib_type = plugin_instance.get_library_type()

            # Filter by type if provided
            if library_type and plugin_lib_type.upper() != library_type.upper():
                continue

            # Get version and description with fallbacks for library plugins
            version = getattr(plugin_instance, "get_version", lambda: "1.0.0")()
            description = getattr(
                plugin_instance,
                "get_description",
                lambda pi=plugin_instance: f"{pi.get_name()} plugin",
            )()

            plugin_info = registry.get_plugin(str(plugin_id).lower())
            translations = (
                plugin_info.load_translations(locale)
                if plugin_info and hasattr(plugin_info, "load_translations")
                else None
            )
            builtin = (
                getattr(getattr(plugin_info, "manifest", None), "builtin", True)
                if plugin_info
                else True
            )
            name = (
                translations.get("name")
                if translations and translations.get("name")
                else plugin_instance.get_name()
            )
            description = (
                translations.get("description")
                if translations and translations.get("description")
                else description
            )

            plugins.append(
                PluginInfo(
                    id=plugin_id,
                    name=name,
                    version=version,
                    description=description,
                    library_type=plugin_lib_type,
                    builtin=builtin,
                )
            )
        except Exception as e:
            logger.warning("Failed to load plugin %s: %s", plugin_id, e)
            continue

    return plugins


@router.get("/metadata-providers")
async def list_metadata_providers(
    request: Request,
    library_type: str | None = None,
    db: DatabaseSession = None,
    current_user=Depends(get_current_superuser),
):
    """
    List available and enabled metadata provider plugins with translated names and descriptions.

    Args:
        request: Request object for locale detection
        library_type: Optional filter by compatible library type (MOVIES, SHOWS, GAMES, etc.)
        db: Database session

    Returns:
        List of metadata provider plugins with translations and compatibility info
    """
    from pyrate.services.metadata import METADATA_PROVIDERS, MetadataService

    metadata_service = MetadataService(db)

    metadata_providers = []
    for domain, info in METADATA_PROVIDERS.items():
        supported_types = [t.upper() for t in info["media_types"]]

        if library_type and library_type.upper() not in supported_types:
            continue

        configured = await metadata_service.is_configured(domain)
        metadata_providers.append(
            {
                "domain": domain,
                "name": info["name"],
                "version": "1.0.0",
                "description": info["description"],
                "supported_media_types": supported_types,
                "configured": configured,
                "enabled": True,
            }
        )

    return {"metadata_providers": metadata_providers}


@router.get("/plugins/{plugin_id}/ui-config", response_model=LibraryUIConfig)
async def get_library_plugin_ui_config(
    plugin_id: str,
    current_user=Depends(get_current_user),
):
    """
    Get UI configuration for a library plugin.

    Returns icons and labels that should be used in the frontend for this library type.
    """
    try:
        # Get plugin instance
        plugin_instance = get_plugin_instance(plugin_id)

        if not hasattr(plugin_instance, "get_library_icon"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plugin '{plugin_id}' is not a library plugin",
            )

        # Get UI configuration from plugin
        return LibraryUIConfig(
            library_icon=plugin_instance.get_library_icon(),
            item_icon=plugin_instance.get_item_icon(),
            play_button_icon=plugin_instance.get_play_button_icon(),
            play_button_label=plugin_instance.get_play_button_label(),
        )
    except Exception as e:
        logger.error("Error getting UI config for plugin %s: %s", plugin_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get UI configuration",
        )


# ============================================================================
# LIBRARY CRUD ENDPOINTS
# ============================================================================


@router.post("", response_model=LibraryRead, status_code=status.HTTP_201_CREATED)
async def create_library(
    library_data: LibraryCreate,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """
    Create a new library.

    Requires superuser privileges.

    Note: Only one library per type is allowed.
    """
    service = LibraryService(db)

    # Convert enum to string value if needed
    library_type = (
        library_data.type.value
        if hasattr(library_data.type, "value")
        else library_data.type
    )

    # Check if a library with this type already exists
    existing = await service.get_library_by_type(library_type)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A library of type '{library_type}' already exists: {existing.name}",
        )

    try:
        library = await service.create_library(
            name=library_data.name,
            type=library_type,
            plugin_id=library_data.plugin_id,
            path=library_data.path,
            enabled=library_data.enabled,
            settings=library_data.settings,
            description=library_data.description,
        )

        # Creator is a superuser, so no masking applies.
        return LibraryRead(**service.serialize_library(library, is_admin=True))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=list[LibraryRead])
async def list_libraries(
    db: DatabaseSession,
    enabled_only: bool = False,
    include_disabled: bool = False,
    current_user=Depends(get_current_user),
):
    """
    List all libraries.

    Query params:
    - enabled_only: If true, only return enabled libraries
    """
    service = LibraryService(db)
    # Admin-vs-user type filtering (disabled types hidden from non-admins) is
    # owned by the service so every listing endpoint shares one implementation.
    is_admin = getattr(current_user, "is_superuser", False)
    libraries = await service.list_visible_libraries(
        enabled_only=enabled_only,
        include_disabled=include_disabled,
        is_admin=is_admin,
    )

    logger.info("list_libraries: Returning %s libraries", len(libraries))

    # Response shaping incl. path/settings masking is delegated to the service
    # so non-admins never receive server filesystem paths.
    result = [
        LibraryRead(**service.serialize_library(lib, is_admin=is_admin))
        for lib in libraries
    ]

    logger.info("list_libraries: Returning %s libraries", len(result))
    if result:
        logger.info("list_libraries: First library: %s (%s)", result[0].name, result[0].type)

    return result


def _resolve_library_subpath(library_path: str, relative_path: str | None = None) -> Path:
    root = Path(library_path).expanduser().resolve()
    requested = root if not relative_path else (root / relative_path).resolve()
    if requested != root and root not in requested.parents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is outside the library root",
        )
    return requested


def _parse_library_settings(raw_settings) -> dict:
    # Settings-blob parsing lives on the service; the router keeps this thin
    # alias so the response-shaping helpers below read the same view the
    # service does.
    return LibraryService.parse_settings(raw_settings)


def _library_options_from_settings(raw_settings) -> LibraryOptions:
    settings = _parse_library_settings(raw_settings)
    raw_options = settings.get("options")
    if not isinstance(raw_options, dict):
        raw_options = {}
    return LibraryOptions(**raw_options)


def _library_folder_policy_from_settings(raw_settings) -> LibraryFolderPolicy:
    settings = _parse_library_settings(raw_settings)
    raw_policy = settings.get("folder_policy")
    if not isinstance(raw_policy, dict):
        raw_policy = {}
    return LibraryFolderPolicy(**raw_policy)


def _library_media_folder_paths(library) -> list[str]:
    # Media-folder computation/dedup is owned by the service.
    return LibraryService.media_folder_paths(library)


async def _media_folder_response(
    service: LibraryService, library
) -> LibraryMediaFoldersResponse:
    # Blocking existence/type checks are offloaded to threads inside the service.
    folders = [
        LibraryMediaFolder(**folder)
        for folder in await service.media_folder_status(library)
    ]
    return LibraryMediaFoldersResponse(
        library_guid=library.guid,
        folders=folders,
        total=len(folders),
    )


def _path_is_nested(path: Path, other: Path) -> bool:
    try:
        resolved_path = path.expanduser().resolve()
        resolved_other = other.expanduser().resolve()
    except OSError:
        resolved_path = path.expanduser().absolute()
        resolved_other = other.expanduser().absolute()
    return resolved_path != resolved_other and resolved_other in resolved_path.parents


async def _validate_library_folder_path(
    service: LibraryService,
    library,
    candidate_path: str,
) -> LibraryFolderValidationResponse:
    policy = _library_folder_policy_from_settings(library.settings)
    path_obj = Path(candidate_path).expanduser()
    normalized_path = str(path_obj)
    existing_paths = _library_media_folder_paths(library)
    primary_path = str(Path(library.path).expanduser())
    is_primary = normalized_path == primary_path
    is_duplicate = normalized_path in existing_paths

    # Blocking filesystem checks are offloaded to a thread by the service.
    probe = await service.probe_path(candidate_path)
    exists = probe["exists"]
    is_directory = probe["is_directory"]
    is_readable = probe["is_readable"]
    is_writable = probe["is_writable"]
    parent_exists = probe["parent_exists"]
    parent_writable = probe["parent_writable"]

    issues: list[str] = []
    warnings: list[str] = []
    if is_duplicate:
        issues.append("Folder is already configured for this library")
    if not policy.allow_nested_folders and not is_duplicate:
        candidate = Path(normalized_path)
        for existing_path in existing_paths:
            existing = Path(existing_path)
            if _path_is_nested(candidate, existing) or _path_is_nested(existing, candidate):
                issues.append("Nested media folders are not allowed")
                break
    if not exists and policy.require_existing_paths:
        issues.append("Folder does not exist")
    elif not exists:
        warnings.append("Folder does not exist")
    elif not is_directory:
        issues.append("Path is not a directory")
    else:
        if policy.excluded_folder_names and path_obj.name in policy.excluded_folder_names:
            issues.append("Folder name is excluded by policy")
        if policy.require_readable_paths and not is_readable:
            issues.append("Folder is not readable")
        if policy.require_writable_paths and not is_writable:
            issues.append("Folder is not writable")
        elif not is_writable:
            warnings.append("Folder is not writable")
    if not parent_exists:
        warnings.append("Parent folder does not exist")
    elif not parent_writable:
        warnings.append("Parent folder is not writable")

    return LibraryFolderValidationResponse(
        library_guid=library.guid,
        path=candidate_path,
        normalized_path=normalized_path,
        exists=exists,
        is_directory=is_directory,
        is_readable=is_readable,
        is_writable=is_writable,
        parent_exists=parent_exists,
        parent_writable=parent_writable,
        is_duplicate=is_duplicate,
        is_primary=is_primary,
        is_valid=not issues,
        issues=issues,
        warnings=warnings,
    )


@router.get("/{library_guid}/paths", response_model=LibraryPhysicalPathResponse)
async def get_library_physical_path(
    library_guid: uuid.UUID,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """Return physical path status for a library. Superuser only."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )

    root = Path(library.path).expanduser()
    return LibraryPhysicalPathResponse(
        library_guid=library.guid,
        path=str(root),
        exists=root.exists(),
        is_directory=root.is_dir(),
    )


@router.post("/{library_guid}/paths/migrate", response_model=LibraryPathMigrationResponse)
async def migrate_library_path(
    library_guid: uuid.UUID,
    body: LibraryPathMigrationRequest,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """Preview or migrate a library's primary path."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )

    previous_path = str(Path(library.path).expanduser())
    validation = await _validate_library_folder_path(service, library, body.path)
    if validation.issues:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "New library path is not valid",
                "issues": validation.issues,
                "warnings": validation.warnings,
            },
        )

    settings = _parse_library_settings(library.settings)
    raw_folders = settings.get("media_folders")
    folders = [str(path) for path in raw_folders] if isinstance(raw_folders, list) else []

    if not body.validate_only:
        if body.keep_existing_as_media_folder and previous_path not in folders:
            folders.append(previous_path)
        settings["media_folders"] = [
            folder for folder in folders if folder != validation.normalized_path
        ]
        library.path = validation.normalized_path
        # Settings persistence (mutate + commit) is centralized in the service.
        await service.replace_settings(library, settings)
        await ActivityLogService(db).create(
            ActivityLogCreate(
                event_type="library.path_migrate",
                message=f"Migrated library path for {library.name}",
                entity_type="library",
                entity_guid=library.guid,
                extra_data=json.dumps(
                    {
                        "previous_path": previous_path,
                        "new_path": validation.normalized_path,
                        "kept_existing_as_media_folder": body.keep_existing_as_media_folder,
                    },
                    sort_keys=True,
                ),
            ),
            actor_guid=current_user.guid,
        )
        folders = _library_media_folder_paths(library)[1:]

    return LibraryPathMigrationResponse(
        library_guid=library.guid,
        previous_path=previous_path,
        new_path=validation.normalized_path,
        migrated=not body.validate_only,
        validation=validation,
        media_folders=folders,
    )


@router.get("/{library_guid}/folders", response_model=LibraryFolderResponse)
async def list_library_folder(
    library_guid: uuid.UUID,
    db: DatabaseSession,
    relative_path: str | None = None,
    current_user=Depends(get_current_superuser),
):
    """List folders/files beneath a library path. Superuser only."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )

    root = Path(library.path).expanduser().resolve()
    requested = _resolve_library_subpath(library.path, relative_path)
    if not requested.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Folder not found",
        )
    if not requested.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is not a directory",
        )

    # The directory walk (iterdir/stat) is offloaded to a thread by the service.
    entries = [
        LibraryFolderEntry(**entry)
        for entry in await service.list_directory_entries(requested, root)
    ]

    return LibraryFolderResponse(
        library_guid=library.guid,
        root_path=str(root),
        relative_path=str(requested.relative_to(root)) if requested != root else "",
        entries=entries,
    )


@router.get("/{library_guid}/media-folders", response_model=LibraryMediaFoldersResponse)
async def list_library_media_folders(
    library_guid: uuid.UUID,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """List configured media folders for a library."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )
    return await _media_folder_response(service, library)


@router.get("/{library_guid}/folder-policy", response_model=LibraryFolderPolicy)
async def get_library_folder_policy(
    library_guid: uuid.UUID,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """Return folder validation policy for a library."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )
    return _library_folder_policy_from_settings(library.settings)


@router.put("/{library_guid}/folder-policy", response_model=LibraryFolderPolicy)
async def update_library_folder_policy(
    library_guid: uuid.UUID,
    policy: LibraryFolderPolicy,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """Update folder validation policy for a library."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )

    settings = _parse_library_settings(library.settings)
    settings["folder_policy"] = policy.model_dump()
    await service.replace_settings(library, settings)
    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="library.folder_policy_update",
            message=f"Updated folder policy for library {library.name}",
            entity_type="library",
            entity_guid=library.guid,
            extra_data=json.dumps(policy.model_dump(), sort_keys=True),
        ),
        actor_guid=current_user.guid,
    )
    return _library_folder_policy_from_settings(library.settings)


@router.post(
    "/{library_guid}/media-folders/validate",
    response_model=LibraryFolderValidationResponse,
)
async def validate_library_media_folder(
    library_guid: uuid.UUID,
    body: LibraryFolderValidationRequest,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """Validate a candidate media folder before attaching it to a library."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )
    return await _validate_library_folder_path(service, library, body.path)


@router.post("/{library_guid}/media-folders", response_model=LibraryMediaFoldersResponse)
async def add_library_media_folder(
    library_guid: uuid.UUID,
    body: LibraryMediaFolderAdd,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """Attach an additional media folder path to a library."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )

    new_path = str(Path(body.path).expanduser())
    if new_path == str(Path(library.path).expanduser()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Folder is already the primary library path",
        )
    settings = _parse_library_settings(library.settings)
    raw_folders = settings.get("media_folders")
    folders = [str(path) for path in raw_folders] if isinstance(raw_folders, list) else []
    if new_path not in folders:
        folders.append(new_path)
    settings["media_folders"] = folders
    await service.replace_settings(library, settings)
    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="library.media_folder_add",
            message=f"Added media folder to library {library.name}",
            entity_type="library",
            entity_guid=library.guid,
            extra_data=json.dumps({"path": new_path}, sort_keys=True),
        ),
        actor_guid=current_user.guid,
    )
    return await _media_folder_response(service, library)


@router.delete("/{library_guid}/media-folders", response_model=LibraryMediaFoldersResponse)
async def remove_library_media_folder(
    library_guid: uuid.UUID,
    path: str,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """Detach an additional media folder path from a library."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )

    remove_path = str(Path(path).expanduser())
    if remove_path == str(Path(library.path).expanduser()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the primary library path",
        )
    settings = _parse_library_settings(library.settings)
    raw_folders = settings.get("media_folders")
    folders = [str(item) for item in raw_folders] if isinstance(raw_folders, list) else []
    if remove_path not in folders:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media folder not found",
        )
    settings["media_folders"] = [folder for folder in folders if folder != remove_path]
    await service.replace_settings(library, settings)
    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="library.media_folder_remove",
            message=f"Removed media folder from library {library.name}",
            entity_type="library",
            entity_guid=library.guid,
            extra_data=json.dumps({"path": remove_path}, sort_keys=True),
        ),
        actor_guid=current_user.guid,
    )
    return await _media_folder_response(service, library)


@router.get("/{library_guid}/options", response_model=LibraryOptions)
async def get_library_options(
    library_guid: uuid.UUID,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """Return per-library metadata/image/subtitle/trickplay options."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )
    return _library_options_from_settings(library.settings)


@router.put("/{library_guid}/options", response_model=LibraryOptions)
async def update_library_options(
    library_guid: uuid.UUID,
    options: LibraryOptions,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """Update per-library metadata/image/subtitle/trickplay options."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )

    settings = _parse_library_settings(library.settings)
    settings["options"] = options.model_dump()
    await service.replace_settings(library, settings)
    return _library_options_from_settings(library.settings)


async def _run_library_scan(
    library_guid: uuid.UUID,
    body: LibraryScanRequest,
    db: DatabaseSession,
    current_user,
    *,
    event_type: str,
    status_value: str,
) -> LibraryScanResponse:
    service = LibraryService(db)
    library = await service.get_library(library_guid)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )

    try:
        discovered = await service.scan_library_for_media(library_guid)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type=event_type,
            message=f"{status_value.title()} library {library.name}; discovered {len(discovered)} files",
            entity_type="library",
            entity_guid=library.guid,
            extra_data=json.dumps(
                {
                    "library_type": library.type,
                    "path": library.path,
                    "discovered_count": len(discovered),
                    "status": status_value,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )
    return LibraryScanResponse(
        library_guid=library.guid,
        status=status_value,
        discovered_count=len(discovered),
        files=discovered[: body.max_files] if body.include_files else [],
    )


@router.post("/{library_guid}/scan", response_model=LibraryScanResponse)
async def scan_library(
    library_guid: uuid.UUID,
    db: DatabaseSession,
    body: LibraryScanRequest | None = None,
    current_user=Depends(get_current_superuser),
):
    """Scan one library path with its registered plugin. Superuser only."""
    return await _run_library_scan(
        library_guid,
        body or LibraryScanRequest(),
        db,
        current_user,
        event_type="library.scan",
        status_value="scanned",
    )


@router.post("/{library_guid}/refresh", response_model=LibraryScanResponse)
async def refresh_library(
    library_guid: uuid.UUID,
    db: DatabaseSession,
    body: LibraryScanRequest | None = None,
    current_user=Depends(get_current_superuser),
):
    """Refresh one library by rescanning its path. Superuser only."""
    return await _run_library_scan(
        library_guid,
        body or LibraryScanRequest(),
        db,
        current_user,
        event_type="library.refresh",
        status_value="refreshed",
    )


@router.get("/{library_guid}", response_model=LibraryRead)
async def get_library(
    library_guid: uuid.UUID,
    db: DatabaseSession,
    current_user=Depends(get_current_user),
):
    """Get a specific library by GUID."""
    service = LibraryService(db)
    library = await service.get_library(library_guid)

    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )

    # Mask filesystem path/settings for non-admins, mirroring list_libraries.
    is_admin = getattr(current_user, "is_superuser", False)
    return LibraryRead(**service.serialize_library(library, is_admin=is_admin))


@router.put("/{library_guid}", response_model=LibraryRead)
async def update_library(
    library_guid: uuid.UUID,
    library_data: LibraryUpdate,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """
    Update a library.

    Requires superuser privileges.
    """
    service = LibraryService(db)

    try:
        library = await service.update_library(
            library_guid=library_guid,
            name=library_data.name,
            path=library_data.path,
            enabled=library_data.enabled,
            settings=library_data.settings,
            description=library_data.description,
        )

        if not library:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
            )

        # Updater is a superuser, so no masking applies.
        return LibraryRead(**service.serialize_library(library, is_admin=True))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{library_guid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library(
    library_guid: uuid.UUID,
    db: DatabaseSession,
    current_user=Depends(get_current_superuser),
):
    """
    Delete a library.

    Requires superuser privileges.
    """
    service = LibraryService(db)
    success = await service.delete_library(library_guid)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library not found"
        )


# ============================================================================
# LIBRARY TYPE CONFIGURATION ENDPOINTS
# ============================================================================


# MOVIES LIBRARY CONFIG
@router.get("/movies/config", response_model=MovieLibraryConfig)
async def get_movie_library_config(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get complete movie library configuration."""
    settings_service = SettingsService(session)

    library_path = await settings_service.get("plugin.movies.library_path")
    enable_library = await settings_service.get("plugin.movies.enable_library")
    enable_on_demand = await settings_service.get(
        "plugin.movies.enable_on_demand_downloads"
    )
    allowed_languages = await settings_service.get(
        "plugin.movies.allowed_languages", []
    )

    movie_plugin = get_plugin_instance("MOVIES")
    naming_config = await _load_naming_config(
        settings_service, movie_plugin, "plugin.movies"
    )

    return MovieLibraryConfig(
        library_path=library_path or "/library/movies",
        enable_library=enable_library if enable_library is not None else False,
        enable_on_demand_downloads=enable_on_demand
        if enable_on_demand is not None
        else False,
        naming=naming_config,
        allowed_languages=allowed_languages
        if isinstance(allowed_languages, list)
        else [],
    )


@router.put("/movies/config", response_model=MovieLibraryConfig)
async def update_movie_library_config(
    update: MovieLibraryUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update movie library configuration."""
    settings_service = SettingsService(session)

    await LibraryConfigService(session).write_type_settings(
        "plugin.movies",
        {
            "library_path": update.library_path,
            "enable_library": update.enable_library,
            "enable_on_demand_downloads": update.enable_on_demand_downloads,
            "allowed_languages": update.allowed_languages,
        },
    )

    if update.naming:
        await _save_naming_config(settings_service, "plugin.movies", update.naming)

    return await get_movie_library_config(session, current_user)


@router.post("/movies/preview-naming", response_model=NamingPreviewResponse)
async def preview_movie_naming(
    naming_templates: dict[str, str | bool],
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Preview movie naming."""
    movie_plugin = get_plugin_instance("MOVIES")

    sample_media_info = {
        "title": "The Matrix",
        "year": 1999,
        "tmdb_id": 603,
        "imdb_id": "tt0133093",
    }

    sample_probe_data = {
        "resolution": "1080p",
        "video_codec": "x264",
        "audio_codec": "DTS",
        "audio_channels": "5.1",
        "hdr_format": None,
    }

    folder_template = naming_templates.get("folder")
    file_template = naming_templates.get("file")

    folder = movie_plugin.suggest_folder_name(
        sample_media_info, template=folder_template, tmdb_id=603
    )

    file_name = movie_plugin.suggest_file_name(
        sample_media_info,
        template=file_template,
        probe_data=sample_probe_data,
        release_group="SPARKS",
    )

    full_path = f"{folder}/{file_name}.mkv" if folder and file_name else None

    return NamingPreviewResponse(folder=folder, file=file_name, full_path=full_path)


# SHOWS LIBRARY
@router.get("/shows/config", response_model=ShowLibraryConfig)
async def get_show_library_config(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get complete show library configuration."""
    settings_service = SettingsService(session)

    library_path = await settings_service.get("plugin.shows.library_path")
    enable_library = await settings_service.get("plugin.shows.enable_library")
    enable_on_demand = await settings_service.get(
        "plugin.shows.enable_on_demand_downloads"
    )
    enable_prefetch = await settings_service.get(
        "plugin.shows.enable_prefetch_downloads"
    )
    hide_season_zero = await settings_service.get("plugin.shows.hide_season_zero")
    allowed_languages = await settings_service.get("plugin.shows.allowed_languages", [])

    show_plugin = get_plugin_instance("SHOWS")
    naming_config = await _load_naming_config(
        settings_service, show_plugin, "plugin.shows"
    )

    return ShowLibraryConfig(
        library_path=library_path or "/library/shows",
        enable_library=enable_library if enable_library is not None else False,
        enable_on_demand_downloads=enable_on_demand
        if enable_on_demand is not None
        else False,
        enable_prefetch_downloads=enable_prefetch
        if enable_prefetch is not None
        else False,
        hide_season_zero=hide_season_zero if hide_season_zero is not None else True,
        naming=naming_config,
        allowed_languages=allowed_languages
        if isinstance(allowed_languages, list)
        else [],
    )


@router.put("/shows/config", response_model=ShowLibraryConfig)
async def update_show_library_config(
    update: ShowLibraryUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update show library configuration."""
    settings_service = SettingsService(session)

    await LibraryConfigService(session).write_type_settings(
        "plugin.shows",
        {
            "library_path": update.library_path,
            "enable_library": update.enable_library,
            "enable_on_demand_downloads": update.enable_on_demand_downloads,
            "enable_prefetch_downloads": update.enable_prefetch_downloads,
            "hide_season_zero": update.hide_season_zero,
            "allowed_languages": update.allowed_languages,
        },
    )

    if update.naming:
        await _save_naming_config(settings_service, "plugin.shows", update.naming)

    return await get_show_library_config(session, current_user)


@router.post("/shows/preview-naming", response_model=NamingPreviewResponse)
async def preview_show_naming(
    naming_templates: dict[str, str | bool],
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Preview show naming."""
    show_plugin = get_plugin_instance("SHOWS")

    sample_media_info = {
        "show_title": "Breaking Bad",
        "year": 2008,
        "tvdb_id": 81189,
        "season": 1,
        "episode": 1,
        "episode_title": "Pilot",
    }

    sample_probe_data = {
        "resolution": "1080p",
        "video_codec": "x265",
        "audio_codec": "AAC",
        "audio_channels": "2.0",
        "hdr_format": None,
    }

    folder_template = naming_templates.get("folder") or naming_templates.get(
        "series_folder"
    )
    season_folder_template = naming_templates.get("season_folder")
    file_template = naming_templates.get("file")

    folder = show_plugin.suggest_folder_name(
        sample_media_info, template=folder_template, tvdb_id=81189
    )

    season_folder = (
        season_folder_template.format(season=1, season_2="01")
        if season_folder_template
        else "Season 01"
    )

    file_name = show_plugin.suggest_file_name(
        sample_media_info,
        template=file_template,
        probe_data=sample_probe_data,
        release_group="DEFLATE",
    )

    full_path = (
        f"{folder}/{season_folder}/{file_name}.mkv"
        if folder and season_folder and file_name
        else None
    )

    return NamingPreviewResponse(
        folder=folder, season_folder=season_folder, file=file_name, full_path=full_path
    )


# ============================================================================
# GENERIC LIBRARY CONFIG (games, music, books, audiobooks, etc.)
# ============================================================================

# Set of library types that have dedicated endpoints above
_DEDICATED_CONFIG_TYPES = {"movies", "shows"}


def _require_plugin(library_type: str):
    """Return the plugin instance for ``library_type`` or raise 404."""
    try:
        return get_plugin_instance(library_type.upper())
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No library plugin found for type '{library_type}'",
        )


@router.get("/{library_type}/config", response_model=SimpleLibraryConfig)
async def get_generic_library_config(
    library_type: str,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get configuration for a simple library type (games, music, books, audiobooks, etc.)."""
    library_type_lower = library_type.lower()

    if library_type_lower in _DEDICATED_CONFIG_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Use the dedicated /{library_type_lower}/config endpoint instead",
        )

    plugin_instance = _require_plugin(library_type)

    settings_service = SettingsService(session)
    prefix = f"plugin.{library_type_lower}"

    library_path = await settings_service.get(f"{prefix}.library_path")
    enable_library = await settings_service.get(f"{prefix}.enable_library")
    enable_on_demand = await settings_service.get(
        f"{prefix}.enable_on_demand_downloads"
    )

    default_path = f"/library/{library_type_lower}"
    if hasattr(plugin_instance, "get_default_path"):
        maybe_default_path = plugin_instance.get_default_path()
        default_path = (
            await maybe_default_path
            if inspect.isawaitable(maybe_default_path)
            else maybe_default_path
        )

    naming_config = await _load_naming_config(settings_service, plugin_instance, prefix)

    return SimpleLibraryConfig(
        library_path=library_path or default_path,
        enable_library=enable_library if enable_library is not None else True,
        enable_on_demand_downloads=enable_on_demand
        if enable_on_demand is not None
        else False,
        naming=naming_config,
    )


@router.put("/{library_type}/config", response_model=SimpleLibraryConfig)
async def update_generic_library_config(
    library_type: str,
    update: SimpleLibraryUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update configuration for a simple library type."""
    library_type_lower = library_type.lower()

    if library_type_lower in _DEDICATED_CONFIG_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Use the dedicated /{library_type_lower}/config endpoint instead",
        )

    _require_plugin(library_type)

    settings_service = SettingsService(session)
    prefix = f"plugin.{library_type_lower}"

    await LibraryConfigService(session).write_type_settings(
        prefix,
        {
            "library_path": update.library_path,
            "enable_library": update.enable_library,
            "enable_on_demand_downloads": update.enable_on_demand_downloads,
        },
    )

    if update.naming:
        await _save_naming_config(settings_service, prefix, update.naming)

    return await get_generic_library_config(library_type, session, current_user)


@router.post("/{library_type}/preview-naming", response_model=NamingPreviewResponse)
async def preview_generic_naming(
    library_type: str,
    naming_templates: dict[str, str | bool],
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Preview naming for a simple library type."""
    library_type_lower = library_type.lower()

    if library_type_lower in _DEDICATED_CONFIG_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Use the dedicated /{library_type_lower}/preview-naming endpoint instead",
        )

    plugin_instance = _require_plugin(library_type)

    sample_media_info = {
        "title": "Sample Title",
        "year": 2024,
    }

    folder_template = naming_templates.get("folder")
    file_template = naming_templates.get("file")

    folder = plugin_instance.suggest_folder_name(
        sample_media_info, template=folder_template
    )

    file_name = plugin_instance.suggest_file_name(
        sample_media_info, template=file_template
    )

    full_path = f"{folder}/{file_name}" if folder and file_name else None

    return NamingPreviewResponse(folder=folder, file=file_name, full_path=full_path)


# ============================================================================
# SCORING CONFIGURATION ENDPOINTS
# ============================================================================

_SCORING_CONFIG_KEYS: dict[str, str] = {
    "movies": "scoring.config.movies",
    "shows": "scoring.config.shows",
}


@router.get("/movies/scoring")
async def get_movie_scoring_config(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get scoring configuration for movies (admin only)."""
    settings_service = SettingsService(session)
    raw = await settings_service.get(_SCORING_CONFIG_KEYS["movies"], None)
    if raw is None:
        return MovieScoringConfig().model_dump(by_alias=True)
    try:
        return MovieScoringConfig.model_validate(raw).model_dump(by_alias=True)
    except Exception:
        return MovieScoringConfig().model_dump(by_alias=True)


@router.put("/movies/scoring")
async def update_movie_scoring_config(
    config_data: dict,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update scoring configuration for movies (admin only)."""
    try:
        config = MovieScoringConfig.model_validate(config_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        )
    settings_service = SettingsService(session)
    await settings_service.set(
        _SCORING_CONFIG_KEYS["movies"], config.model_dump(by_alias=True)
    )
    return config.model_dump(by_alias=True)


@router.post("/movies/scoring/reset")
async def reset_movie_scoring_config(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Reset movie scoring configuration to defaults (admin only)."""
    config = MovieScoringConfig()
    settings_service = SettingsService(session)
    await settings_service.set(
        _SCORING_CONFIG_KEYS["movies"], config.model_dump(by_alias=True)
    )
    return config.model_dump(by_alias=True)


@router.get("/shows/scoring")
async def get_show_scoring_config(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get scoring configuration for shows (admin only)."""
    settings_service = SettingsService(session)
    raw = await settings_service.get(_SCORING_CONFIG_KEYS["shows"], None)
    if raw is None:
        return ShowScoringConfig().model_dump(by_alias=True)
    try:
        return ShowScoringConfig.model_validate(raw).model_dump(by_alias=True)
    except Exception:
        return ShowScoringConfig().model_dump(by_alias=True)


@router.put("/shows/scoring")
async def update_show_scoring_config(
    config_data: dict,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Update scoring configuration for shows (admin only)."""
    try:
        config = ShowScoringConfig.model_validate(config_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        )
    settings_service = SettingsService(session)
    await settings_service.set(
        _SCORING_CONFIG_KEYS["shows"], config.model_dump(by_alias=True)
    )
    return config.model_dump(by_alias=True)


@router.post("/shows/scoring/reset")
async def reset_show_scoring_config(
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Reset show scoring configuration to defaults (admin only)."""
    config = ShowScoringConfig()
    settings_service = SettingsService(session)
    await settings_service.set(
        _SCORING_CONFIG_KEYS["shows"], config.model_dump(by_alias=True)
    )
    return config.model_dump(by_alias=True)


# ============================================================================
# QUALITY PROFILE ENDPOINTS (Sonarr-style ordered list + cutoff)
#
# One profile per media type + an optional "favorites" variant. Favorites
# fall back to the standard profile, which falls back to a built-in default.
# Legacy /scoring endpoints above are preserved (they feed the additive
# within-rung tiebreaker via QualityProfile.scoring).
# ============================================================================

# profile type segment -> representative MediaType name for ladder/default
_PROFILE_TYPE_MEDIA = {
    "movies": "MOVIES",
    "shows": "SHOWS",
    "music": "MUSIC",
    "books": "BOOKS",
    "games": "GAMES",
}


def _validate_profile_type(profile_type: str) -> str:
    if profile_type not in _PROFILE_TYPE_MEDIA:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown quality profile type '{profile_type}'",
        )
    return profile_type


@router.get("/quality-profiles/{profile_type}/qualities")
async def list_profile_qualities(
    profile_type: str,
    current_user=Depends(get_current_superuser),
):
    """Canonical ordered quality ladder for a profile type (for the UI)."""
    from pyrate.libraries.quality import qualities_for_media_type

    _validate_profile_type(profile_type)
    media_type = _PROFILE_TYPE_MEDIA[profile_type]
    return [
        {"id": d.id, "label": d.label, "kind": d.kind.value}
        for d in qualities_for_media_type(media_type)
    ]


@router.get("/quality-profiles/{profile_type}")
async def get_quality_profile(
    profile_type: str,
    favorites: bool = False,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Get the stored quality profile (or the built-in default)."""
    from pyrate.services.quality_profile import (
        QualityProfileService,
        default_profile,
    )

    _validate_profile_type(profile_type)
    svc = QualityProfileService(session)
    settings_service = SettingsService(session)
    raw = await settings_service.get(
        svc.settings_key(profile_type, favorites=favorites), None
    )
    if raw is None:
        return default_profile(
            _PROFILE_TYPE_MEDIA[profile_type]
        ).model_dump()
    try:
        return QualityProfile.model_validate(raw).model_dump()
    except Exception:
        return default_profile(
            _PROFILE_TYPE_MEDIA[profile_type]
        ).model_dump()


@router.put("/quality-profiles/{profile_type}")
async def update_quality_profile(
    profile_type: str,
    config_data: dict,
    favorites: bool = False,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Create/update a quality profile (admin only)."""
    from pyrate.services.quality_profile import QualityProfileService

    _validate_profile_type(profile_type)
    try:
        profile = QualityProfile.model_validate(config_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        )
    svc = QualityProfileService(session)
    settings_service = SettingsService(session)
    await settings_service.set(
        svc.settings_key(profile_type, favorites=favorites),
        profile.model_dump(),
    )
    return profile.model_dump()


@router.post("/quality-profiles/{profile_type}/reset")
async def reset_quality_profile(
    profile_type: str,
    favorites: bool = False,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(get_current_superuser),
):
    """Reset a quality profile to the built-in default (admin only).

    For the favorites variant this clears the override so it falls back to
    the standard profile.
    """
    from pyrate.services.quality_profile import (
        QualityProfileService,
        default_profile,
    )

    _validate_profile_type(profile_type)
    svc = QualityProfileService(session)
    settings_service = SettingsService(session)
    key = svc.settings_key(profile_type, favorites=favorites)
    if favorites:
        # Clearing the favorites override = fall back to the standard profile.
        await settings_service.delete(key)
        return {"cleared": True}
    profile = default_profile(_PROFILE_TYPE_MEDIA[profile_type])
    await settings_service.set(key, profile.model_dump())
    return profile.model_dump()


# ============================================================================
# TRENDING IMPORT ENDPOINT
# ============================================================================


@router.post("/{library_guid}/import-trending", status_code=status.HTTP_202_ACCEPTED)
async def import_trending_items(
    library_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: User = Depends(get_current_superuser),
) -> dict:
    """Import trending items from the library's metadata provider."""
    try:
        return await LibraryImportService(
            db,
            genre_importer=import_genres_for_media,
        ).import_trending_items(library_guid)
    except LibraryImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# ============================================================================
# IMPORT BY EXTERNAL ID
# ============================================================================


class ImportByExternalIdRequest(BaseModel):
    """Request model for importing media by external ID (TMDB only)."""

    tmdb_id: str


class ImportByExternalIdResponse(BaseModel):
    """Response model for import by external ID."""

    status: str
    message: str
    media_item_guid: uuid.UUID | None = None
    already_existed: bool = False


@router.post(
    "/{library_guid}/import-by-external-id", status_code=status.HTTP_201_CREATED
)
async def import_by_external_id(
    library_guid: uuid.UUID,
    request: ImportByExternalIdRequest,
    db: DatabaseSession,
    current_user: User = Depends(get_current_superuser),
) -> ImportByExternalIdResponse:
    """Import a media item into the library by TMDB ID."""
    try:
        result = await LibraryImportService(
            db,
            genre_importer=import_genres_for_media,
        ).import_by_external_id(
            library_guid=library_guid,
            tmdb_id=request.tmdb_id,
        )
    except LibraryImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return ImportByExternalIdResponse(
        status=result.status,
        message=result.message,
        media_item_guid=result.media_item_guid,
        already_existed=result.already_existed,
    )


async def import_genres_for_media(
    db: AsyncSession,
    media_item_guid: uuid.UUID,
    genre_data: list,
) -> None:
    """Compatibility wrapper for older tests and imports."""
    await LibraryImportService(db).import_genres_for_media(media_item_guid, genre_data)


async def import_show_seasons_and_episodes(
    db: AsyncSession,
    media_service,
    metadata_plugin,
    show_item,
    show_external_id: str,
    library_guid: uuid.UUID,
) -> None:
    """Compatibility wrapper for older tests and imports."""
    await LibraryImportService(db).import_show_seasons_and_episodes(
        media_service=media_service,
        metadata_plugin=metadata_plugin,
        show_item=show_item,
        show_external_id=show_external_id,
        library_guid=library_guid,
    )
