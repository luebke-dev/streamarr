"""Library service for managing media libraries and unified media operations."""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, cast, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamarr.libraries import get_registered_plugins
from streamarr.models.library import Library
from streamarr.models.media import (
    AvailabilityStatus,
    MediaExternalId,
    MediaFile,
    MediaItem,
    MediaRelease,
    MediaType,
)
from streamarr.services.media import MediaService
from streamarr.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Full eager-load for detail pages that read files/releases/external_ids.
# Public so other services (api/v1/media.py, api/v1/users.py, worker.py)
# can import the same shape instead of redefining selectinload chains.
MEDIA_ITEM_LOAD_OPTIONS = (
    selectinload(MediaItem.genres),
    selectinload(MediaItem.platforms),
    selectinload(MediaItem.files),
    selectinload(MediaItem.releases).selectinload(MediaRelease.links),
    selectinload(MediaItem.external_ids),
)

# Slim eager-load for list endpoints that serialize MediaItemSummary
# (needs genres + platforms, skips files/releases/external_ids).
MEDIA_ITEM_SLIM_LOAD_OPTIONS = (
    selectinload(MediaItem.genres),
    selectinload(MediaItem.platforms),
)

# Internal aliases so the existing private references inside this file
# keep working without a sweeping per-line rename.
_MEDIA_ITEM_LOAD_OPTIONS = MEDIA_ITEM_LOAD_OPTIONS
_MEDIA_ITEM_SLIM_LOAD_OPTIONS = MEDIA_ITEM_SLIM_LOAD_OPTIONS


def _combined_int_filters(
    single_value: int | None,
    values: list[int] | None,
) -> list[int]:
    combined: list[int] = []
    if single_value is not None:
        combined.append(single_value)
    if values:
        combined.extend(value for value in values if value is not None)
    return sorted(set(combined))


def _clean_int_values(values: list[int] | None) -> list[int]:
    if not values:
        return []
    return sorted({value for value in values if value is not None})


