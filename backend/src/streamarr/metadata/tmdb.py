import logging
from typing import Any

import httpx

from streamarr.metadata.base import MetadataBase, NormalizedMetadata
from streamarr.utils.http import make_async_client
from streamarr.utils.retry import http_with_retries

logger = logging.getLogger(__name__)

# Fallback language when a caller doesn't pass one. Callers that have the
# configured system locale (SettingsService.get_locale) should pass it; this is
# only the last-resort default. (metadata stays free of a services import.)
_DEFAULT_LANGUAGE = "de-DE"


def _country_of(language: str | None) -> str:
    """Country code implied by a locale (``de-DE`` → ``DE``)."""
    if language and "-" in language:
        return language.rsplit("-", 1)[-1].upper()
    return _DEFAULT_LANGUAGE.rsplit("-", 1)[-1]


class TMDB(MetadataBase):
    # TMDB allows ~40 requests per 10 seconds
    DEFAULT_MAX_RETRIES = 5
    DEFAULT_RETRY_DELAY = 1.0  # Base delay in seconds

    def __init__(
        self,
        api_key: str,
        language: str = _DEFAULT_LANGUAGE,
        client: httpx.AsyncClient | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> None:
        self.base_url = "https://api.themoviedb.org/3"
        self.api_key = api_key
        self.language = language
        self.client = client or make_async_client(base_url=self.base_url)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._owns_client = client is None

    def get_name(self) -> str:
        """Get the plugin name."""
        return "TMDB"

    def get_config_schema(self) -> dict[str, Any]:
        """Get configuration schema for TMDB."""
        return {
            "api_key": {
                "type": "password",
                "label": "API Key",
                "hint": "Your TMDB API Key (Bearer Token)",
                "required": True,
                "placeholder": "Enter your TMDB API key",
                "info_text": "Get API Key at: https://www.themoviedb.org/settings/api",
                "info_link": "https://www.themoviedb.org/settings/api",
            }
        }

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """
        Search for movies or shows.

        Args:
            query: Search query string
            **kwargs: Additional parameters like 'year', 'media_type' (movie/tv)

        Returns:
            list[dict]: Search results
        """
        media_type = kwargs.get("media_type", "movie")
        year = kwargs.get("year")
        return await self.search_movies(query, year) if media_type == "movie" else []

    async def get_details(self, media_id: str | int, **kwargs) -> dict[str, Any]:
        """
        Get detailed information about a movie or show.

        Args:
            media_id: The TMDB ID
            **kwargs: Additional parameters like 'media_type' (movie/tv)

        Returns:
            dict: Detailed media information
        """
        media_type = kwargs.get("media_type", "movie")
        if media_type == "movie":
            return await self.get_movie_details(str(media_id))
        else:
            return await self.get_show_details(str(media_id))

    async def _request(self, endpoint: str, params: dict | None = None):
        """Call TMDB and return the parsed JSON, or {} on failure / exhaustion.

        Retry/backoff/rate-limit handling lives in utils.retry.http_with_retries;
        this wrapper just builds the request closure and unwraps the optional
        ``result`` envelope some endpoints use.
        """
        async def do_request() -> httpx.Response:
            return await self.client.get(
                f"{self.base_url}/{endpoint}",
                params={"language": self.language, **(params or {})},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )

        try:
            response = await http_with_retries(
                do_request,
                max_retries=self.max_retries,
                base_delay=self.retry_delay,
                log_label=f"TMDB {endpoint}",
            )
        except Exception as exc:
            logger.warning("TMDB request failed for %s: %s", endpoint, exc)
            return {}
        if response is None or response.status_code >= 400:
            if response is not None:
                logger.warning(
                    "TMDB request failed for %s: HTTP %s", endpoint, response.status_code,
                )
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("TMDB invalid JSON for %s: %s", endpoint, exc)
            return {}
        return data.get("result", data) if isinstance(data, dict) else data

    async def get_trending(self, media_type: str, **kwargs) -> list[dict]:
        """
        Get trending media items.

        Args:
            media_type: Type of media ('movie' or 'show')
            **kwargs: Additional parameters

        Returns:
            list[dict]: List of trending media items
        """
        if media_type.lower() in ["show", "shows", "tv", "series"]:
            return await self.get_trending_shows()
        elif media_type.lower() in ["movie", "movies", "film", "films"]:
            return await self.get_trending_movies()
        else:
            raise ValueError(f"Unsupported media type: {media_type}")

    async def get_trending_shows(self):
        logger.info("Fetching trending shows")
        result = await self._request(endpoint="trending/tv/day")
        return result

    async def get_trending_movies(self):
        result = await self._request(endpoint="trending/movie/day")
        return result

    async def get_movie_details(self, id: str, include_external_ids: bool = True):
        logger.info(f"Fetching details for movie {id}")
        params = {}
        append_parts = []
        if include_external_ids:
            append_parts.append("external_ids")
        append_parts.append("credits")
        append_parts.append("release_dates")
        if append_parts:
            params["append_to_response"] = ",".join(append_parts)
        result = await self._request(
            endpoint=f"movie/{id}", params=params if params else None
        )
        return result

    async def get_movie_credits(self, id: str):
        result = await self._request(endpoint=f"movie/{id}/credits")
        return result

    async def get_movie_external_ids(self, id: str):
        result = await self._request(endpoint=f"movie/{id}/external_ids")
        return result

    async def get_show_credits(self, id: str):
        result = await self._request(endpoint=f"tv/{id}/aggregate_credits")
        return result

    async def get_movie_similar(self, id: str, page: int = 1):
        return await self._request(
            endpoint=f"movie/{id}/similar", params={"page": page}
        )

    async def get_movie_recommendations(self, id: str, page: int = 1):
        return await self._request(
            endpoint=f"movie/{id}/recommendations", params={"page": page}
        )

    async def get_show_similar(self, id: str, page: int = 1):
        return await self._request(
            endpoint=f"tv/{id}/similar", params={"page": page}
        )

    async def get_show_recommendations(self, id: str, page: int = 1):
        return await self._request(
            endpoint=f"tv/{id}/recommendations", params={"page": page}
        )

    async def get_show_details(self, id: str, include_external_ids: bool = True):
        params = {}
        append_parts = []
        if include_external_ids:
            append_parts.append("external_ids")
        append_parts.append("aggregate_credits")
        append_parts.append("content_ratings")
        if append_parts:
            params["append_to_response"] = ",".join(append_parts)
        result = await self._request(
            endpoint=f"tv/{id}", params=params if params else None
        )
        return result

    @staticmethod
    def extract_certification(
        details: dict, media_type: str, preferred_country: str = "DE"
    ) -> str | None:
        """Pull the best-matching age-rating string from a TMDB details blob.

        Prefers ``preferred_country`` (from the configured locale), falls back to
        US, then takes the first non-empty cert seen. Works for movies
        (``release_dates.results[*].release_dates[*].certification``) and shows
        (``content_ratings.results[*].rating``).
        """
        preferred = (preferred_country, "US")

        def _first_non_empty(entries: list[str]) -> str | None:
            for cert in entries:
                if cert:
                    return cert
            return None

        if media_type == "movie":
            results = (details.get("release_dates") or {}).get("results") or []
            by_country = {
                r.get("iso_3166_1"): [
                    rd.get("certification", "") for rd in (r.get("release_dates") or [])
                ]
                for r in results
            }
        else:
            results = (details.get("content_ratings") or {}).get("results") or []
            by_country = {
                r.get("iso_3166_1"): [r.get("rating", "")] for r in results
            }

        for country in preferred:
            cert = _first_non_empty(by_country.get(country) or [])
            if cert:
                return cert

        for entries in by_country.values():
            cert = _first_non_empty(entries)
            if cert:
                return cert
        return None

    async def get_normalized_details(
        self, media_id: str | int, media_type: str = "movie", **kwargs
    ) -> NormalizedMetadata:
        """Fetch details and return in normalized format."""
        from streamarr.utils.age_rating import parse_min_age

        if media_type in ("movie", "movies"):
            raw = await self.get_movie_details(media_id)
            cert = self.extract_certification(raw, "movie", _country_of(self.language))
            return NormalizedMetadata(
                title=raw.get("title"),
                original_title=raw.get("original_title"),
                description=raw.get("overview"),
                tagline=raw.get("tagline"),
                release_date=raw.get("release_date"),
                poster_path=raw.get("poster_path"),
                backdrop_path=raw.get("backdrop_path"),
                content_rating=cert,
                min_age=parse_min_age(cert),
                credits=raw.get("credits", {}),
                extra=raw,
            )
        elif media_type in ("tv", "show", "shows"):
            raw = await self.get_show_details(media_id)
            cert = self.extract_certification(raw, "tv", _country_of(self.language))
            return NormalizedMetadata(
                title=raw.get("name"),
                original_title=raw.get("original_name"),
                description=raw.get("overview"),
                tagline=raw.get("tagline"),
                release_date=raw.get("first_air_date"),
                poster_path=raw.get("poster_path"),
                backdrop_path=raw.get("backdrop_path"),
                content_rating=cert,
                min_age=parse_min_age(cert),
                credits=raw.get("aggregate_credits", {}),
                seasons=raw.get("seasons", []),
                extra=raw,
            )
        else:
            raw = await self.get_details(media_id)
            return self._normalize(raw, media_type)

    async def get_show_external_ids(self, id: str):
        result = await self._request(endpoint=f"tv/{id}/external_ids")
        return result

    async def get_show_season(self, id: str, season_number: str):
        result = await self._request(endpoint=f"tv/{id}/season/{season_number}")
        return result

    async def get_popular_shows(self):
        result = await self._request(endpoint="tv/popular")
        return result

    async def get_popular_movies(self):
        result = await self._request(endpoint="movie/popular")
        return result

    async def get_top_rated_movies(self):
        result = await self._request(endpoint="movie/top_rated")
        return result

    async def get_now_playing_movies(self):
        result = await self._request(endpoint="movie/now_playing")
        return result

    async def get_now_playing_shows(self):
        result = await self._request(endpoint="tv/airing_today")
        return result

    async def get_top_rated_shows(self):
        result = await self._request(endpoint="tv/top_rated")
        return result

    async def get_upcoming_movies(self):
        result = await self._request(endpoint="movie/upcoming")
        return result

    async def search_movies(self, query: str, year: int = None):
        params = {"query": query}
        if year:
            params["year"] = year
        result = await self._request(endpoint="search/movie", params=params)
        return result

    async def get_person_details(self, person_id: str):
        """Get detailed person info including biography, birthday, etc."""
        result = await self._request(endpoint=f"person/{person_id}")
        return result

    async def get_person_combined_credits(self, person_id: str):
        """Get all movie and TV credits for a person."""
        result = await self._request(
            endpoint=f"person/{person_id}/combined_credits"
        )
        return result

    async def get_translations(self, tmdb_id: int | str, media_type: str = "movie") -> dict[str, dict]:
        """
        Fetch all available translations for a movie or TV show.

        Args:
            tmdb_id: TMDB ID
            media_type: "movie" or "tv"

        Returns:
            Dict of language_code → {title, description, tagline}
            e.g. {"de": {"title": "...", "description": "..."}, "en": {...}}
        """
        endpoint = f"{media_type}/{tmdb_id}/translations"
        data = await self._request(endpoint)

        result = {}
        for entry in data.get("translations", []):
            iso = entry.get("iso_639_1", "")
            info = entry.get("data", {})
            title = info.get("title") or info.get("name")
            overview = info.get("overview")
            tagline = info.get("tagline")

            # Only store if there's actual translated content
            if title or overview:
                result[iso] = {
                    "title": title,
                    "description": overview,
                    "tagline": tagline,
                }

        return result

    async def close(self) -> None:
        """Clean up plugin resources."""
        if self._owns_client and self.client:
            await self.client.aclose()

    async def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Validate TMDB configuration.

        Args:
            config: Configuration dictionary with 'api_key'

        Returns:
            dict: Validation result with 'valid' (bool), 'errors' (list of str)
        """
        errors = []

        # Check if api_key is provided
        api_key = config.get("api_key", "").strip()
        if not api_key:
            errors.append("TMDB API key is required")
            return {"valid": False, "errors": errors}

        # Test the API key by making a simple request
        try:
            test_client = httpx.AsyncClient(timeout=10.0)
            response = await test_client.get(
                "https://api.themoviedb.org/3/configuration",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            await test_client.aclose()

            if response.status_code == 401:
                errors.append("Invalid TMDB API key - authentication failed")
            elif response.status_code != 200:
                errors.append(f"TMDB API returned status code {response.status_code}")
        except httpx.TimeoutException:
            errors.append("Connection to TMDB API timed out")
        except httpx.HTTPError as e:
            errors.append(f"Failed to connect to TMDB API: {str(e)}")
        except Exception as e:
            errors.append(f"Unexpected error while validating TMDB API key: {str(e)}")

        return {"valid": len(errors) == 0, "errors": errors}


# Export plugin class for loader
PLUGIN_CLASS = TMDB
