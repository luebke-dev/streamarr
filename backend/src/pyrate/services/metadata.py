"""Metadata service for managing metadata provider configurations."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.services.settings import SettingsService

logger = logging.getLogger(__name__)

# Registry of all metadata providers
METADATA_PROVIDERS: dict[str, dict[str, Any]] = {
    "tmdb": {
        "name": "TMDB",
        "description": "The Movie Database — metadata for movies and TV shows",
        "icon": "mdi-movie-open",
        "module": "pyrate.metadata.tmdb",
        "class_name": "TMDB",
        "media_types": ["movies", "shows"],
        "capabilities": {
            "search": True,
            "details": True,
            "identify": True,
            "remote_images": True,
            "translations": True,
            "trending": True,
            "audio_identification": False,
        },
    },
    "tvdb": {
        "name": "TheTVDB",
        "description": "TheTVDB — metadata for TV shows",
        "icon": "mdi-television-classic",
        "module": "pyrate.metadata.tvdb",
        "class_name": "TVDB",
        "media_types": ["shows"],
        "capabilities": {
            "search": True,
            "details": True,
            "identify": True,
            "remote_images": True,
            "translations": False,
            "trending": False,
            "audio_identification": False,
        },
    },
    "igdb": {
        "name": "IGDB",
        "description": "Internet Game Database — metadata for games",
        "icon": "mdi-gamepad-variant",
        "module": "pyrate.metadata.igdb",
        "class_name": "IGDB",
        "media_types": ["games"],
        "capabilities": {
            "search": True,
            "details": True,
            "identify": True,
            "remote_images": True,
            "translations": False,
            "trending": True,
            "audio_identification": False,
        },
    },
    "spotify": {
        "name": "Spotify",
        "description": "Spotify — metadata for music, albums, and artists",
        "icon": "mdi-spotify",
        "module": "pyrate.metadata.spotify",
        "class_name": "Spotify",
        "media_types": ["music"],
        "capabilities": {
            "search": True,
            "details": True,
            "identify": True,
            "remote_images": True,
            "translations": False,
            "trending": False,
            "audio_identification": False,
        },
    },
    "musicbrainz": {
        "name": "MusicBrainz",
        "description": "MusicBrainz — free music metadata database",
        "icon": "mdi-music-box",
        "module": "pyrate.metadata.musicbrainz",
        "class_name": "MusicBrainz",
        "media_types": ["music"],
        "capabilities": {
            "search": True,
            "details": True,
            "identify": True,
            "remote_images": True,
            "translations": False,
            "trending": False,
            "audio_identification": False,
        },
    },
    "shazam": {
        "name": "Shazam",
        "description": "Shazam — identify songs from audio",
        "icon": "mdi-waveform",
        "module": "pyrate.metadata.shazam",
        "class_name": "ShazamProvider",
        "media_types": ["music"],
        "capabilities": {
            "search": False,
            "details": True,
            "identify": True,
            "remote_images": True,
            "translations": False,
            "trending": False,
            "audio_identification": True,
        },
    },
}


def _get_provider_class(domain: str):
    """Get a metadata provider class by domain."""
    import importlib

    info = METADATA_PROVIDERS.get(domain)
    if not info:
        raise ValueError(f"Unknown metadata provider: {domain}")

    module = importlib.import_module(info["module"])
    return getattr(module, info["class_name"])


def _get_schema(domain: str) -> dict[str, Any]:
    """Get config schema without instantiating the provider."""
    cls = _get_provider_class(domain)
    # Create bare instance to call get_config_schema without __init__
    instance = object.__new__(cls)
    return instance.get_config_schema()


def _get_provider_instance(domain: str, config: dict[str, Any]):
    """Instantiate a metadata provider by domain with config."""
    cls = _get_provider_class(domain)
    return cls(**config)


class MetadataService:
    """Service for managing metadata provider configurations."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = SettingsService(db)

    def list_providers(self) -> list[dict[str, Any]]:
        """List all available metadata providers."""
        result = []
        for domain, info in METADATA_PROVIDERS.items():
            schema = _get_schema(domain)
            result.append({
                "domain": domain,
                "name": info["name"],
                "description": info["description"],
                "icon": info["icon"],
                "media_types": info["media_types"],
                "capabilities": info.get("capabilities", {}),
                "has_config": bool(schema),
                "config_schema": schema,
            })
        return result

    def get_provider_capabilities(self, domain: str) -> dict[str, Any]:
        """Get declared provider capabilities for UI and admin tooling."""
        info = METADATA_PROVIDERS[domain]
        return {
            "domain": domain,
            "name": info["name"],
            "media_types": info["media_types"],
            "capabilities": dict(info.get("capabilities", {})),
        }

    def get_provider_schema(self, domain: str) -> dict[str, Any]:
        """Get the config schema for a provider."""
        return _get_schema(domain)

    async def get_provider_config(self, domain: str) -> dict[str, Any]:
        """Get current config for a provider from Settings table."""
        schema = self.get_provider_schema(domain)
        config = {}
        for key in schema:
            value = await self.settings.get(f"plugin.{domain}.{key}")
            if value is not None:
                config[key] = value
        return config

    async def is_configured(self, domain: str) -> bool:
        """Check if a provider has all required config fields set."""
        schema = self.get_provider_schema(domain)
        config = await self.get_provider_config(domain)
        for key, field in schema.items():
            if field.get("required") and not config.get(key):
                return False
        return True

    async def set_provider_config(self, domain: str, config: dict[str, Any]) -> None:
        """Save config for a provider to Settings table."""
        if domain not in METADATA_PROVIDERS:
            raise ValueError(f"Unknown metadata provider: {domain}")

        schema = self.get_provider_schema(domain)
        for key, value in config.items():
            if key in schema:
                await self.settings.set(f"plugin.{domain}.{key}", value)

    async def validate_provider_config(
        self, domain: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate config for a provider."""
        provider = _get_provider_instance(domain, config)
        try:
            result = await provider.validate_config(config)
            return result
        finally:
            await provider.close()

    async def test_connection(
        self, domain: str, config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Test connection to a provider."""
        if config is None:
            config = await self.get_provider_config(domain)

        if not config:
            return {"success": False, "error": "No configuration found"}

        provider = _get_provider_instance(domain, config)
        try:
            result = await provider.validate_config(config)
            return {
                "success": result.get("valid", False),
                "errors": result.get("errors", []),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            await provider.close()

    async def search_identify_candidates(
        self,
        *,
        domain: str,
        query: str,
        media_type: str,
        year: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search a configured provider for live identify candidates."""
        if domain not in METADATA_PROVIDERS:
            raise ValueError(f"Unknown metadata provider: {domain}")

        config = await self.get_provider_config(domain)
        provider = _get_provider_instance(domain, config)
        try:
            results = await provider.search(
                query,
                media_type=media_type,
                year=year,
                limit=limit,
            )
        finally:
            await provider.close()

        candidates: list[dict[str, Any]] = []
        for raw in results[:limit]:
            if not isinstance(raw, dict):
                continue
            provider_id = raw.get("provider_id") or raw.get("id") or raw.get("guid")
            title = raw.get("title") or raw.get("name")
            if not provider_id or not title:
                continue
            candidates.append(
                {
                    "provider": domain,
                    "provider_id": str(provider_id),
                    "title": str(title),
                    "original_title": raw.get("original_title"),
                    "description": raw.get("description")
                    or raw.get("overview")
                    or raw.get("summary"),
                    "tagline": raw.get("tagline"),
                    "release_date": raw.get("release_date") or raw.get("first_air_date"),
                    "poster_path": raw.get("poster_path") or raw.get("poster_url"),
                    "backdrop_path": raw.get("backdrop_path")
                    or raw.get("backdrop_url"),
                    "score": raw.get("score") or raw.get("vote_average"),
                }
            )
        return candidates

    async def search_remote_images(
        self,
        *,
        domain: str,
        provider_id: str,
        media_type: str,
    ) -> list[dict[str, Any]]:
        """Fetch remote image candidates from a configured provider."""
        if domain not in METADATA_PROVIDERS:
            raise ValueError(f"Unknown metadata provider: {domain}")

        config = await self.get_provider_config(domain)
        provider = _get_provider_instance(domain, config)
        try:
            if hasattr(provider, "get_normalized_details"):
                details = await provider.get_normalized_details(
                    provider_id,
                    media_type=media_type,
                )
                raw_details = getattr(details, "extra", {}) or {}
                poster_path = getattr(details, "poster_path", None)
                backdrop_path = getattr(details, "backdrop_path", None)
            else:
                raw_details = await provider.get_details(provider_id, media_type=media_type)
                poster_path = raw_details.get("poster_path") or raw_details.get("poster_url")
                backdrop_path = raw_details.get("backdrop_path") or raw_details.get("backdrop_url")
        finally:
            await provider.close()

        images: list[dict[str, Any]] = []
        if poster_path:
            images.append(
                {
                    "provider": domain,
                    "provider_id": f"{provider_id}:poster",
                    "image_type": "poster",
                    "url": poster_path,
                    "thumbnail_url": poster_path,
                    "score": 100,
                }
            )
        if backdrop_path:
            images.append(
                {
                    "provider": domain,
                    "provider_id": f"{provider_id}:backdrop",
                    "image_type": "backdrop",
                    "url": backdrop_path,
                    "thumbnail_url": backdrop_path,
                    "score": 90,
                }
            )

        raw_images = raw_details.get("images") if isinstance(raw_details, dict) else None
        if isinstance(raw_images, dict):
            for key, image_type in (("posters", "poster"), ("backdrops", "backdrop")):
                for index, raw_image in enumerate(raw_images.get(key) or []):
                    if not isinstance(raw_image, dict):
                        continue
                    path = raw_image.get("file_path") or raw_image.get("url")
                    if not path:
                        continue
                    url = (
                        f"https://image.tmdb.org/t/p/original{path}"
                        if isinstance(path, str) and path.startswith("/")
                        else path
                    )
                    images.append(
                        {
                            "provider": domain,
                            "provider_id": f"{provider_id}:{image_type}:{index}",
                            "image_type": image_type,
                            "url": url,
                            "thumbnail_url": url,
                            "width": raw_image.get("width"),
                            "height": raw_image.get("height"),
                            "language": raw_image.get("iso_639_1"),
                            "score": raw_image.get("vote_average"),
                        }
                    )
        return images
