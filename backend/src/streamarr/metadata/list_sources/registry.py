"""Registry & factory for list-source adapters.

The registry maps a stable ``slug`` (used in setting keys and admin
config) onto a constructor that turns a dict of API keys into a
configured ``ListSource`` instance. The smart-collection engine calls
``build_source(slug, api_keys)`` to obtain a source for one fetch.
"""

from __future__ import annotations

from typing import Any, Callable

from streamarr.metadata.list_sources.anilist import AnilistListSource
from streamarr.metadata.list_sources.base import (
    ListSource,
    ListSourceError,
)
from streamarr.metadata.list_sources.imdb import ImdbListSource
from streamarr.metadata.list_sources.letterboxd import LetterboxdListSource
from streamarr.metadata.list_sources.mal import MalListSource
from streamarr.metadata.list_sources.mdblist import MdblistListSource
from streamarr.metadata.list_sources.tmdb_list import TmdbListSource
from streamarr.metadata.list_sources.trakt import TraktListSource


_Factory = Callable[[dict[str, Any]], ListSource]


def _need(api_keys: dict[str, Any], slug: str) -> str:
    key = api_keys.get(slug)
    if not key:
        raise ListSourceError(
            f"List source {slug!r} requires an API key in "
            f"settings['smart_collections.api_keys'][{slug!r}]"
        )
    return key


def _tmdb(api_keys: dict[str, Any]) -> ListSource:
    return TmdbListSource(api_key=_need(api_keys, "tmdb"))


def _trakt(api_keys: dict[str, Any]) -> ListSource:
    return TraktListSource(client_id=_need(api_keys, "trakt"))


def _mdblist(api_keys: dict[str, Any]) -> ListSource:
    return MdblistListSource(api_key=_need(api_keys, "mdblist"))


def _imdb(_: dict[str, Any]) -> ListSource:
    return ImdbListSource()


def _letterboxd(_: dict[str, Any]) -> ListSource:
    return LetterboxdListSource()


def _mal(_: dict[str, Any]) -> ListSource:
    return MalListSource()


def _anilist(_: dict[str, Any]) -> ListSource:
    return AnilistListSource()


_REGISTRY: dict[str, _Factory] = {
    "tmdb": _tmdb,
    "trakt": _trakt,
    "mdblist": _mdblist,
    "imdb": _imdb,
    "letterboxd": _letterboxd,
    "mal": _mal,
    "anilist": _anilist,
}


def list_source_slugs() -> list[str]:
    """All registered list-source slugs."""
    return sorted(_REGISTRY)


def build_source(slug: str, api_keys: dict[str, Any] | None = None) -> ListSource:
    """Construct a list source by slug, pulling API keys from ``api_keys``."""
    factory = _REGISTRY.get(slug)
    if factory is None:
        raise ListSourceError(f"Unknown list source slug {slug!r}")
    return factory(api_keys or {})


def source_class(slug: str) -> type[ListSource]:
    """Return the source class (without instantiating). Useful for schemas."""
    factory = _REGISTRY.get(slug)
    if factory is None:
        raise ListSourceError(f"Unknown list source slug {slug!r}")
    # Each factory closes over its class — easier to map slug → class explicitly.
    return _SLUG_TO_CLASS[slug]


_SLUG_TO_CLASS: dict[str, type[ListSource]] = {
    "tmdb": TmdbListSource,
    "trakt": TraktListSource,
    "mdblist": MdblistListSource,
    "imdb": ImdbListSource,
    "letterboxd": LetterboxdListSource,
    "mal": MalListSource,
    "anilist": AnilistListSource,
}