def _clean_lower_values(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return sorted({value.strip().lower() for value in values if value.strip()})


def _probe_folder_path(path_str: str) -> dict[str, Any]:
    """Blocking filesystem probe for a single path.

    Runs the ``exists``/``is_dir``/``os.access`` syscalls off the event loop
    (via ``asyncio.to_thread``) so a slow mount does not stall the worker.
    """
    path_obj = Path(path_str).expanduser()
    exists = path_obj.exists()
    is_directory = path_obj.is_dir()
    parent = path_obj.parent
    parent_exists = parent.exists()
    return {
        "name": path_obj.name,
        "exists": exists,
        "is_directory": is_directory,
        "is_readable": exists and is_directory and os.access(path_obj, os.R_OK),
        "is_writable": exists and is_directory and os.access(path_obj, os.W_OK),
        "parent_exists": parent_exists,
        "parent_writable": parent_exists and os.access(parent, os.W_OK),
    }


def _list_directory_entries(directory: str, root: str) -> list[dict[str, Any]]:
    """Blocking directory walk used by the library folder browser.

    Returns plain dicts; the router turns them into response models. Runs off
    the event loop via ``asyncio.to_thread``.
    """
    root_path = Path(root)
    entries: list[dict[str, Any]] = []
    for child in sorted(
        Path(directory).iterdir(),
        key=lambda path: (not path.is_dir(), path.name.lower()),
    ):
        try:
            stat = child.stat()
        except OSError:
            continue
        is_directory = child.is_dir()
        entries.append(
            {
                "name": child.name,
                "relative_path": str(child.relative_to(root_path)),
                "path": str(child),
                "is_directory": is_directory,
                "size_bytes": None if is_directory else stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )
    return entries


class LibraryService:
    """Service for managing media libraries."""

    def __init__(self, db: AsyncSession):
        self.db = db
        # Store plugin classes, not instances (instantiate on demand)
        self._plugin_classes = {}
        for library_type_str, plugin_class in get_registered_plugins().items():
            self._plugin_classes[library_type_str] = plugin_class
        # Lazily-created shared MediaService (same session) so the unified
        # media operations below delegate to a single canonical implementation
        # instead of duplicating create/read/delete logic.
        self._media_service: MediaService | None = None

    @property
    def media(self) -> MediaService:
        """Shared MediaService bound to the same session (canonical impl)."""
        if self._media_service is None:
            self._media_service = MediaService(self.db)
        return self._media_service

    def get_plugin(self, library_type: str, config: dict | None = None):
        """Get the plugin instance for a specific library type.

        Args:
            library_type: Library type string (e.g., 'MOVIES', 'SHOWS', 'AUDIOBOOKS')
            config: Optional plugin configuration

        Returns:
            Plugin instance for the library type, or None if not found
        """
        plugin_class = self._plugin_classes.get(library_type)
        if not plugin_class:
            return None

        # Return an instance of the plugin class
        return plugin_class()

    async def create_library(
        self,
        name: str,
        type: str,  # Changed from LibraryType enum to string
        plugin_id: str,
        path: str | None = None,
        enabled: bool = True,
        settings: dict | None = None,
        description: str | None = None,
    ) -> Library:
        """
        Create a new library.

        Args:
            name: Library name
            type: Library type
            plugin_id: Plugin identifier
            path: Library path (defaults to plugin default)
            enabled: Whether library is enabled
            settings: Library-specific settings
            description: Optional description

        Returns:
            The created library
        """
        plugin = self.get_plugin(type)
        if not plugin:
            raise ValueError(f"No plugin found for library type: {type}")

        # Use default path if not provided
        if not path:
            path = await plugin.get_default_path()

        # Validate path
        if not await plugin.validate_path(path):
            raise ValueError(f"Invalid library path: {path}")

        # Create library directory if it doesn't exist
        await plugin.initialize_library(path)

        library = Library(
            guid=uuid.uuid4(),
            name=name,
            type=type,
            plugin_id=plugin_id,
            path=path,
            enabled=enabled,
            settings=json.dumps(settings) if settings else None,
            description=description,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        self.db.add(library)
        await self.db.commit()
        await self.db.refresh(library)

        logger.info("Created library: %s (%s) at %s", name, type, path)
        return library

    async def get_library(self, library_guid: uuid.UUID) -> Library | None:
        """Get a library by GUID."""
        result = await self.db.execute(
            select(Library).where(Library.guid == library_guid)
        )
        return result.scalar_one_or_none()

    async def get_library_by_type(self, library_type: str) -> Library | None:
        """Get the first enabled library of a specific type.

        Args:
            library_type: Library type string (e.g., 'MOVIES', 'SHOWS', 'AUDIOBOOKS')
        """
        result = await self.db.execute(
            select(Library)
            .where(Library.type == library_type, Library.enabled)
            .order_by(Library.created_at)
            .limit(1)
        )
        return result.scalars().first()

    async def list_libraries(self, enabled_only: bool = False) -> list[Library]:
        """List all libraries."""
        query = select(Library)
        if enabled_only:
            query = query.where(Library.enabled)
        query = query.order_by(Library.created_at)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_library(
        self,
        library_guid: uuid.UUID,
        name: str | None = None,
        path: str | None = None,
        enabled: bool | None = None,
        settings: dict | None = None,
        description: str | None = None,
    ) -> Library | None:
        """Update a library."""
        library = await self.get_library(library_guid)
        if not library:
            return None

        # Validate new path if provided
        if path and path != library.path:
            plugin = self.get_plugin(library.type)
            if plugin and not await plugin.validate_path(path):
                raise ValueError(f"Invalid library path: {path}")
            library.path = path

        if name is not None:
            library.name = name
        if enabled is not None:
            library.enabled = enabled
        if settings is not None:
            library.settings = json.dumps(settings)
        if description is not None:
            library.description = description

        library.updated_at = datetime.now(UTC)

        await self.db.commit()
        await self.db.refresh(library)

        logger.info("Updated library: %s (%s)", library.name, library.type)
        return library

    async def delete_library(self, library_guid: uuid.UUID) -> bool:
        """Delete a library."""
        library = await self.get_library(library_guid)
        if not library:
            return False

        await self.db.delete(library)
        await self.db.commit()

        logger.info("Deleted library: %s (%s)", library.name, library.type)
        return True

    async def get_library_stats(self, library_guid: uuid.UUID) -> dict | None:
        """Get statistics for a library."""
        library = await self.get_library(library_guid)
        if not library:
            return None

        plugin = self.get_plugin(library.type)
        if not plugin:
            return None

        stats = await plugin.get_library_stats(library.path)
        stats["library_name"] = library.name
        stats["library_type"] = library.type
        stats["enabled"] = library.enabled

        return stats

    async def initialize_default_libraries(self) -> list[Library]:
        """
        Initialize default libraries for all types if they don't exist.

        Returns:
            List of created libraries
        """
        created = []

        for lib_type, plugin_class in self._plugin_classes.items():
            # Check if library of this type already exists
            existing = await self.get_library_by_type(lib_type)
            if existing:
                logger.info("Library for %s already exists: %s", lib_type, existing.name)
                continue

            plugin = plugin_class()
            # Create default library
            try:
                default_path = await plugin.get_default_path()
                library = await self.create_library(
                    name=f"Default {plugin.get_name()}",
                    type=lib_type,
                    plugin_id=lib_type.lower(),
                    path=default_path,
                    enabled=True,
                    description=f"Default {plugin.get_name().lower()} storage",
                )
                created.append(library)
                logger.info("Created default library for %s", lib_type)
            except Exception as e:
                logger.error("Failed to create default library for %s: %s", lib_type, e)

        return created

    # ==================== Library settings / serialization ====================

    @staticmethod
    def parse_settings(raw_settings: Any) -> dict:
        """Parse a library's ``settings`` blob (dict or JSON string) into a dict."""
        if not raw_settings:
            return {}
        if isinstance(raw_settings, dict):
            return dict(raw_settings)
        if isinstance(raw_settings, str):
            try:
                parsed = json.loads(raw_settings)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def media_folder_paths(library: Library) -> list[str]:
        """Return the primary path plus configured media folders, de-duplicated."""
        settings = LibraryService.parse_settings(library.settings)
        raw_paths = settings.get("media_folders")
        paths = [str(library.path)]
        if isinstance(raw_paths, list):
            paths.extend(str(path) for path in raw_paths if path)
        deduped: list[str] = []
        seen: set[str] = set()
        for path in paths:
            normalized = str(Path(path).expanduser())
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def serialize_library(library: Library, *, is_admin: bool) -> dict:
        """Serialize a library to a response dict.

        Filesystem ``path`` and the raw ``settings`` blob are only exposed to
        admins; non-admins get ``None`` for both. Centralizing this here keeps
        the authorization masking identical across every endpoint that returns
        a library.
        """
        lib_type = (
            library.type.value if hasattr(library.type, "value") else str(library.type)
        )
        return {
            "guid": library.guid,
            "name": library.name,
            "type": lib_type,
            "plugin_id": library.plugin_id,
            "path": library.path if is_admin else None,
            "enabled": library.enabled,
            "settings": library.settings if is_admin else None,
            "description": library.description,
            "created_at": library.created_at.isoformat(),
            "updated_at": library.updated_at.isoformat(),
        }

    async def list_visible_libraries(
        self,
        *,
        enabled_only: bool = False,
        include_disabled: bool = False,
        is_admin: bool = False,
    ) -> list[Library]:
        """List libraries, filtering out admin-disabled types for non-admins.

        A library type is hidden when ``plugin.<type>.enable_library`` is false,
        unless an admin explicitly requests ``include_disabled``.
        """
        libraries = await self.list_libraries(enabled_only=enabled_only)
        if include_disabled and is_admin:
            return libraries

        settings_service = SettingsService(self.db)
        type_enabled_cache: dict[str, bool] = {}
        filtered: list[Library] = []
        for lib in libraries:
            lib_type = (
                lib.type.value if hasattr(lib.type, "value") else str(lib.type)
            ).lower()
            if lib_type not in type_enabled_cache:
                type_enabled_cache[lib_type] = await settings_service.get(
                    f"plugin.{lib_type}.enable_library", True
                )
            if type_enabled_cache[lib_type]:
                filtered.append(lib)
        return filtered

    async def replace_settings(self, library: Library, settings: dict) -> Library:
        """Persist a rebuilt ``settings`` blob for a library (mutate + commit).

        Central choke point for the folder/policy/options endpoints so the raw
        ``library.settings = json.dumps(...)`` + ``db.commit()`` no longer lives
        in the router.
        """
        library.settings = json.dumps(settings, sort_keys=True)
        library.updated_at = datetime.now()
        await self.db.commit()
        await self.db.refresh(library)
        return library

    async def probe_path(self, path_str: str) -> dict[str, Any]:
        """Filesystem facts for a single path (offloaded to a thread)."""
        return await asyncio.to_thread(_probe_folder_path, path_str)

    async def media_folder_status(self, library: Library) -> list[dict[str, Any]]:
        """Configured media folders with existence/type flags, FS work threaded."""
        paths = self.media_folder_paths(library)
        probes = (
            await asyncio.gather(
                *(asyncio.to_thread(_probe_folder_path, path) for path in paths)
            )
            if paths
            else []
        )
        return [
            {
                "path": path,
                "exists": probe["exists"],
                "is_directory": probe["is_directory"],
                "primary": index == 0,
            }
            for index, (path, probe) in enumerate(zip(paths, probes))
        ]

    async def list_directory_entries(
        self, directory: Path, root: Path
    ) -> list[dict[str, Any]]:
        """List a directory's children (offloaded to a thread)."""
        return await asyncio.to_thread(
            _list_directory_entries, str(directory), str(root)
        )

    # ==================== Unified Media Operations ====================

    async def create_media_item(
        self,
        title: str,
        media_type: MediaType | None = None,
        library_guid: uuid.UUID | None = None,
        commit: bool = True,
        **kwargs: Any,
    ) -> MediaItem:
        """
        Create a new media item.

        Args:
            title: Media title
            media_type: Media type (required unless library_guid provided for backwards compat)
            library_guid: Deprecated, ignored. Use media_type instead.
            commit: Commit immediately, or only flush for caller-owned UoW
            **kwargs: Additional media fields

        Returns:
            The created media item
        """
        # Determine media type (LibraryService-specific backwards-compat:
        # resolve the type from a library_guid when not given explicitly).
        if media_type is None:
            if library_guid is None:
                raise ValueError("media_type must be provided")
            library = await self.get_library(library_guid)
            if not library:
                raise ValueError(f"Library not found: {library_guid}")
            # library.type is already a string, convert it to MediaType enum
            media_type = MediaType(library.type)

        # Delegate persistence to the canonical MediaService implementation.
        return await self.media.create_media_item(
            media_type=media_type,
            title=title,
            commit=commit,
            **kwargs,
        )

    async def get_media_item(
        self,
        item_guid: uuid.UUID,
        load_files: bool = False,
        load_releases: bool = False,
        load_external_ids: bool = False,
    ) -> MediaItem | None:
        """Get media item by GUID with optional eager loading."""
        query = select(MediaItem).where(MediaItem.guid == item_guid)
        query = query.options(*_MEDIA_ITEM_SLIM_LOAD_OPTIONS)

        if load_files:
            query = query.options(selectinload(MediaItem.files))
        if load_releases:
            # Eager load releases and their links to avoid lazy loading issues
            query = query.options(
                selectinload(MediaItem.releases).selectinload(MediaRelease.links)
            )
        if load_external_ids:
            query = query.options(selectinload(MediaItem.external_ids))

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_disabled_media_types(self) -> set[str]:
        """Get media types belonging to disabled libraries."""
        from streamarr.libraries import get_media_item_types_for_library

        disabled_libraries = await self.db.execute(
            select(Library.type).where(Library.enabled == False)  # noqa: E712
        )
        disabled_types: set[str] = set()
        for (lib_type,) in disabled_libraries:
            for item_type in get_media_item_types_for_library(lib_type):
                disabled_types.add(item_type["name"])
        return disabled_types

    async def list_media_items(
        self,
        library_guid: uuid.UUID | None = None,
        media_type: MediaType | None = None,
        parent_guid: uuid.UUID | None = None,
        genre_id: int | None = None,
        genre_ids: list[int] | None = None,
        genre_names: list[str] | None = None,
        exclude_genre_ids: list[int] | None = None,
        exclude_genre_names: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "created_at",
        order_desc: bool = True,
        top_level_only: bool = False,
        slim: bool = False,
        availability: str | None = None,
        has_poster: bool | None = None,
        has_description: bool | None = None,
        platform_id: int | None = None,
        platform_ids: list[int] | None = None,
        exclude_platform_ids: list[int] | None = None,
        year: int | None = None,
        years: list[int] | None = None,
        exclude_years: list[int] | None = None,
        start_year: int | None = None,
        end_year: int | None = None,
        content_rating: str | None = None,
        exclude_content_ratings: list[str] | None = None,
        studio_name: str | None = None,
        container: str | None = None,
        exclude_containers: list[str] | None = None,
        has_backdrop: bool | None = None,
        is_favorite: bool | None = None,
        is_played: bool | None = None,
        user_guid: uuid.UUID | None = None,
        person_guid: uuid.UUID | None = None,
        person_name: str | None = None,
        exclude_person_guid: uuid.UUID | None = None,
        exclude_person_name: str | None = None,
        search_term: str | None = None,
        allowed_media_types: list[MediaType] | None = None,
        include_disabled_libraries: bool = False,
        max_age: int | None = None,
    ) -> list[MediaItem]:
        """
        List media items with filtering.

        Args:
            library_guid: Filter by library
            media_type: Filter by media type
            parent_guid: Filter by parent (for episodes, tracks, etc.)
            genre_id: Filter by genre
            limit: Max results
            offset: Pagination offset
            order_by: Field to order by
            order_desc: Descending order if True
            top_level_only: If True, only return items without a parent (top-level items)
            slim: If True, only load genres (skip files, releases, external_ids)
            include_disabled_libraries: If True, include items from disabled libraries
        """
        from streamarr.models.media import media_genre_table

        if slim:
            query = select(MediaItem).options(*_MEDIA_ITEM_SLIM_LOAD_OPTIONS)
        else:
            query = select(MediaItem).options(*_MEDIA_ITEM_LOAD_OPTIONS)

        # Exclude items from disabled libraries
        if not include_disabled_libraries:
            disabled_types = await self.get_disabled_media_types()
            if disabled_types:
                query = query.where(MediaItem.media_type.notin_(disabled_types))

        if max_age is not None:
            from streamarr.utils.age_rating import age_filter_clause
            query = query.where(age_filter_clause(max_age))

        if media_type:
            query = query.where(MediaItem.media_type == media_type)
        if allowed_media_types is not None:
            if not allowed_media_types:
                return []
            query = query.where(MediaItem.media_type.in_(allowed_media_types))

        if search_term:
            pattern = f"%{search_term.strip()}%"
            query = query.where(
                or_(
                    MediaItem.title.ilike(pattern),
                    MediaItem.original_title.ilike(pattern),
                    MediaItem.description.ilike(pattern),
                )
            )

        if parent_guid is not None:
            query = query.where(MediaItem.parent_guid == parent_guid)
        elif top_level_only:
            query = query.where(MediaItem.parent_guid.is_(None))

        genre_filter_ids = _combined_int_filters(genre_id, genre_ids)
        genre_filter_names = _clean_lower_values(genre_names)
        if genre_filter_ids or genre_filter_names:
            genre_items = select(media_genre_table.c.media_item_guid)
            if genre_filter_names:
                from streamarr.models.genre import Genre

                genre_items = genre_items.join(
                    Genre, Genre.id == media_genre_table.c.genre_id
                )
                genre_match = func.lower(Genre.name).in_(genre_filter_names)
                if genre_filter_ids:
                    genre_match = or_(
                        media_genre_table.c.genre_id.in_(genre_filter_ids),
                        genre_match,
                    )
                genre_items = genre_items.where(genre_match)
            else:
                genre_items = genre_items.where(
                    media_genre_table.c.genre_id.in_(genre_filter_ids)
                )
            query = query.where(MediaItem.guid.in_(genre_items.distinct()))

        exclude_genre_filter_ids = _clean_int_values(exclude_genre_ids)
        exclude_genre_filter_names = _clean_lower_values(exclude_genre_names)
        if exclude_genre_filter_ids or exclude_genre_filter_names:
            excluded_genre_items = select(media_genre_table.c.media_item_guid)
            if exclude_genre_filter_names:
                from streamarr.models.genre import Genre

                excluded_genre_items = excluded_genre_items.join(
                    Genre, Genre.id == media_genre_table.c.genre_id
                )
                excluded_genre_match = func.lower(Genre.name).in_(
                    exclude_genre_filter_names
                )
                if exclude_genre_filter_ids:
                    excluded_genre_match = or_(
                        media_genre_table.c.genre_id.in_(exclude_genre_filter_ids),
                        excluded_genre_match,
                    )
                excluded_genre_items = excluded_genre_items.where(
                    excluded_genre_match
                )
            else:
                excluded_genre_items = excluded_genre_items.where(
                    media_genre_table.c.genre_id.in_(exclude_genre_filter_ids)
                )
            query = query.where(MediaItem.guid.notin_(excluded_genre_items.distinct()))

        platform_filter_ids = _combined_int_filters(platform_id, platform_ids)
        if platform_filter_ids:
            from streamarr.models.media import media_platform_table
            query = query.where(
                MediaItem.guid.in_(
                    select(media_platform_table.c.media_item_guid)
                    .where(media_platform_table.c.platform_id.in_(platform_filter_ids))
                    .distinct()
                )
            )

        exclude_platform_filter_ids = _clean_int_values(exclude_platform_ids)
        if exclude_platform_filter_ids:
            from streamarr.models.media import media_platform_table
            query = query.where(
                MediaItem.guid.notin_(
                    select(media_platform_table.c.media_item_guid)
                    .where(media_platform_table.c.platform_id.in_(exclude_platform_filter_ids))
                    .distinct()
                )
            )

        if year is not None:
            query = query.where(extract("year", MediaItem.release_date) == year)
        year_values = _clean_int_values(years)
        if year_values:
            query = query.where(extract("year", MediaItem.release_date).in_(year_values))
        exclude_year_values = _clean_int_values(exclude_years)
        if exclude_year_values:
            query = query.where(extract("year", MediaItem.release_date).notin_(exclude_year_values))
        if start_year is not None:
            query = query.where(extract("year", MediaItem.release_date) >= start_year)
        if end_year is not None:
            query = query.where(extract("year", MediaItem.release_date) <= end_year)
        if content_rating:
            query = query.where(MediaItem.content_rating == content_rating)
        exclude_rating_values = _clean_lower_values(exclude_content_ratings)
        if exclude_rating_values:
            query = query.where(
                func.lower(MediaItem.content_rating).notin_(exclude_rating_values)
            )
        if studio_name:
            # Structured lookup scoped to the studio-related keys of the JSONB
            # payload (``extra_data -> key`` on Postgres, JSON path on SQLite)
            # instead of a substring ILIKE over the *whole* serialized blob,
            # which matched unrelated fields (false positives) and forced a
            # full scan. Casting each sub-document to text keeps it tolerant of
            # both scalar values (``studio``) and nested company lists
            # (``production_companies: [{"name": ...}]``). Mirrors the key set
            # used by ``_extract_studio_names`` in the filters endpoint.
            needle = f"%{studio_name.strip().lower()}%"
            studio_keys = (
                "studio",
                "studios",
                "production_company",
                "production_companies",
            )
            query = query.where(
                or_(
                    *(
                        func.lower(cast(MediaItem.extra_data[key], String)).like(needle)
                        for key in studio_keys
                    )
                )
            )
        if container:
            query = query.where(
                MediaItem.guid.in_(
                    select(MediaFile.media_item_guid)
                    .where(func.lower(MediaFile.format) == container.strip().lower())
                    .distinct()
                )
            )
        exclude_container_values = _clean_lower_values(exclude_containers)
        if exclude_container_values:
            query = query.where(
                MediaItem.guid.notin_(
                    select(MediaFile.media_item_guid)
                    .where(func.lower(MediaFile.format).in_(exclude_container_values))
                    .distinct()
                )
            )
        if person_guid is not None or person_name:
            from streamarr.models.person import MediaCast, Person
            cast_items = select(MediaCast.media_item_guid)
            if person_guid is not None:
                cast_items = cast_items.where(MediaCast.person_guid == person_guid)
            if person_name:
                cast_items = cast_items.join(
                    Person, Person.guid == MediaCast.person_guid
                ).where(Person.name.ilike(f"%{person_name.strip()}%"))
            query = query.where(MediaItem.guid.in_(cast_items.distinct()))
        if exclude_person_guid is not None or exclude_person_name:
            from streamarr.models.person import MediaCast, Person
            excluded_cast_items = select(MediaCast.media_item_guid)
            if exclude_person_guid is not None:
                excluded_cast_items = excluded_cast_items.where(
                    MediaCast.person_guid == exclude_person_guid
                )
            if exclude_person_name:
                excluded_cast_items = excluded_cast_items.join(
                    Person, Person.guid == MediaCast.person_guid
                ).where(Person.name.ilike(f"%{exclude_person_name.strip()}%"))
            query = query.where(MediaItem.guid.notin_(excluded_cast_items.distinct()))

        if has_poster is True:
            query = query.where(MediaItem.poster_path.isnot(None))
        elif has_poster is False:
            query = query.where(MediaItem.poster_path.is_(None))

        if has_backdrop is True:
            query = query.where(MediaItem.backdrop_path.isnot(None))
        elif has_backdrop is False:
            query = query.where(MediaItem.backdrop_path.is_(None))

        if has_description is True:
            query = query.where(MediaItem.description.isnot(None), MediaItem.description != "")
        elif has_description is False:
            query = query.where(
                (MediaItem.description.is_(None)) | (MediaItem.description == "")
            )

        if user_guid is not None and is_favorite is not None:
            from streamarr.models.list import List as ListModel
            from streamarr.models.list import ListItem, ListType
            favorite_items = select(ListItem.item_guid).where(
                ListItem.list_guid.in_(
                    select(ListModel.guid).where(
                        ListModel.owner_guid == user_guid,
                        ListModel.list_type == ListType.FAVORITES,
                    )
                )
            )
            query = query.where(
                MediaItem.guid.in_(favorite_items)
                if is_favorite
                else MediaItem.guid.notin_(favorite_items)
            )

        if user_guid is not None and is_played is not None:
            from streamarr.models.viewing_history import ViewingHistory
            played_items = select(ViewingHistory.media_item_guid).where(
                ViewingHistory.user_guid == user_guid,
                ViewingHistory.is_completed.is_(True),
            )
            query = query.where(
                MediaItem.guid.in_(played_items)
                if is_played
                else MediaItem.guid.notin_(played_items)
            )

        if availability == "local":
            # Has at least one file
            query = query.where(
                MediaItem.guid.in_(
                    select(MediaFile.media_item_guid).distinct()
                )
            )
        elif availability == "releases":
            # Has releases but no files
            query = query.where(
                MediaItem.guid.notin_(
                    select(MediaFile.media_item_guid).distinct()
                ),
                MediaItem.guid.in_(
                    select(MediaRelease.media_item_guid).distinct()
                ),
            )
        elif availability == "none":
            # No files and no releases
            query = query.where(
                MediaItem.guid.notin_(
                    select(MediaFile.media_item_guid).distinct()
                ),
                MediaItem.guid.notin_(
                    select(MediaRelease.media_item_guid).distinct()
                ),
            )

        # Order by
        order_field = MediaItem.release_date if order_by == "year" else getattr(
            MediaItem, order_by, MediaItem.created_at
        )
        if order_desc:
            order_field = order_field.desc()
        query = query.order_by(order_field)

        query = query.limit(limit).offset(offset)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_media_items(
        self,
        library_guid: uuid.UUID | None = None,
        media_type: MediaType | None = None,
        parent_guid: uuid.UUID | None = None,
        genre_id: int | None = None,
        genre_ids: list[int] | None = None,
        genre_names: list[str] | None = None,
        exclude_genre_ids: list[int] | None = None,
        exclude_genre_names: list[str] | None = None,
        top_level_only: bool = False,
        availability: str | None = None,
        has_poster: bool | None = None,
        has_description: bool | None = None,
        platform_id: int | None = None,
        platform_ids: list[int] | None = None,
        exclude_platform_ids: list[int] | None = None,
        year: int | None = None,
        years: list[int] | None = None,
        exclude_years: list[int] | None = None,
        start_year: int | None = None,
        end_year: int | None = None,
        content_rating: str | None = None,
        exclude_content_ratings: list[str] | None = None,
        studio_name: str | None = None,
        container: str | None = None,
        exclude_containers: list[str] | None = None,
        has_backdrop: bool | None = None,
        is_favorite: bool | None = None,
        is_played: bool | None = None,
        user_guid: uuid.UUID | None = None,
        person_guid: uuid.UUID | None = None,
        person_name: str | None = None,
        exclude_person_guid: uuid.UUID | None = None,
        exclude_person_name: str | None = None,
        search_term: str | None = None,
        allowed_media_types: list[MediaType] | None = None,
        include_disabled_libraries: bool = False,
        max_age: int | None = None,
    ) -> int:
        """Count media items with filtering."""
        from streamarr.models.media import media_genre_table

        query = select(func.count(MediaItem.guid))

        if not include_disabled_libraries:
            disabled_types = await self.get_disabled_media_types()
            if disabled_types:
                query = query.where(MediaItem.media_type.notin_(disabled_types))

        if max_age is not None:
            from streamarr.utils.age_rating import age_filter_clause
            query = query.where(age_filter_clause(max_age))

        if media_type:
            query = query.where(MediaItem.media_type == media_type)
        if allowed_media_types is not None:
            if not allowed_media_types:
                return 0
            query = query.where(MediaItem.media_type.in_(allowed_media_types))

        if search_term:
            pattern = f"%{search_term.strip()}%"
            query = query.where(
                or_(
                    MediaItem.title.ilike(pattern),
                    MediaItem.original_title.ilike(pattern),
                    MediaItem.description.ilike(pattern),
                )
            )

        if parent_guid is not None:
            query = query.where(MediaItem.parent_guid == parent_guid)
        elif top_level_only:
            query = query.where(MediaItem.parent_guid.is_(None))

        genre_filter_ids = _combined_int_filters(genre_id, genre_ids)
        genre_filter_names = _clean_lower_values(genre_names)
        if genre_filter_ids or genre_filter_names:
            genre_items = select(media_genre_table.c.media_item_guid)
            if genre_filter_names:
                from streamarr.models.genre import Genre

                genre_items = genre_items.join(
                    Genre, Genre.id == media_genre_table.c.genre_id
                )
                genre_match = func.lower(Genre.name).in_(genre_filter_names)
                if genre_filter_ids:
                    genre_match = or_(
                        media_genre_table.c.genre_id.in_(genre_filter_ids),
                        genre_match,
                    )
                genre_items = genre_items.where(genre_match)
            else:
                genre_items = genre_items.where(
                    media_genre_table.c.genre_id.in_(genre_filter_ids)
                )
            query = query.where(MediaItem.guid.in_(genre_items.distinct()))

        exclude_genre_filter_ids = _clean_int_values(exclude_genre_ids)
        exclude_genre_filter_names = _clean_lower_values(exclude_genre_names)
        if exclude_genre_filter_ids or exclude_genre_filter_names:
            excluded_genre_items = select(media_genre_table.c.media_item_guid)
            if exclude_genre_filter_names:
                from streamarr.models.genre import Genre

                excluded_genre_items = excluded_genre_items.join(
                    Genre, Genre.id == media_genre_table.c.genre_id
                )
                excluded_genre_match = func.lower(Genre.name).in_(
                    exclude_genre_filter_names
                )
                if exclude_genre_filter_ids:
                    excluded_genre_match = or_(
                        media_genre_table.c.genre_id.in_(exclude_genre_filter_ids),
                        excluded_genre_match,
                    )
                excluded_genre_items = excluded_genre_items.where(
                    excluded_genre_match
                )
            else:
                excluded_genre_items = excluded_genre_items.where(
                    media_genre_table.c.genre_id.in_(exclude_genre_filter_ids)
                )
            query = query.where(MediaItem.guid.notin_(excluded_genre_items.distinct()))

        platform_filter_ids = _combined_int_filters(platform_id, platform_ids)
        if platform_filter_ids:
            from streamarr.models.media import media_platform_table
            query = query.where(
                MediaItem.guid.in_(
                    select(media_platform_table.c.media_item_guid)
                    .where(media_platform_table.c.platform_id.in_(platform_filter_ids))
                    .distinct()
                )
            )

        exclude_platform_filter_ids = _clean_int_values(exclude_platform_ids)
        if exclude_platform_filter_ids:
            from streamarr.models.media import media_platform_table
            query = query.where(
                MediaItem.guid.notin_(
                    select(media_platform_table.c.media_item_guid)
                    .where(media_platform_table.c.platform_id.in_(exclude_platform_filter_ids))
                    .distinct()
                )
            )

        if year is not None:
            query = query.where(extract("year", MediaItem.release_date) == year)
        year_values = _clean_int_values(years)
        if year_values:
            query = query.where(extract("year", MediaItem.release_date).in_(year_values))
        exclude_year_values = _clean_int_values(exclude_years)
        if exclude_year_values:
            query = query.where(extract("year", MediaItem.release_date).notin_(exclude_year_values))
        if start_year is not None:
            query = query.where(extract("year", MediaItem.release_date) >= start_year)
        if end_year is not None:
            query = query.where(extract("year", MediaItem.release_date) <= end_year)
        if content_rating:
            query = query.where(MediaItem.content_rating == content_rating)
        exclude_rating_values = _clean_lower_values(exclude_content_ratings)
        if exclude_rating_values:
            query = query.where(
                func.lower(MediaItem.content_rating).notin_(exclude_rating_values)
            )
        if studio_name:
            # Structured lookup scoped to the studio-related keys of the JSONB
            # payload (``extra_data -> key`` on Postgres, JSON path on SQLite)
            # instead of a substring ILIKE over the *whole* serialized blob,
            # which matched unrelated fields (false positives) and forced a
            # full scan. Casting each sub-document to text keeps it tolerant of
            # both scalar values (``studio``) and nested company lists
            # (``production_companies: [{"name": ...}]``). Mirrors the key set
            # used by ``_extract_studio_names`` in the filters endpoint.
            needle = f"%{studio_name.strip().lower()}%"
            studio_keys = (
                "studio",
                "studios",
                "production_company",
                "production_companies",
            )
            query = query.where(
                or_(
                    *(
                        func.lower(cast(MediaItem.extra_data[key], String)).like(needle)
                        for key in studio_keys
                    )
                )
            )
        if container:
            query = query.where(
                MediaItem.guid.in_(
                    select(MediaFile.media_item_guid)
                    .where(func.lower(MediaFile.format) == container.strip().lower())
                    .distinct()
                )
            )
        exclude_container_values = _clean_lower_values(exclude_containers)
        if exclude_container_values:
            query = query.where(
                MediaItem.guid.notin_(
                    select(MediaFile.media_item_guid)
                    .where(func.lower(MediaFile.format).in_(exclude_container_values))
                    .distinct()
                )
            )
        if person_guid is not None or person_name:
            from streamarr.models.person import MediaCast, Person
            cast_items = select(MediaCast.media_item_guid)
            if person_guid is not None:
                cast_items = cast_items.where(MediaCast.person_guid == person_guid)
            if person_name:
                cast_items = cast_items.join(
                    Person, Person.guid == MediaCast.person_guid
                ).where(Person.name.ilike(f"%{person_name.strip()}%"))
            query = query.where(MediaItem.guid.in_(cast_items.distinct()))
        if exclude_person_guid is not None or exclude_person_name:
            from streamarr.models.person import MediaCast, Person
            excluded_cast_items = select(MediaCast.media_item_guid)
            if exclude_person_guid is not None:
                excluded_cast_items = excluded_cast_items.where(
                    MediaCast.person_guid == exclude_person_guid
                )
            if exclude_person_name:
                excluded_cast_items = excluded_cast_items.join(
                    Person, Person.guid == MediaCast.person_guid
                ).where(Person.name.ilike(f"%{exclude_person_name.strip()}%"))
            query = query.where(MediaItem.guid.notin_(excluded_cast_items.distinct()))

        if has_poster is True:
            query = query.where(MediaItem.poster_path.isnot(None))
        elif has_poster is False:
            query = query.where(MediaItem.poster_path.is_(None))

        if has_backdrop is True:
            query = query.where(MediaItem.backdrop_path.isnot(None))
        elif has_backdrop is False:
            query = query.where(MediaItem.backdrop_path.is_(None))

        if has_description is True:
            query = query.where(MediaItem.description.isnot(None), MediaItem.description != "")
        elif has_description is False:
            query = query.where(
                (MediaItem.description.is_(None)) | (MediaItem.description == "")
            )

        if user_guid is not None and is_favorite is not None:
            from streamarr.models.list import List as ListModel
            from streamarr.models.list import ListItem, ListType
            favorite_items = select(ListItem.item_guid).where(
                ListItem.list_guid.in_(
                    select(ListModel.guid).where(
                        ListModel.owner_guid == user_guid,
                        ListModel.list_type == ListType.FAVORITES,
                    )
                )
            )
            query = query.where(
                MediaItem.guid.in_(favorite_items)
                if is_favorite
                else MediaItem.guid.notin_(favorite_items)
            )

        if user_guid is not None and is_played is not None:
            from streamarr.models.viewing_history import ViewingHistory
            played_items = select(ViewingHistory.media_item_guid).where(
                ViewingHistory.user_guid == user_guid,
                ViewingHistory.is_completed.is_(True),
            )
            query = query.where(
                MediaItem.guid.in_(played_items)
                if is_played
                else MediaItem.guid.notin_(played_items)
            )

        if availability == "local":
            query = query.where(MediaItem.guid.in_(select(MediaFile.media_item_guid).distinct()))
        elif availability == "releases":
            query = query.where(
                MediaItem.guid.notin_(select(MediaFile.media_item_guid).distinct()),
                MediaItem.guid.in_(select(MediaRelease.media_item_guid).distinct()),
            )
        elif availability == "none":
            query = query.where(
                MediaItem.guid.notin_(select(MediaFile.media_item_guid).distinct()),
                MediaItem.guid.notin_(select(MediaRelease.media_item_guid).distinct()),
            )

        result = await self.db.execute(query)
        return result.scalar() or 0

    async def search_media_items(
        self,
        query_string: str,
        library_guid: uuid.UUID | None = None,
        media_type: MediaType | None = None,
        limit: int = 50,
        slim: bool = False,
        allowed_media_types: list[MediaType] | None = None,
        max_age: int | None = None,
    ) -> list[MediaItem]:
        """
        Search media items by title.

        Args:
            query_string: Search query
            library_guid: Optional filter by library
            media_type: Optional filter by type
            limit: Max results
            slim: If True, only load genres (skip files, releases, external_ids)
            allowed_media_types: User-visible media types to include
            max_age: User parental-control maximum age
        """
        if slim:
            query = (
                select(MediaItem)
                .options(
                    selectinload(MediaItem.genres),
                )
                .where(
                    or_(
                        MediaItem.title.ilike(f"%{query_string}%"),
                        MediaItem.original_title.ilike(f"%{query_string}%"),
                    )
                )
            )
        else:
            query = (
                select(MediaItem)
                .options(*_MEDIA_ITEM_LOAD_OPTIONS)
                .where(
                    or_(
                        MediaItem.title.ilike(f"%{query_string}%"),
                        MediaItem.original_title.ilike(f"%{query_string}%"),
                    )
                )
            )

        if media_type:
            query = query.where(MediaItem.media_type == media_type)
        if allowed_media_types is not None:
            if not allowed_media_types:
                return []
            query = query.where(MediaItem.media_type.in_(allowed_media_types))
        if max_age is not None:
            from streamarr.utils.age_rating import age_filter_clause
            query = query.where(age_filter_clause(max_age))

        query = query.limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_media_item(
        self,
        item_guid: uuid.UUID,
        commit: bool = True,
        **kwargs: Any,
    ) -> MediaItem | None:
        """Update media item fields."""
        media_item = await self.get_media_item(item_guid)
        if not media_item:
            return None

        for key, value in kwargs.items():
            if hasattr(media_item, key):
                setattr(media_item, key, value)

        media_item.updated_at = datetime.now(UTC)

        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await self.db.refresh(media_item)

        return media_item

    async def delete_media_item(
        self,
        item_guid: uuid.UUID,
        *,
        commit: bool = True,
    ) -> bool:
        """Delete media item (cascades to files, releases, etc.).

        Delegates to the canonical ``MediaService.delete``.
        """
        return await self.media.delete(item_guid, commit=commit)

    async def get_children(
        self,
        parent_guid: uuid.UUID,
        order_by_sequence: bool = True,
    ) -> list[MediaItem]:
        """
        Get child media items (e.g., seasons of a show, episodes of a season).

        Delegates to the canonical ``MediaService.get_children`` but eager-loads
        the full detail relations LibraryService callers expect.

        Args:
            parent_guid: Parent media item GUID
            order_by_sequence: Order by sequence_number if True
        """
        return await self.media.get_children(
            parent_guid,
            order_by_sequence=order_by_sequence,
            load_options=_MEDIA_ITEM_LOAD_OPTIONS,
        )

    async def get_children_bulk(
        self,
        parent_guids: list[uuid.UUID],
        order_by_sequence: bool = True,
    ) -> dict[uuid.UUID, list[MediaItem]]:
        """Fetch children for multiple parents in one query, grouped by parent_guid."""
        if not parent_guids:
            return {}
        query = (
            select(MediaItem)
            .options(*_MEDIA_ITEM_LOAD_OPTIONS)
            .where(MediaItem.parent_guid.in_(parent_guids))
        )
        if order_by_sequence:
            query = query.order_by(MediaItem.parent_guid, MediaItem.sequence_number)

        result = await self.db.execute(query)
        grouped: dict[uuid.UUID, list[MediaItem]] = {pg: [] for pg in parent_guids}
        for item in result.scalars().all():
            grouped.setdefault(item.parent_guid, []).append(item)
        return grouped

    async def get_by_external_id(
        self,
        provider: str,
        external_id: str,
        media_type: MediaType | None = None,
    ) -> MediaItem | None:
        """Get media item by external ID (e.g., TMDB ID).

        Delegates to the canonical ``MediaService.get_by_external_id`` with the
        full detail eager-load LibraryService callers expect.
        """
        return await self.media.get_by_external_id(
            provider,
            external_id,
            media_type=media_type,
            load_options=_MEDIA_ITEM_LOAD_OPTIONS,
        )

    async def add_external_id(
        self,
        media_item_guid: uuid.UUID,
        provider: str,
        external_id: str,
    ) -> MediaExternalId:
        """Add external ID mapping (TMDB, IGDB, etc.).

        Delegates to the canonical ``MediaService.add_external_id`` (add +
        commit, no refresh) — behaviourally identical to the previous inline
        implementation.
        """
        return await self.media.add_external_id(
            media_item_guid, provider, external_id
        )

    async def scan_library_for_media(
        self,
        library_guid: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """
        Scan library path for media files using library plugin.

        Args:
            library_guid: Library to scan

        Returns:
            List of discovered media files
        """
        library = await self.get_library(library_guid)
        if not library:
            raise ValueError(f"Library not found: {library_guid}")

        plugin = self.get_plugin(library.type)
        if not plugin:
            raise ValueError(f"No plugin found for library type: {library.type}")

        logger.info("Scanning library: %s at %s", library.name, library.path)
        discovered_files = await plugin.scan_library(library.path)

        logger.info("Found %s media files in %s", len(discovered_files), library.name)

        # Games libraries PERSIST scanned ROMs as MediaItem(GAMES)+MediaFile so
        # they become first-class library media (all other types are
        # discovery-only today, importing via the download-completion path).
        # Scoped to GAMES so movie/show/music/book behaviour is unchanged.
        if library.type == "GAMES":
            await self._ingest_scanned_games(discovered_files)

        return discovered_files

    async def _ingest_scanned_games(
        self, discovered_files: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Upsert scanned ROM files into GAMES MediaItems + MediaFiles.

        Deduplicated on ``MediaFile.file_path`` (an already-ingested ROM is
        skipped). Each new item is stamped with
        ``extra_data.lightrays.profile = "retro"`` so the launch resolver picks
        the retro container profile and derives the ROM bind mount from the
        file. Commits once; returns created/skipped counts.
        """
        created = 0
        skipped = 0
        for info in discovered_files:
            file_path = str(info.get("path") or "").strip()
            if not file_path:
                skipped += 1
                continue
            existing = await self.db.execute(
                select(MediaFile).where(MediaFile.file_path == file_path).limit(1)
            )
            if existing.scalars().first() is not None:
                skipped += 1
                continue

            title = str(info.get("title") or Path(file_path).stem).strip()
            platform = info.get("platform")
            extra_data: dict[str, Any] = {"lightrays": {"profile": "retro"}}
            if platform:
                extra_data["platform"] = platform

            item = await self.media.create_media_item(
                media_type=MediaType.GAMES,
                title=title,
                commit=False,
                extra_data=extra_data,
                availability_status=AvailabilityStatus.AVAILABLE,
            )
            await self.media.create_media_file(
                media_item_guid=item.guid,
                file_path=file_path,
                file_name=Path(file_path).name,
                file_size=info.get("size"),
                format=str(info.get("extension") or "").lstrip("."),
                commit=False,
            )
            created += 1

        if created:
            await self.db.commit()
        logger.info("Games scan ingest: created=%d skipped=%d", created, skipped)
        return {"created": created, "skipped": skipped}

    async def match_media_with_metadata(
        self,
        library_guid: uuid.UUID,
        file_info: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Match a media file to external metadata using library plugin.

        Args:
            library_guid: Library the file belongs to
            file_info: File information

        Returns:
            Matched metadata or None
        """
        library = await self.get_library(library_guid)
        if not library:
            return None

        plugin = self.get_plugin(library.type)
        if not plugin:
            return None

        return await plugin.match_media(file_info)

    async def create_media_release(
        self,
        media_item_guid: uuid.UUID,
        title: str,
        **kwargs: Any,
    ) -> MediaRelease:
        """Create a media release entry.

        Delegates to the canonical ``MediaService.create_media_release``
        (add + commit + refresh) — behaviourally identical.
        """
        return await self.media.create_media_release(
            media_item_guid, title, **kwargs
        )

    async def update_availability_status(
        self,
        item_guid: uuid.UUID,
        status: AvailabilityStatus,
    ) -> MediaItem | None:
        """Update availability status.

        Delegates to the canonical ``MediaService.update_availability_status``.
        """
        return await self.media.update_availability_status(item_guid, status)

    async def rescore_releases(
        self,
        media_item: MediaItem,
        releases: list[MediaRelease],
    ) -> list[MediaRelease]:
        """
        Re-score releases using current scoring rules.

        This should be called when retrieving releases to ensure
        scores reflect current preferences and rules.

        Args:
            media_item: The media item the releases belong to
            releases: List of releases to re-score

        Returns:
            List of releases with updated scores
        """
        if not releases:
            return releases

        # Get the library plugin for this media type
        library_type = (
            media_item.media_type.value
            if hasattr(media_item.media_type, "value")
            else str(media_item.media_type)
        )
        plugin = self.get_plugin(library_type)

        if (
            not plugin
            or not hasattr(plugin, "score_release")
            or not hasattr(plugin, "extract_release_metadata")
        ):
            logger.debug("No scoring plugin available for %s", library_type)
            return releases

        # Load scoring config from settings for this media type
        scoring_preferences: dict[str, Any] | None = None
        try:
            settings_service = SettingsService(self.db)
            config_key = f"scoring.config.{library_type.lower()}"
            scoring_preferences = await settings_service.get(config_key, None)
        except Exception as e:
            logger.warning("Could not load scoring config for %s: %s", library_type, e)

        # Inject allowed_languages from library settings into scoring preferences
        try:
            settings_service = SettingsService(self.db)
            raw_allowed = await settings_service.get(
                f"plugin.{library_type.lower()}.allowed_languages", []
            )
            if isinstance(raw_allowed, list) and raw_allowed:
                if scoring_preferences is None:
                    scoring_preferences = {}
                scoring_preferences.setdefault("allowed_languages", raw_allowed)
        except Exception as e:
            logger.warning("Could not load allowed_languages for %s: %s", library_type, e)

        # Inject codec preferences from the requesting user's quality_preferences.
        # These are stored on the User model as quality_preferences JSON and include:
        #   supported_video_codecs, supported_audio_codecs,
        #   codec_match_bonus, codec_mismatch_penalty
        # Only inject if not already present in scoring_preferences.
        # Re-score each release
        updated = False
        for release in releases:
            try:
                # Always re-parse metadata to pick up any parser improvements
                # (e.g. new 4K/UHD synonym support, HDR pattern fixes)
                metadata = await plugin.extract_release_metadata(release.title)
                # Inject publish_date for age-based scoring
                if hasattr(release, "publish_date") and release.publish_date:
                    metadata["publish_date"] = release.publish_date.isoformat()

                # Calculate new score
                new_score = await plugin.score_release(metadata, scoring_preferences)
                new_score_int = int(new_score)

                # Only persist when the score actually changes so pure GETs
                # (detail/releases) don't write to the DB on every request.
                if release.score != new_score_int:
                    release.release_metadata = metadata
                    release.score = new_score_int
                    updated = True

            except Exception as e:
                logger.warning("Error scoring release %s: %s", release.title, e)
                continue

        # Commit changes if any
        if updated:
            try:
                await self.db.commit()
            except Exception as e:
                logger.error("Error committing release score updates: %s", e)
                await self.db.rollback()

        return releases


class LibraryConfigService:
    """Persistence for per-library-type plugin settings (``plugin.<type>.*``).

    Centralizes the ``settings_service.set(...)`` fan-out that the per-type
    config endpoints previously duplicated one key at a time, so adding a new
    per-type setting no longer requires touching every type's update handler.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = SettingsService(db)

    async def write_type_settings(
        self, prefix: str, values: dict[str, Any]
    ) -> None:
        """Persist ``plugin.<prefix>.<key>`` for each non-``None`` value.

        ``None`` values are skipped (partial update semantics), matching the
        ``if update.<field> is not None`` guards the handlers used before.
        """
        for key, value in values.items():
            if value is not None:
                await self.settings.set(f"{prefix}.{key}", value)
