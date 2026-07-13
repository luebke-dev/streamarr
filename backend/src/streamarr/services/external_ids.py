"""Shared helper for reading provider external IDs off a media item.

Both :mod:`streamarr.services.search` and :mod:`streamarr.services.local_search`
need to turn a collection of ``MediaExternalId`` rows into the
``(tmdb_id, igdb_id, spotify_id)`` triple used by search hits. The logic used
to be copy-pasted in both places; it now lives here so a provider/parse change
is made once.
"""

import logging

logger = logging.getLogger(__name__)


def extract_external_ids(external_ids) -> tuple[int | None, int | None, str | None]:
    """Extract ``(tmdb_id, igdb_id, spotify_id)`` from external ID objects."""
    tmdb_id: int | None = None
    igdb_id: int | None = None
    spotify_id: str | None = None
    for ext in external_ids or []:
        if ext.provider == "tmdb":
            try:
                tmdb_id = int(ext.external_id)
            except (ValueError, TypeError):
                logger.debug("Non-integer TMDB external ID: %s", ext.external_id)
        elif ext.provider == "igdb":
            try:
                igdb_id = int(ext.external_id)
            except (ValueError, TypeError):
                logger.debug("Non-integer IGDB external ID: %s", ext.external_id)
        elif ext.provider == "spotify":
            spotify_id = ext.external_id
    return tmdb_id, igdb_id, spotify_id
