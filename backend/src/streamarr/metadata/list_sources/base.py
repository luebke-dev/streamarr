"""Base types for list-source adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar


class ListSourceMediaType(StrEnum):
    MOVIE = "movie"
    SHOW = "show"


@dataclass(slots=True)
class ExternalRef:
    """A reference to a media item by external provider id.

    The resolver looks up ``(provider, external_id)`` in ``media_external_id``
    to find a local ``MediaItem``. ``extra`` carries hints that filters may
    use without re-fetching from the provider (e.g. ``vote_average``).
    """

    provider: str  # "tmdb", "imdb", "tvdb", "anilist", "mal"
    external_id: str
    media_type: ListSourceMediaType
    title: str | None = None
    year: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class ListSourceError(Exception):
    """Raised when a list source cannot fulfil a fetch request."""


class ListSource(ABC):
    """Abstract list-source adapter.

    Concrete subclasses declare:
      * ``slug``: stable identifier used in setting keys and registry lookup.
      * ``supported_media_types``: which media types this source can return.
      * ``config_schema``: JSON-schema-ish dict the admin UI uses to render
        a form. Same shape as ``MetadataBase.get_config_schema`` so the
        frontend can reuse its renderer.

    Concrete subclasses implement ``fetch()`` returning ``ExternalRef`` rows.
    """

    slug: ClassVar[str]
    supported_media_types: ClassVar[frozenset[ListSourceMediaType]]
    config_schema: ClassVar[dict[str, Any]] = {}
    requires_api_key: ClassVar[bool] = False

    @abstractmethod
    async def fetch(
        self,
        config: dict[str, Any],
        *,
        media_type: ListSourceMediaType,
        limit: int | None = None,
    ) -> list[ExternalRef]:
        """Return external references matching ``config``."""

    async def close(self) -> None:
        """Release HTTP clients etc. Default no-op."""
        return None
