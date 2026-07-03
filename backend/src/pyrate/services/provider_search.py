"""
Provider search transforms and per-provider search methods.

This module extracts the *provider* responsibility out of the search God
module (``pyrate.services.search``): turning raw provider payloads (TMDB,
IGDB, Spotify, Open Library) into the unified search-hit format and running
the per-provider search calls.

The behaviour is intentionally identical to the original ``SearchService``
methods — this is a pure move. ``SearchService`` mixes this class in, so all
methods bind to the same instance (``self``) and keep sharing the client
cache, DB session and settings held on the facade.
"""

import logging
from typing import Any

import httpx

from pyrate.metadata.igdb import IGDB
from pyrate.metadata.spotify import Spotify
from pyrate.metadata.tmdb import TMDB
from pyrate.schemas.search import SearchRequest, SearchType

logger = logging.getLogger(__name__)

# Kept here (single definition) and re-exported by pyrate.services.search so
# the facade and the import-queue module can share the exact same tuple.
TRANSIENT_SEARCH_ERRORS = (httpx.HTTPError, TimeoutError, ConnectionError, OSError)


class ProviderSearchMixin:
    """Provider-facing transforms and per-provider search methods.

    Mixed into :class:`pyrate.services.search.SearchService`. Client
    acquisition (``_get_tmdb_client`` etc.) stays on the facade; these methods
    receive an already-constructed client as an argument.
    """

    # ── Search-hit builder ─────────────────────────────────────────────

    @staticmethod
    def _relevance_score(raw: float, index: int, divisor: float = 100) -> float:
        """Compute a 0-10 relevance score from a raw value and result position."""
        base = (raw or 0) / divisor
        position_boost = max(0, 1 - (index * 0.05))
        return min(base + position_boost, 10.0)

    @staticmethod
    def _build_search_hit(*, overrides: dict[str, Any]) -> dict[str, Any]:
        """
        Return a search-hit dict with sensible defaults.

        Callers pass only the fields that differ from the defaults via
        *overrides*.
        """
        hit: dict[str, Any] = {
            "id": None,
            "tmdb_id": None,
            "igdb_id": None,
            "spotify_id": None,
            "type": SearchType.MOVIES,
            "score": 0.0,
            "title": "",
            "original_title": None,
            "description": None,
            "tagline": None,
            "poster_path": None,
            "backdrop_path": None,
            "release_date": None,
            "first_air_date": None,
            "genres": [],
            "genre_ids": [],
            "created_at": None,
            "updated_at": None,
            "status": None,
            "number_of_seasons": None,
            "number_of_episodes": None,
            "popularity": None,
            "vote_average": None,
            "vote_count": None,
            "source": "provider",
            "in_library": False,
        }
        hit.update(overrides)
        return hit

    # ── TMDB ─────────────────────────────────────────────────────────────

    async def _search_tmdb_movies(
        self, tmdb: TMDB, request: SearchRequest
    ) -> dict[str, Any]:
        """Search TMDB for movies."""
        try:
            year = None
            if request.year_from and request.year_from == request.year_to:
                year = request.year_from

            logger.debug("Calling TMDB search_movies: query='%s', year=%s", request.query, year)
            results = await tmdb.search_movies(request.query, year=year)
            logger.debug(
                "TMDB search_movies raw result: %s - keys: %s",
                type(results), results.keys() if isinstance(results, dict) else 'N/A',
            )

            if not results or "results" not in results:
                logger.warning("TMDB search_movies returned no 'results' key: %s", results)
                return {"hits": [], "total": 0}

            hits = []
            for idx, movie in enumerate(results.get("results", [])):
                hit = self._transform_tmdb_movie(movie, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": results.get("total_results", len(hits)),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("TMDB movie search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    async def _search_tmdb_shows(
        self, tmdb: TMDB, request: SearchRequest
    ) -> dict[str, Any]:
        """Search TMDB for TV shows."""
        try:
            # TMDB uses different endpoint for TV search
            params = {"query": request.query}
            if request.year_from and request.year_from == request.year_to:
                params["first_air_date_year"] = request.year_from

            logger.debug("Calling TMDB search/tv: params=%s", params)
            results = await tmdb._request("search/tv", params=params)
            logger.debug(
                "TMDB search/tv raw result: %s - keys: %s",
                type(results), results.keys() if isinstance(results, dict) else 'N/A',
            )

            if not results or "results" not in results:
                logger.warning("TMDB search/tv returned no 'results' key: %s", results)
                return {"hits": [], "total": 0}

            hits = []
            for idx, show in enumerate(results.get("results", [])):
                hit = self._transform_tmdb_show(show, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": results.get("total_results", len(hits)),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("TMDB show search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    def _transform_tmdb_movie(self, movie: dict, index: int) -> dict[str, Any]:
        """Transform TMDB movie result to unified search hit format."""
        return self._build_search_hit(overrides={
            "tmdb_id": movie.get("id"),
            "type": SearchType.MOVIES,
            "score": self._relevance_score(movie.get("popularity", 0), index),
            "title": movie.get("title", ""),
            "original_title": movie.get("original_title"),
            "description": movie.get("overview"),
            "poster_path": movie.get("poster_path"),
            "backdrop_path": movie.get("backdrop_path"),
            "release_date": movie.get("release_date"),
            "genre_ids": movie.get("genre_ids", []),
            "popularity": movie.get("popularity"),
            "vote_average": movie.get("vote_average"),
            "vote_count": movie.get("vote_count"),
            "source": "tmdb",
        })

    def _transform_tmdb_show(self, show: dict, index: int) -> dict[str, Any]:
        """Transform TMDB show result to unified search hit format."""
        return self._build_search_hit(overrides={
            "tmdb_id": show.get("id"),
            "type": SearchType.SHOWS,
            "score": self._relevance_score(show.get("popularity", 0), index),
            "title": show.get("name", ""),
            "original_title": show.get("original_name"),
            "description": show.get("overview"),
            "poster_path": show.get("poster_path"),
            "backdrop_path": show.get("backdrop_path"),
            "first_air_date": show.get("first_air_date"),
            "genre_ids": show.get("genre_ids", []),
            "popularity": show.get("popularity"),
            "vote_average": show.get("vote_average"),
            "vote_count": show.get("vote_count"),
            "source": "tmdb",
        })

    # ── IGDB ─────────────────────────────────────────────────────────────

    async def _search_igdb_games(
        self, igdb: IGDB, request: SearchRequest
    ) -> dict[str, Any]:
        """Search IGDB for games."""
        try:
            logger.debug("Calling IGDB search_games: query='%s'", request.query)
            results = await igdb.search_games(request.query, limit=20)

            if not results:
                return {"hits": [], "total": 0}

            hits = []
            for idx, game in enumerate(results):
                hit = self._transform_igdb_game(game, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": len(hits),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("IGDB game search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    @staticmethod
    def _igdb_cover_url(cover: dict | None) -> str | None:
        """Build a poster URL from an IGDB cover dict."""
        if isinstance(cover, dict) and cover.get("image_id"):
            return f"https://images.igdb.com/igdb/image/upload/t_cover_big/{cover['image_id']}.jpg"
        return None

    @staticmethod
    def _igdb_release_date(timestamp: int | None) -> str | None:
        """Convert a UNIX timestamp to a YYYY-MM-DD string."""
        if not timestamp:
            return None
        from datetime import UTC
        from datetime import datetime as dt
        try:
            return dt.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d")
        except (OSError, ValueError):
            return None

    def _transform_igdb_game(self, game: dict, index: int) -> dict[str, Any]:
        """Transform IGDB game result to unified search hit format."""
        genres = [g.get("name") for g in game.get("genres", []) if g.get("name")]

        return self._build_search_hit(overrides={
            "igdb_id": game.get("id"),
            "type": SearchType.GAMES,
            "score": self._relevance_score(game.get("rating", 0), index, divisor=10),
            "title": game.get("name", ""),
            "description": game.get("summary"),
            "poster_path": self._igdb_cover_url(game.get("cover")),
            "release_date": self._igdb_release_date(game.get("first_release_date")),
            "genres": genres,
            "vote_average": game.get("rating"),
            "vote_count": game.get("rating_count"),
            "source": "igdb",
        })

    # ── Open Library ─────────────────────────────────────────────────────

    async def _search_openlibrary_books(
        self, request: SearchRequest
    ) -> dict[str, Any]:
        """Search Open Library for books."""
        try:
            from pyrate.metadata.openlibrary import OpenLibrary

            client = OpenLibrary()
            try:
                results = await client.search(request.query, limit=20)
            finally:
                await client.close()

            if not results:
                return {"hits": [], "total": 0}

            hits = []
            for idx, book in enumerate(results):
                author_str = ", ".join(book.get("authors", []))
                year = book.get("year")
                hit = self._build_search_hit(overrides={
                    "openlibrary_id": book.get("id"),
                    "type": SearchType.BOOKS,
                    "score": max(0.0, 10.0 - idx * 0.5),
                    "title": book.get("title", ""),
                    "description": author_str,
                    "poster_path": book.get("cover_url"),
                    "release_date": f"{year}-01-01" if year else None,
                    "genres": book.get("subjects", [])[:5],
                    "vote_average": None,
                    "source": "openlibrary",
                })
                hits.append(hit)

            return {"hits": hits, "total": len(hits)}

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("Open Library book search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    # ── Spotify ──────────────────────────────────────────────────────────

    async def _search_spotify_albums(
        self, spotify: Spotify, request: SearchRequest
    ) -> dict[str, Any]:
        """Search Spotify for music albums."""
        try:
            logger.debug("Calling Spotify search_albums: query='%s'", request.query)
            results = await spotify.search_albums(request.query, limit=20)

            if not results:
                return {"hits": [], "total": 0}

            hits = []
            for idx, album in enumerate(results):
                hit = self._transform_spotify_album(album, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": len(hits),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("Spotify album search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    @staticmethod
    def _spotify_image_url(images: list[dict]) -> str | None:
        """Return the URL of the first (largest) Spotify image, or None."""
        return images[0].get("url") if images else None

    @staticmethod
    def _artist_names_str(artists: list[dict]) -> str | None:
        """Join artist names into a comma-separated string."""
        names = [a.get("name") for a in artists if a.get("name")]
        return ", ".join(names) if names else None

    def _transform_spotify_album(self, album: dict, index: int) -> dict[str, Any]:
        """Transform Spotify album result to unified search hit format."""
        return self._build_search_hit(overrides={
            "spotify_id": album.get("id"),
            "type": SearchType.MUSIC,
            "score": self._relevance_score(album.get("popularity", 0), index),
            "title": album.get("name", ""),
            "description": self._artist_names_str(album.get("artists", [])),
            "poster_path": self._spotify_image_url(album.get("images", [])),
            "release_date": album.get("release_date"),
            "status": album.get("album_type"),
            "number_of_episodes": album.get("total_tracks"),
            "popularity": album.get("popularity"),
            "source": "spotify",
        })

    async def _search_spotify_artists(
        self, spotify: Spotify, request: SearchRequest
    ) -> dict[str, Any]:
        """Search Spotify for artists."""
        try:
            logger.debug("Calling Spotify search_artists: query='%s'", request.query)
            results = await spotify.search_artists(request.query, limit=10)

            if not results:
                return {"hits": [], "total": 0}

            hits = []
            for idx, artist in enumerate(results):
                hit = self._transform_spotify_artist(artist, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": len(hits),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("Spotify artist search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    def _transform_spotify_artist(self, artist: dict, index: int) -> dict[str, Any]:
        """Transform Spotify artist result to unified search hit format."""
        return self._build_search_hit(overrides={
            "spotify_id": artist.get("id"),
            "type": SearchType.MUSIC,
            "music_type": "artist",
            "score": self._relevance_score(artist.get("popularity", 0), index),
            "title": artist.get("name", ""),
            "poster_path": self._spotify_image_url(artist.get("images", [])),
            "genres": artist.get("genres", []),
            "popularity": artist.get("popularity"),
            "source": "spotify",
        })

    async def _search_spotify_tracks(
        self, spotify: Spotify, request: SearchRequest
    ) -> dict[str, Any]:
        """Search Spotify for tracks."""
        try:
            logger.debug("Calling Spotify search_tracks: query='%s'", request.query)
            results = await spotify.search_tracks(request.query, limit=10)

            if not results:
                return {"hits": [], "total": 0}

            hits = []
            for idx, track in enumerate(results):
                hit = self._transform_spotify_track(track, idx)
                hits.append(hit)

            return {
                "hits": hits,
                "total": len(hits),
            }

        except TRANSIENT_SEARCH_ERRORS as e:
            logger.error("Spotify track search error: %s", e)
            return {"hits": [], "total": 0, "error": str(e)}

    def _transform_spotify_track(self, track: dict, index: int) -> dict[str, Any]:
        """Transform Spotify track result to unified search hit format."""
        album = track.get("album", {})

        return self._build_search_hit(overrides={
            "spotify_id": track.get("id"),
            "album_spotify_id": album.get("id"),
            "type": SearchType.MUSIC,
            "music_type": "track",
            "score": self._relevance_score(track.get("popularity", 0), index),
            "title": track.get("name", ""),
            "description": self._artist_names_str(track.get("artists", [])),
            "poster_path": self._spotify_image_url(album.get("images", [])),
            "release_date": album.get("release_date"),
            "popularity": track.get("popularity"),
            "source": "spotify",
        })
