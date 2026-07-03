"""Legacy registry adapter backed by the static library/metadata modules."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from pyrate.libraries import get_registered_plugins as _library_plugins
from pyrate.metadata.igdb import IGDB
from pyrate.metadata.tmdb import TMDB


_METADATA_PLUGINS = {
    "tmdb": TMDB,
    "igdb": IGDB,
}


@dataclass(slots=True)
class PluginInfo:
    """Minimal plugin metadata exposed by the legacy registry API."""

    plugin_id: str
    plugin_class: type
    builtin: bool = True

    @property
    def name(self) -> str:
        return self.plugin_id.replace("_", " ").title()

    @property
    def manifest(self) -> SimpleNamespace:
        return SimpleNamespace(
            builtin=self.builtin,
            description=f"{self.name} Library",
        )

    def load_translations(self, _locale: str | None = None) -> dict[str, str] | None:
        return None


class PluginRegistry:
    """Small adapter for code/tests still expecting a dynamic registry."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginInfo] = {}
        for library_type, plugin_class in _library_plugins().items():
            self._plugins[library_type.lower()] = PluginInfo(
                plugin_id=library_type.lower(),
                plugin_class=plugin_class,
            )

    def get_plugin(self, plugin_id: str) -> PluginInfo | None:
        return self._plugins.get(plugin_id.lower())


def get_registered_plugins() -> dict[str, type]:
    """Return static library plugins via the legacy namespace."""
    return _library_plugins()


def get_registry() -> PluginRegistry:
    """Return a registry-shaped view over static plugins."""
    return PluginRegistry()


def get_plugin_class(plugin_id: str) -> type | None:
    """Return a metadata or library plugin class by legacy plugin id."""
    normalized = plugin_id.lower()
    if normalized in _METADATA_PLUGINS:
        return _METADATA_PLUGINS[normalized]
    return _library_plugins().get(plugin_id.upper())
