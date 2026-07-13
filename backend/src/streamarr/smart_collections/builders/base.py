"""Builder protocol for smart collections."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.metadata.list_sources import ExternalRef, ListSourceMediaType


@dataclass(slots=True)
class BuildResult:
    """Output of a single builder ``fetch()``.

    ``refs`` are the external references to attempt to resolve. For
    ``LibraryFilterBuilder`` these are pre-resolved (``provider="local"``);
    the resolver short-circuits in that case.
    """

    refs: list[ExternalRef] = field(default_factory=list)
    # Free-form details the run record may surface to the admin UI (e.g.
    # which TMDb endpoint was called, how many pages walked).
    debug: dict[str, Any] = field(default_factory=dict)


class SmartCollectionBuilder(ABC):
    """A builder fetches refs for one rule execution."""

    #: Registry key. ``ListSourceBuilder`` uses the underlying source slug.
    type: str

    @abstractmethod
    async def fetch(
        self,
        config: dict[str, Any],
        *,
        media_type: ListSourceMediaType,
        limit: int | None,
        db: AsyncSession,
    ) -> BuildResult:
        """Return a ``BuildResult`` for ``config``.

        ``db`` is supplied so builders that need to query the local
        database (``library_filter``) can do so; remote builders ignore it.
        """

    async def close(self) -> None:
        """Release any owned HTTP clients."""
        return None
