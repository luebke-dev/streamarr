"""
MusicBrainz metadata plugin.

Provides artist, album (release-group), and track metadata from the
MusicBrainz open music encyclopedia. No API key required — only a
User-Agent header and 1 request/second rate limiting.

Cover art is fetched from the Cover Art Archive (coverartarchive.org).
"""

import asyncio
import logging
from typing import Any

import httpx

from pyrate.metadata.base import MetadataBase
from pyrate.utils.http import make_async_client

logger = logging.getLogger(__name__)

# MusicBrainz requires 1 req/s rate limiting. The lock keeps two concurrent
# coroutines from racing the timestamp check and each firing a request in the
# same second.
_RATE_LIMIT_DELAY = 1.1  # seconds between requests
_last_request_time = 0.0
_rate_limit_lock = asyncio.Lock()


class MusicBrainz(MetadataBase):
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = "https://musicbrainz.org/ws/2"
        self.cover_art_url = "https://coverartarchive.org"
        self.client = client or make_async_client()

    def get_name(self) -> str:
        return "MusicBrainz"

    def get_config_schema(self) -> dict[str, Any]:
        return {}

    async def _request(
        self, endpoint: str, params: dict | None = None
    ) -> dict[str, Any]:
        """Make a rate-limited request to the MusicBrainz API."""
        import time

        global _last_request_time

        # Rate limiting: 1 request per second. The async lock serialises the
        # check-then-update so two coroutines can't both see "elapsed > delay"
        # and fire simultaneously.
        async with _rate_limit_lock:
            now = time.monotonic()
            elapsed = now - _last_request_time
            if elapsed < _RATE_LIMIT_DELAY:
                await asyncio.sleep(_RATE_LIMIT_DELAY - elapsed)
            _last_request_time = time.monotonic()

        if params is None:
            params = {}
        params["fmt"] = "json"

        try:
            response = await self.client.get(
                f"{self.base_url}/{endpoint}",
                params=params,
                headers={
                    "User-Agent": "pyrate.media/1.0 (https://pyrate.media)",
                    "Accept": "application/json",
                },
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                logger.warning("MusicBrainz rate limited, retrying after delay")
                await asyncio.sleep(2.0)
                return await self._request(endpoint, params)
            logger.error("MusicBrainz API error on %s: %s", endpoint, e)
            return {}
        except Exception as e:
            logger.error("MusicBrainz request error on %s: %s", endpoint, e)
            return {}

    # ==================== Search ====================

    async def search_artists(
        self, query: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search for artists by name."""
        result = await self._request(
            "artist",
            params={"query": query, "limit": limit},
        )
        artists = result.get("artists", [])
        return [
            {
                "name": a.get("name", ""),
                "mbid": a.get("id", ""),
                "type": a.get("type", ""),
                "country": a.get("country", ""),
                "disambiguation": a.get("disambiguation", ""),
                "score": a.get("score", 0),
                "tags": [t.get("name") for t in a.get("tags", [])],
            }
            for a in artists
        ]

    async def search_albums(
        self, query: str, artist: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search for albums (release groups) by name, optionally filtered by artist."""
        q = query
        if artist:
            q = f'releasegroup:"{query}" AND artist:"{artist}"'

        result = await self._request(
            "release-group",
            params={"query": q, "limit": limit},
        )
        groups = result.get("release-groups", [])
        return [
            {
                "title": rg.get("title", ""),
                "mbid": rg.get("id", ""),
                "primary_type": rg.get("primary-type", ""),
                "first_release_date": rg.get("first-release-date", ""),
                "artist_name": rg["artist-credit"][0]["name"]
                if rg.get("artist-credit")
                else "",
                "artist_mbid": rg["artist-credit"][0]["artist"]["id"]
                if rg.get("artist-credit")
                and rg["artist-credit"][0].get("artist")
                else "",
                "score": rg.get("score", 0),
            }
            for rg in groups
        ]

    # ==================== Details ====================

    async def get_artist_details(self, mbid: str) -> dict[str, Any]:
        """Get detailed artist information by MBID."""
        result = await self._request(
            f"artist/{mbid}",
            params={"inc": "tags+release-groups"},
        )
        if not result or "error" in result:
            return {}

        return {
            "name": result.get("name", ""),
            "mbid": result.get("id", ""),
            "type": result.get("type", ""),
            "country": result.get("country", ""),
            "disambiguation": result.get("disambiguation", ""),
            "begin_date": result.get("life-span", {}).get("begin"),
            "end_date": result.get("life-span", {}).get("end"),
            "tags": [t.get("name") for t in result.get("tags", [])],
            "release_groups": [
                {
                    "title": rg.get("title", ""),
                    "mbid": rg.get("id", ""),
                    "primary_type": rg.get("primary-type", ""),
                    "first_release_date": rg.get("first-release-date", ""),
                }
                for rg in result.get("release-groups", [])
            ],
        }

    async def get_album_details(self, mbid: str) -> dict[str, Any]:
        """Get detailed album (release-group) information by MBID.

        Returns the release group details. To get tracks, use get_album_tracks()
        which fetches the first release of this group.
        """
        result = await self._request(
            f"release-group/{mbid}",
            params={"inc": "artists+tags+releases"},
        )
        if not result or "error" in result:
            return {}

        artists = result.get("artist-credit", [])
        artist_names = [a.get("name", "") for a in artists if a.get("name")]

        # Get the first official release for track listing
        releases = result.get("releases", [])
        first_release_mbid = releases[0]["id"] if releases else None

        return {
            "title": result.get("title", ""),
            "mbid": result.get("id", ""),
            "primary_type": result.get("primary-type", ""),
            "first_release_date": result.get("first-release-date", ""),
            "artists": artist_names,
            "artist_mbid": artists[0]["artist"]["id"]
            if artists and artists[0].get("artist")
            else "",
            "tags": [t.get("name") for t in result.get("tags", [])],
            "first_release_mbid": first_release_mbid,
            "release_count": len(releases),
        }

    async def get_album_tracks(self, release_group_mbid: str) -> list[dict[str, Any]]:
        """Get tracks for an album by fetching the first release of the release-group."""
        # First get the release group to find a release
        rg = await self.get_album_details(release_group_mbid)
        release_mbid = rg.get("first_release_mbid")
        if not release_mbid:
            return []

        # Fetch the release with recordings
        result = await self._request(
            f"release/{release_mbid}",
            params={"inc": "recordings"},
        )
        if not result or "error" in result:
            return []

        tracks = []
        for medium in result.get("media", []):
            disc_number = medium.get("position", 1)
            for track in medium.get("tracks", []):
                recording = track.get("recording", {})
                tracks.append(
                    {
                        "title": recording.get("title", track.get("title", "")),
                        "mbid": recording.get("id", ""),
                        "position": track.get("position", 0),
                        "disc_number": disc_number,
                        "length_ms": recording.get("length") or track.get("length"),
                    }
                )

        return tracks

    # ==================== Cover Art ====================

    async def get_cover_art_url(self, release_group_mbid: str) -> str | None:
        """Get the front cover art URL for a release group from Cover Art Archive."""
        # Cover Art Archive redirects to the image — just build the URL
        return f"{self.cover_art_url}/release-group/{release_group_mbid}/front-500"

    # ==================== Search interface (MetadataBase) ====================

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """Search for artists (primary search interface)."""
        search_type = kwargs.get("search_type", "artist")
        if search_type == "album":
            return await self.search_albums(query, artist=kwargs.get("artist"))
        return await self.search_artists(query)

    async def get_details(self, media_id: str | int, **kwargs) -> dict[str, Any]:
        """Get details by MBID."""
        media_type = kwargs.get("media_type", "artist")
        if media_type == "album":
            return await self.get_album_details(str(media_id))
        return await self.get_artist_details(str(media_id))

    async def close(self) -> None:
        """Clean up resources."""
        if self.client:
            await self.client.aclose()

    async def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate MusicBrainz configuration (no credentials needed)."""
        # Test connectivity by doing a simple search
        try:
            test_client = httpx.AsyncClient()
            response = await test_client.get(
                f"{self.base_url}/artist",
                params={"query": "test", "limit": 1, "fmt": "json"},
                headers={
                    "User-Agent": "pyrate.media/1.0 (https://pyrate.media)",
                },
                timeout=10.0,
            )
            await test_client.aclose()
            if response.status_code == 200:
                return {"valid": True, "errors": []}
            return {
                "valid": False,
                "errors": [f"MusicBrainz API returned status {response.status_code}"],
            }
        except Exception as e:
            return {"valid": False, "errors": [f"Connection failed: {e}"]}


# Export plugin class for loader
PLUGIN_CLASS = MusicBrainz
