"""Smart-collection engine: auto-populate Lists from external sources.

Public API:
    * ``SmartCollectionService`` — orchestrates a single rule run.
    * ``build_builder`` — factory mapping ``builder_type`` to a Builder.
    * ``next_run_after`` — cron helper used by the scheduler.
"""

from streamarr.smart_collections.builders.registry import (
    build_builder,
    builder_types,
)
from streamarr.smart_collections.cron import next_run_after, parse_cron
from streamarr.smart_collections.service import (
    SmartCollectionService,
    SmartCollectionRunResult,
)

__all__ = [
    "SmartCollectionService",
    "SmartCollectionRunResult",
    "build_builder",
    "builder_types",
    "next_run_after",
    "parse_cron",
]
