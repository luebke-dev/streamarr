"""List-source adapters: fetch external media lists for smart collections.

Unlike `MetadataBase` (which describes a single item), a ``ListSource``
returns *references* (external IDs) to many items. The smart-collection
engine resolves these refs against ``MediaExternalId`` to find local
``MediaItem`` rows, then applies filters and updates the target ``List``.
"""

from pyrate.metadata.list_sources.base import (
    ExternalRef,
    ListSource,
    ListSourceError,
    ListSourceMediaType,
)
from pyrate.metadata.list_sources.registry import (
    build_source,
    list_source_slugs,
    source_class,
)

__all__ = [
    "ExternalRef",
    "ListSource",
    "ListSourceError",
    "ListSourceMediaType",
    "build_source",
    "list_source_slugs",
    "source_class",
]
