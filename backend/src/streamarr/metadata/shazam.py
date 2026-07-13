"""Shazam metadata provider — audio-based song identification via ShazamIO."""

import logging
from typing import Any

from streamarr.metadata.base import MetadataBase

logger = logging.getLogger(__name__)


class ShazamProvider(MetadataBase):
    """Identify songs from audio segments using the Shazam API (via shazamio)."""

    def get_name(self) -> str:
        return "Shazam"

    def get_config_schema(self) -> dict[str, Any]:
        return {}

    async def identify(self, audio_path: str) -> dict[str, Any] | None:
        """
        Identify a song from an audio file.

        Args:
            audio_path: Path to a WAV/OGG audio file.

        Returns:
            Dict with title, artist, album, shazam_id, cover_art — or None.
        """
        from shazamio import Shazam

        shazam = Shazam()
        result = await shazam.recognize(audio_path)

        track = result.get("track")
        if not track:
            return None

        # Extract album from sections metadata
        album = None
        for section in track.get("sections", []):
            if section.get("type") == "SONG":
                for meta in section.get("metadata", []):
                    if meta.get("title") == "Album":
                        album = meta.get("text")
                        break

        # Extract cover art
        cover_art = None
        images = track.get("images", {})
        if images:
            cover_art = images.get("coverarthq") or images.get("coverart")

        return {
            "title": track.get("title"),
            "artist": track.get("subtitle"),
            "album": album,
            "shazam_id": track.get("key"),
            "cover_art": cover_art,
        }

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """Not applicable for Shazam — use identify() instead."""
        return []

    async def get_details(self, media_id: str | int, **kwargs) -> dict[str, Any]:
        """Not applicable for Shazam."""
        return {}
