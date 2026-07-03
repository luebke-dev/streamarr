"""Smart-collection builders.

A *builder* produces ``ExternalRef`` rows for a given ``builder_config``.
Most builders are thin adapters around a ``ListSource``; the special
``library_filter`` builder runs locally against pyrate's MediaItem table.
"""

from pyrate.smart_collections.builders.base import (
    BuildResult,
    SmartCollectionBuilder,
)
from pyrate.smart_collections.builders.library_filter import (
    LibraryFilterBuilder,
    LIBRARY_FILTER_TYPE,
)
from pyrate.smart_collections.builders.list_source import (
    ListSourceBuilder,
)
from pyrate.smart_collections.builders.registry import (
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
