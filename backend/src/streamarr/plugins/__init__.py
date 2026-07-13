"""Compatibility facade for the legacy plugin registry namespace."""

from streamarr.plugins.registry import (
    get_plugin_class,
    get_registry,
    get_registered_plugins,
)

__all__ = ["get_plugin_class", "get_registry", "get_registered_plugins"]
