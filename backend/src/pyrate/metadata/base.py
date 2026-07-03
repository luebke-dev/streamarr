"""Base classes for metadata providers and indexers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedMetadata:
    """Provider-agnostic metadata format.

    All providers must return data in this format so the worker
    can update the database generically without knowing about
    provider-specific field names.
    """

    title: str | None = None
    original_title: str | None = None
    description: str | None = None
    tagline: str | None = None
    release_date: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    # Parental-control fields: raw certification + normalized age-years.
    content_rating: str | None = None
    min_age: int | None = None
    # Credits (cast/crew) in provider format — consumed by PersonService
    credits: dict = field(default_factory=dict)
    # For shows: season list from provider
    seasons: list[dict] = field(default_factory=list)
    # All remaining provider-specific data (stored as extra_data JSON)
    extra: dict = field(default_factory=dict)


class MetadataBase(ABC):
    """Abstract base class for metadata providers (TMDB, IGDB, Spotify, etc.)."""

    @abstractmethod
    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def get_details(self, media_id: str | int, **kwargs) -> dict[str, Any]:
        """Get raw provider details. Prefer get_normalized_details for refresh."""
        pass

    async def get_normalized_details(
        self, media_id: str | int, media_type: str = "movie", **kwargs
    ) -> NormalizedMetadata:
        """Get details in normalized format. Subclasses should override this."""
        raw = await self.get_details(media_id, **kwargs)
        return self._normalize(raw, media_type)

    def _normalize(self, raw: dict, media_type: str = "movie") -> NormalizedMetadata:
        """Default normalization — subclasses should override for accuracy."""
        return NormalizedMetadata(
            title=raw.get("title") or raw.get("name"),
            original_title=raw.get("original_title") or raw.get("original_name"),
            description=raw.get("overview") or raw.get("description") or raw.get("summary"),
            tagline=raw.get("tagline"),
            release_date=raw.get("release_date") or raw.get("first_air_date"),
            poster_path=raw.get("poster_path"),
            backdrop_path=raw.get("backdrop_path"),
            extra=raw,
        )

    async def get_translations(
        self, media_id: str | int, media_type: str = "movie"
    ) -> dict[str, dict]:
        """Get translations keyed by language code. Override in subclasses."""
        return {}

    async def get_trending(self, media_type: str, **kwargs) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def close(self) -> None:
        pass

    async def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"valid": True, "errors": []}
