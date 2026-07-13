import hashlib
import json
import logging
import time
from typing import Any

import httpx

from streamarr.metadata.base import MetadataBase
from streamarr.indexers.base import IndexerBase
from streamarr.utils.http import make_async_client
from streamarr.utils.retry import http_with_retries

logger = logging.getLogger(__name__)

# Module-level response cache shared across instances. Access is intentionally
# lock-free: dict operations are atomic under the GIL, and at worst two
# concurrent callers will double-fetch the same uncached endpoint — the cache
# is a best-effort optimisation, not a consistency boundary.
_response_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 3600  # 1 hour
_CACHE_MAX_SIZE = 2000
_MAX_RETRIES = 3


class Spotify(MetadataBase, IndexerBase):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: str | None = None
        self.token_expires_at: float | None = None
        self.base_url = "https://api.spotify.com/v1"
        self.auth_url = "https://accounts.spotify.com/api/token"

        if client is None:
            self.client = make_async_client()
        else:
            self.client = client

    def get_name(self) -> str:
        """Get the plugin name."""
        return "Spotify"

    def get_config_schema(self) -> dict[str, Any]:
        """Get configuration schema for Spotify."""
        return {
            "client_id": {
                "type": "string",
                "label": "Client ID",
                "hint": "Your Spotify Application Client ID",
                "required": True,
                "placeholder": "Enter your Spotify Client ID",
                "info_text": "Create an app at: https://developer.spotify.com/dashboard",
                "info_link": "https://developer.spotify.com/dashboard",
            },
            "client_secret": {
                "type": "password",
                "label": "Client Secret",
                "hint": "Your Spotify Application Client Secret",
                "required": True,
                "placeholder": "Enter your Spotify Client Secret",
                "info_text": "Get credentials at: https://developer.spotify.com/dashboard",
                "info_link": "https://developer.spotify.com/dashboard",
            },
        }

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """
        Search for albums, tracks, or artists.

        Args:
            query: Search query string
            **kwargs: Additional parameters like 'search_type' (album/track/artist), 'limit'

        Returns:
            list[dict]: Search results
        """
        search_type = kwargs.get("search_type", "album")
        limit = kwargs.get("limit", 20)

        if search_type == "album":
            return await self.search_albums(query, limit)
        elif search_type == "track":
            return await self.search_tracks(query, limit)
        elif search_type == "artist":
            return await self.search_artists(query, limit)
        else:
            return await self.search_albums(query, limit)

    async def get_details(self, media_id: str | int, **kwargs) -> dict[str, Any]:
        """
        Get detailed information about an album, track, or artist.

        Args:
            media_id: The Spotify ID
            **kwargs: Additional parameters like 'media_type' (album/track/artist)

        Returns:
            dict: Detailed media information
        """
        media_type = kwargs.get("media_type", "album")

        if media_type == "album":
            return await self.get_album_details(str(media_id))
        elif media_type == "track":
            return await self.get_track_details(str(media_id))
        elif media_type == "artist":
            return await self.get_artist_details(str(media_id))
        else:
            return await self.get_album_details(str(media_id))

    async def _authenticate(self) -> bool:
        """Authenticate with Spotify using Client Credentials flow"""
        try:
            response = await self.client.post(
                self.auth_url,
                data={
                    "grant_type": "client_credentials",
                },
                auth=(self.client_id, self.client_secret),
            )
            response.raise_for_status()

            data = response.json()
            self.access_token = data["access_token"]
            # Set expiry time to current time + expires_in seconds minus 5 minutes buffer
            self.token_expires_at = time.time() + data["expires_in"] - 300

            logger.info("Successfully authenticated with Spotify API")
            return True

        except Exception as e:
            logger.error(f"Failed to authenticate with Spotify API: {e}")
            return False

    async def _ensure_authenticated(self) -> bool:
        """Ensure we have a valid access token"""
        if (
            self.access_token is None
            or self.token_expires_at is None
            or time.time() >= self.token_expires_at
        ):
            return await self._authenticate()
        return True

    @staticmethod
    def _cache_key(endpoint: str, params: dict) -> str:
        raw = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _cache_get(key: str) -> Any | None:
        entry = _response_cache.get(key)
        if entry and time.time() < entry[0]:
            return entry[1]
        if entry:
            _response_cache.pop(key, None)
        return None

    @staticmethod
    def _cache_set(key: str, value: Any) -> None:
        # Evict oldest entries if cache is too large
        if len(_response_cache) >= _CACHE_MAX_SIZE:
            oldest = sorted(_response_cache, key=lambda k: _response_cache[k][0])
            for k in oldest[: _CACHE_MAX_SIZE // 4]:
                _response_cache.pop(k, None)
        _response_cache[key] = (time.time() + _CACHE_TTL, value)

    async def _request(
        self, endpoint: str, params: dict | None = None
    ) -> dict[str, Any]:
        """Make a request to the Spotify API with caching and retry on rate limit."""
        if not await self._ensure_authenticated():
            return {}

        params = params or {}
        cache_key = self._cache_key(endpoint, params)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        async def do_request():
            return await self.client.get(
                f"{self.base_url}/{endpoint}",
                headers={"Authorization": f"Bearer {self.access_token}"},
                params=params,
            )

        async def refresh_auth():
            # Drop the token so _ensure_authenticated triggers a fresh fetch.
            self.access_token = None
            await self._ensure_authenticated()

        try:
            response = await http_with_retries(
                do_request,
                max_retries=_MAX_RETRIES,
                on_unauthorized=refresh_auth,
                log_label=f"Spotify {endpoint}",
            )
        except Exception as exc:
            logger.error("Spotify request failed for %s: %s", endpoint, exc)
            return {}
        if response is None:
            return {}
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("HTTP error on %s: %s", endpoint, exc)
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("Spotify invalid JSON for %s: %s", endpoint, exc)
            return {}
        self._cache_set(cache_key, data)
        return data

    async def search_albums(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search for albums by name"""
        result = await self._request(
            "search",
            params={
                "q": query,
                "type": "album",
                "limit": limit,
            },
        )

        if "albums" in result and "items" in result["albums"]:
            return result["albums"]["items"]
        return []

    async def search_tracks(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search for tracks by name"""
        result = await self._request(
            "search",
            params={
                "q": query,
                "type": "track",
                "limit": limit,
            },
        )

        if "tracks" in result and "items" in result["tracks"]:
            return result["tracks"]["items"]
        return []

    async def search_artists(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search for artists by name"""
        result = await self._request(
            "search",
            params={
                "q": query,
                "type": "artist",
                "limit": limit,
            },
        )

        if "artists" in result and "items" in result["artists"]:
            return result["artists"]["items"]
        return []

    async def get_album_details(self, album_id: str) -> dict[str, Any]:
        """Get detailed information about a specific album"""
        result = await self._request(f"albums/{album_id}")
        return result if result else {}

    async def get_albums_batch(self, album_ids: list[str]) -> list[dict[str, Any]]:
        """Get details for multiple albums in one request (max 20 per batch)."""
        albums = []
        for i in range(0, len(album_ids), 20):
            batch = album_ids[i : i + 20]
            result = await self._request("albums", params={"ids": ",".join(batch)})
            albums.extend(result.get("albums", []))
        return [a for a in albums if a]

    async def get_album_tracks(
        self, album_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get tracks from a specific album"""
        result = await self._request(
            f"albums/{album_id}/tracks",
            params={"limit": limit},
        )

        if "items" in result:
            return result["items"]
        return []

    async def get_track_details(self, track_id: str) -> dict[str, Any]:
        """Get detailed information about a specific track"""
        result = await self._request(f"tracks/{track_id}")
        return result if result else {}

    async def get_tracks_batch(self, track_ids: list[str]) -> list[dict[str, Any]]:
        """Get details for multiple tracks in one request (max 50 per batch)."""
        tracks = []
        for i in range(0, len(track_ids), 50):
            batch = track_ids[i : i + 50]
            result = await self._request("tracks", params={"ids": ",".join(batch)})
            tracks.extend(result.get("tracks", []))
        return [t for t in tracks if t]

    async def get_artist_details(self, artist_id: str) -> dict[str, Any]:
        """Get detailed information about a specific artist"""
        result = await self._request(f"artists/{artist_id}")
        return result if result else {}

    async def get_artists_batch(self, artist_ids: list[str]) -> list[dict[str, Any]]:
        """Get details for multiple artists in one request (max 50 per batch)."""
        artists = []
        for i in range(0, len(artist_ids), 50):
            batch = artist_ids[i : i + 50]
            result = await self._request("artists", params={"ids": ",".join(batch)})
            artists.extend(result.get("artists", []))
        return [a for a in artists if a]

    async def get_artist_albums(
        self, artist_id: str, limit: int = 20, include_groups: str = "album,single"
    ) -> list[dict[str, Any]]:
        """Get albums by a specific artist"""
        result = await self._request(
            f"artists/{artist_id}/albums",
            params={
                "limit": limit,
                "include_groups": include_groups,
            },
        )

        if "items" in result:
            return result["items"]
        return []

    async def get_trending_albums(
        self, limit: int = 50, country: str = "DE"
    ) -> list[dict[str, Any]]:
        """Get trending albums via Spotify's new-releases endpoint.

        The previous playlist-based approach broke because Spotify no longer
        allows Client Credentials access to curated playlists (404).
        ``browse/new-releases`` is stable and returns current popular albums.
        """
        result = await self._request(
            "browse/new-releases",
            params={"limit": min(limit, 50), "country": country},
        )

        albums = result.get("albums", {}).get("items", [])
        return [a for a in albums if a and a.get("id")]

    async def get_new_releases(
        self, limit: int = 20, country: str = "US"
    ) -> list[dict[str, Any]]:
        """Get new album releases"""
        result = await self._request(
            "browse/new-releases",
            params={
                "limit": limit,
                "country": country,
            },
        )

        if "albums" in result and "items" in result["albums"]:
            return result["albums"]["items"]
        return []

    async def get_featured_playlists(
        self, limit: int = 20, country: str = "US"
    ) -> list[dict[str, Any]]:
        """Get featured playlists"""
        result = await self._request(
            "browse/featured-playlists",
            params={
                "limit": limit,
                "country": country,
            },
        )

        if "playlists" in result and "items" in result["playlists"]:
            return result["playlists"]["items"]
        return []

    async def get_categories(
        self, limit: int = 20, country: str = "US"
    ) -> list[dict[str, Any]]:
        """Get available browse categories"""
        result = await self._request(
            "browse/categories",
            params={
                "limit": limit,
                "country": country,
            },
        )

        if "categories" in result and "items" in result["categories"]:
            return result["categories"]["items"]
        return []

    # --- IndexerPlugin interface ---

    async def search_movie(
        self, q: str | None = None, imdb_id: str | None = None, **kwargs
    ) -> list[dict[str, Any]]:
        return []

    async def search_show(
        self,
        q: str | None = None,
        tvdb_id: str | None = None,
        season: str | None = None,
        ep: str | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        return []

    async def search_music(
        self,
        q: str | None = None,
        spotify_id: str | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """
        Search for music releases on Spotify and return them as indexer results
        suitable for download via spotdl.

        If spotify_id is provided, fetches that specific track/album.
        Otherwise searches by query string.

        Returns releases with Spotify URLs that spotdl can download.
        """
        results = []

        if spotify_id:
            # Try as track first, then album
            track = await self.get_track_details(spotify_id)
            if track and track.get("type") == "track":
                results.append(self._track_to_release(track))
            else:
                album = await self.get_album_details(spotify_id)
                if album and album.get("tracks"):
                    tracks = album["tracks"].get("items", [])
                    for t in tracks:
                        # Album track items lack album info, enrich them
                        t["album"] = {
                            "name": album.get("name"),
                            "images": album.get("images", []),
                            "id": album.get("id"),
                        }
                        results.append(self._track_to_release(t))
        elif q:
            tracks = await self.search_tracks(q, limit=kwargs.get("limit", 20))
            for t in tracks:
                results.append(self._track_to_release(t))

        return results

    def _track_to_release(self, track: dict[str, Any]) -> dict[str, Any]:
        """Convert a Spotify track object into an indexer release dict."""
        track_id = track.get("id", "")
        artists = ", ".join(
            a.get("name", "") for a in track.get("artists", [])
        )
        title = track.get("name", "Unknown")
        album_name = ""
        album_images = []
        album_data = track.get("album", {})
        if album_data:
            album_name = album_data.get("name", "")
            album_images = album_data.get("images", [])

        duration_ms = track.get("duration_ms", 0)
        # Estimate size: ~10MB per 3 min track at 320kbps
        estimated_size = int((duration_ms / 1000) * 40000) if duration_ms else 0

        return {
            "title": f"{artists} - {title}" if artists else title,
            "link": f"https://open.spotify.com/track/{track_id}",
            "size": estimated_size,
            "indexer_id": "spotify",
            "source": "spotify",
            "spotify_id": track_id,
            "artist": artists,
            "album": album_name,
            "duration_ms": duration_ms,
            "poster": album_images[0].get("url") if album_images else None,
        }

    async def close(self) -> None:
        """Clean up plugin resources."""
        if self.client:
            await self.client.aclose()

    async def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Validate Spotify configuration by testing the credentials.

        Args:
            config: Configuration dictionary with 'client_id' and 'client_secret'

        Returns:
            dict: Validation result with 'valid' (bool), 'errors' (list of str)
        """
        errors = []

        client_id = config.get("client_id", "").strip()
        client_secret = config.get("client_secret", "").strip()

        if not client_id:
            errors.append("Spotify Client ID is required")
        if not client_secret:
            errors.append("Spotify Client Secret is required")

        if errors:
            return {"valid": False, "errors": errors}

        try:
            test_client = httpx.AsyncClient()
            response = await test_client.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
            )
            await test_client.aclose()

            if response.status_code == 401:
                errors.append("Invalid Spotify credentials - authentication failed")
            elif response.status_code != 200:
                errors.append(f"Spotify API returned status code {response.status_code}")
        except httpx.TimeoutException:
            errors.append("Connection to Spotify API timed out")
        except httpx.HTTPError as e:
            errors.append(f"Failed to connect to Spotify API: {str(e)}")
        except Exception as e:
            errors.append(f"Unexpected error while validating Spotify credentials: {str(e)}")

        return {"valid": len(errors) == 0, "errors": errors}


# Export plugin class for loader
PLUGIN_CLASS = Spotify
