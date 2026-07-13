"""Static library registry. No dynamic plugin discovery needed."""

from __future__ import annotations

from typing import Any

from streamarr.libraries.base import LibraryBase


def _import_libraries() -> dict[str, type[LibraryBase]]:
    """Import all library classes. Done in a function to avoid circular imports."""
    from streamarr.libraries.movies import MovieLibraryPlugin
    from streamarr.libraries.shows import ShowLibraryPlugin
    from streamarr.libraries.music import MusicLibraryPlugin
    from streamarr.libraries.games import GameLibraryPlugin
    from streamarr.libraries.books import BookLibraryPlugin
    from streamarr.libraries.photos import PhotoLibraryPlugin

    return {
        "MOVIES": MovieLibraryPlugin,
        "SHOWS": ShowLibraryPlugin,
        "MUSIC": MusicLibraryPlugin,
        "GAMES": GameLibraryPlugin,
        "BOOKS": BookLibraryPlugin,
        "PHOTOS": PhotoLibraryPlugin,
    }


_registry: dict[str, type[LibraryBase]] | None = None
_instances: dict[str, LibraryBase] = {}


def _ensure_registry() -> dict[str, type[LibraryBase]]:
    global _registry
    if _registry is None:
        _registry = _import_libraries()
    return _registry


def get_plugin_instance(library_type: str) -> LibraryBase | None:
    registry = _ensure_registry()
    upper = library_type.upper()
    if upper not in _instances:
        cls = registry.get(upper)
        if cls is None:
            return None
        _instances[upper] = cls()
    return _instances[upper]


def get_registered_plugins() -> dict[str, type[LibraryBase]]:
    return dict(_ensure_registry())


def get_all_media_item_types() -> list[str]:
    registry = _ensure_registry()
    types = []
    seen: set[str] = set()
    for cls in registry.values():
        instance = cls()
        for item_type in instance.get_media_item_types():
            name = item_type["name"]
            if name not in seen:
                types.append(name)
                seen.add(name)
    return types


def get_available_media_types() -> list[str]:
    return list(_ensure_registry().keys())


def get_media_item_types_for_library(library_type: str) -> list[dict[str, Any]]:
    registry = _ensure_registry()
    cls = registry.get(library_type.upper())
    if cls is None:
        return []
    return cls().get_media_item_types()


def get_library_type_for_media_item_type(media_type: str) -> str | None:
    registry = _ensure_registry()
    upper = media_type.upper()
    for lib_type, cls in registry.items():
        instance = cls()
        for item_type in instance.get_media_item_types():
            if item_type["name"].upper() == upper:
                return lib_type
    return None
