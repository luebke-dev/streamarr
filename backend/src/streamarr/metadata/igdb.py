import logging
import time
from typing import Any

import httpx

from streamarr.metadata.base import MetadataBase, NormalizedMetadata

logger = logging.getLogger(__name__)


class IGDB(MetadataBase):
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
        self.base_url = "https://api.igdb.com/v4"
        self.auth_url = "https://id.twitch.tv/oauth2/token"

        if client is None:
            self.client = httpx.AsyncClient()
        else:
            self.client = client

    def get_name(self) -> str:
        """Get the plugin name."""
        return "IGDB"

    def get_config_schema(self) -> dict[str, Any]:
        """Get configuration schema for IGDB."""
        return {
            "client_id": {
                "type": "string",
                "label": "Client ID",
                "hint": "Your Twitch/IGDB Client ID",
                "required": True,
                "placeholder": "Enter your Twitch Client ID",
            },
            "client_secret": {
                "type": "password",
                "label": "Client Secret",
                "hint": "Your Twitch/IGDB Client Secret",
                "required": True,
                "placeholder": "Enter your Twitch Client Secret",
                "info_text": "Get credentials at: https://dev.twitch.tv/console/apps",
                "info_link": "https://dev.twitch.tv/console/apps",
            },
        }

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """
        Search for games.

        Args:
            query: Search query string
            **kwargs: Additional parameters like 'limit'

        Returns:
            list[dict]: Search results
        """
        limit = kwargs.get("limit", 10)
        return await self.search_games(query, limit)

    async def get_details(self, media_id: str | int, **kwargs) -> dict[str, Any]:
        """
        Get detailed information about a game.

        Args:
            media_id: The IGDB game ID
            **kwargs: Additional parameters

        Returns:
            dict: Detailed game information
        """
        return await self.get_game_details(int(media_id))

    async def _authenticate(self) -> bool:
        """Authenticate with Twitch OAuth2 to get access token for IGDB API"""
        try:
            response = await self.client.post(
                self.auth_url,
                params={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()

            data = response.json()
            self.access_token = data["access_token"]
            # Set expiry time to current time + expires_in seconds minus 5 minutes buffer
            self.token_expires_at = time.time() + data["expires_in"] - 300

            logger.info("Successfully authenticated with IGDB API")
            return True

        except Exception as e:
            logger.error(f"Failed to authenticate with IGDB API: {e}")
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

    async def _request(self, endpoint: str, query: str) -> dict[str, Any]:
        """Make a request to the IGDB API"""
        if not await self._ensure_authenticated():
            return {}

        try:
            response = await self.client.post(
                f"{self.base_url}/{endpoint}",
                headers={
                    "Client-ID": self.client_id,
                    "Authorization": f"Bearer {self.access_token}",
                    "Accept": "application/json",
                },
                data=query,
            )
            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error when requesting {endpoint}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error when requesting {endpoint}: {e}")
            return []

    async def search_games(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search for games by name"""
        # IGDB's Apicalypse dialect uses double-quoted strings and ; as
        # statement terminator. Escape both so a title containing quotes can't
        # break out of the search literal and inject new statements.
        safe_query = query.replace("\\", "\\\\").replace('"', '\\"')
        safe_limit = max(1, min(int(limit), 500))
        igdb_query = f'''
        search "{safe_query}";
        fields id, name, summary, storyline, first_release_date, rating, rating_count,
               cover.url, cover.image_id, screenshots.url, screenshots.image_id,
               genres.name, platforms.name, involved_companies.company.name,
               involved_companies.developer, involved_companies.publisher,
               external_games.category, external_games.uid;
        limit {safe_limit};
        '''

        result = await self._request("games", igdb_query)
        return result if isinstance(result, list) else []

    async def get_normalized_details(
        self, media_id: str | int, media_type: str = "game", **kwargs
    ) -> NormalizedMetadata:
        """Fetch game details and return in normalized format."""
        raw = await self.get_game_details(int(media_id))
        if not raw:
            return NormalizedMetadata()

        # IGDB cover URL needs transformation
        cover = raw.get("cover", {})
        poster_url = None
        if cover and cover.get("image_id"):
            poster_url = f"https://images.igdb.com/igdb/image/upload/t_cover_big/{cover['image_id']}.jpg"

        # Use first screenshot as backdrop
        backdrop_url = None
        screenshots = raw.get("screenshots", [])
        if screenshots and screenshots[0].get("image_id"):
            backdrop_url = f"https://images.igdb.com/igdb/image/upload/t_screenshot_big/{screenshots[0]['image_id']}.jpg"

        # Convert IGDB timestamp to date string
        release_date = None
        if raw.get("first_release_date"):
            from datetime import datetime, UTC
            release_date = datetime.fromtimestamp(raw["first_release_date"], tz=UTC).strftime("%Y-%m-%d")

        return NormalizedMetadata(
            title=raw.get("name"),
            description=raw.get("summary") or raw.get("storyline"),
            release_date=release_date,
            poster_path=poster_url,
            backdrop_path=backdrop_url,
            extra=raw,
        )

    async def get_game_details(self, game_id: int) -> dict[str, Any]:
        """Get detailed information about a specific game"""
        # Coerce so a caller passing a str that sneaks through type hints
        # can't inject extra statements via ``id = 1; drop ...``.
        safe_id = int(game_id)
        igdb_query = f"""
        fields id, name, summary, storyline, first_release_date, rating, rating_count,
               cover.url, cover.image_id, screenshots.url, screenshots.image_id,
               genres.name, platforms.name, platforms.platform_logo.image_id,
               involved_companies.company.name,
               involved_companies.developer, involved_companies.publisher,
               external_games.category, external_games.uid, websites.category, websites.url,
               release_dates.date, release_dates.platform.name, release_dates.region,
               game_modes.name, player_perspectives.name, themes.name,
               age_ratings.category, age_ratings.rating;
        where id = {safe_id};
        """

        result = await self._request("games", igdb_query)
        return result[0] if isinstance(result, list) and len(result) > 0 else {}

    @staticmethod
    def _safe_limit(limit: int) -> int:
        return max(1, min(int(limit), 500))

    @staticmethod
    def _escape_str(value: str) -> str:
        """Escape a string literal for IGDB's Apicalypse query language."""
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    async def get_trending_games(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get trending games based on hype count (community anticipation)."""
        safe_limit = self._safe_limit(limit)
        igdb_query = f"""
        fields id, name, summary, first_release_date, hypes,
               cover.url, cover.image_id, screenshots.url, screenshots.image_id,
               genres.name, platforms.name;
        where hypes != null;
        sort hypes desc;
        limit {safe_limit};
        """

        result = await self._request("games", igdb_query)
        return result if isinstance(result, list) else []

    async def get_popular_games(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get popular games based on rating and rating count"""
        safe_limit = self._safe_limit(limit)
        igdb_query = f"""
        fields id, name, summary, first_release_date, rating, rating_count,
               cover.url, cover.image_id, genres.name, platforms.name;
        where rating_count > 10 & rating > 70;
        sort rating_count desc;
        limit {safe_limit};
        """

        result = await self._request("games", igdb_query)
        return result if isinstance(result, list) else []

    async def get_upcoming_games(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get upcoming games"""
        safe_limit = self._safe_limit(limit)
        current_timestamp = int(time.time())
        igdb_query = f"""
        fields id, name, summary, first_release_date, rating, rating_count,
               cover.url, cover.image_id, genres.name, platforms.name;
        where first_release_date > {current_timestamp};
        sort first_release_date asc;
        limit {safe_limit};
        """

        result = await self._request("games", igdb_query)
        return result if isinstance(result, list) else []

    async def get_recently_released_games(
        self, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get recently released games (last 6 months)"""
        safe_limit = self._safe_limit(limit)
        current_timestamp = int(time.time())
        six_months_ago = current_timestamp - (
            6 * 30 * 24 * 60 * 60
        )  # Approximately 6 months

        igdb_query = f"""
        fields id, name, summary, first_release_date, rating, rating_count,
               cover.url, cover.image_id, genres.name, platforms.name;
        where first_release_date > {six_months_ago} & first_release_date < {current_timestamp};
        sort first_release_date desc;
        limit {safe_limit};
        """

        result = await self._request("games", igdb_query)
        return result if isinstance(result, list) else []

    async def get_games_by_genre(
        self, genre_name: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get games by genre"""
        safe_limit = self._safe_limit(limit)
        safe_genre = self._escape_str(genre_name)
        igdb_query = f'''
        fields id, name, summary, first_release_date, rating, rating_count,
               cover.url, cover.image_id, genres.name, platforms.name;
        where genres.name = "{safe_genre}";
        sort rating desc;
        limit {safe_limit};
        '''

        result = await self._request("games", igdb_query)
        return result if isinstance(result, list) else []

    async def get_games_by_platform(
        self, platform_name: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get games by platform"""
        safe_limit = self._safe_limit(limit)
        safe_platform = self._escape_str(platform_name)
        igdb_query = f'''
        fields id, name, summary, first_release_date, rating, rating_count,
               cover.url, cover.image_id, genres.name, platforms.name;
        where platforms.name = "{safe_platform}";
        sort rating desc;
        limit {safe_limit};
        '''

        result = await self._request("games", igdb_query)
        return result if isinstance(result, list) else []

    async def get_game_localizations(self, game_id: int) -> list[dict[str, Any]]:
        """Get localized names for a game"""
        safe_id = int(game_id)
        igdb_query = f"""
        fields name, region.name, region.identifier;
        where game = {safe_id};
        """

        result = await self._request("game_localizations", igdb_query)
        return result if isinstance(result, list) else []

    async def close(self):
        """Close the HTTP client"""
        if self.client:
            await self.client.aclose()

    async def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Validate IGDB configuration.

        Args:
            config: Configuration dictionary with 'client_id' and 'client_secret'

        Returns:
            dict: Validation result with 'valid' (bool), 'errors' (list of str)
        """
        errors = []

        # Check if client_id is provided
        client_id = config.get("client_id", "").strip()
        if not client_id:
            errors.append("IGDB client ID is required")

        # Check if client_secret is provided
        client_secret = config.get("client_secret", "").strip()
        if not client_secret:
            errors.append("IGDB client secret is required")

        if errors:
            return {"valid": False, "errors": errors}

        # Test the credentials by attempting authentication
        try:
            test_client = httpx.AsyncClient(timeout=10.0)
            response = await test_client.post(
                "https://id.twitch.tv/oauth2/token",
                params={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                },
            )
            await test_client.aclose()

            if response.status_code == 400:
                errors.append("Invalid IGDB credentials")
            elif response.status_code == 401:
                errors.append(
                    "IGDB authentication failed - invalid client ID or secret"
                )
            elif response.status_code != 200:
                errors.append(f"IGDB API returned status code {response.status_code}")
        except httpx.TimeoutException:
            errors.append("Connection to IGDB API timed out")
        except httpx.HTTPError as e:
            errors.append(f"Failed to connect to IGDB API: {str(e)}")
        except Exception as e:
            errors.append(
                f"Unexpected error while validating IGDB credentials: {str(e)}"
            )

        return {"valid": len(errors) == 0, "errors": errors}


# Export plugin class for loader
PLUGIN_CLASS = IGDB
