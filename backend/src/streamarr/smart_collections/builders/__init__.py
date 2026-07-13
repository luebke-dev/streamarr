"""Smart-collection builders.

A *builder* produces ``ExternalRef`` rows for a given ``builder_config``.
Most builders are thin adapters around a ``ListSource``; the special
``library_filter`` builder runs locally against streamarr's MediaItem table.
"""

from streamarr.smart_collections.builders.base import (
    BuildResult,
    SmartCollectionBuilder,
)
from streamarr.smart_collections.builders.library_filter import (
    LibraryFilterBuilder,
    LIBRARY_FILTER_TYPE,
)
from streamarr.smart_collections.builders.list_source import (
    ListSourceBuilder,
)
from streamarr.smart_collections.builders.registry import (
    build_builder,
    builder_types,
)

__all__ = [
    "BuildResult",
    "SmartCollectionBuilder",
    "LibraryFilterBuilder",
    "ListSourceBuilder",
    "LIBRARY_FILTER_TYPE",
    "build_builder",
    "builder_types",
]
