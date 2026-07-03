"""Media file service for probe data extraction and metadata updates."""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.media import MediaFile

logger = logging.getLogger(__name__)


# Height-to-quality mapping thresholds (descending order)
_QUALITY_THRESHOLDS = [
    (2160, "4K"),
    (1080, "1080p"),
    (720, "720p"),
    (480, "480p"),
]
_QUALITY_DEFAULT = "SD"


class MediaFileService:
    """Service for managing media file metadata."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def quality_from_height(height: int | None) -> str | None:
        """Determine quality label from video height in pixels.

        Returns:
            Quality string (e.g. "1080p") or None if height is not provided.
        """
        if height is None:
            return None
        for threshold, label in _QUALITY_THRESHOLDS:
            if height >= threshold:
                return label
        return _QUALITY_DEFAULT

    async def update_from_probe_data(
        self, media_file_guid: str, probe_data: dict
    ) -> MediaFile:
        """Apply probe data to a MediaFile and persist changes.

        Extracts duration, file_size, bitrate, width, height, codec, and
        quality from the raw ffprobe output and updates the corresponding
        model fields.

        Args:
            media_file_guid: GUID of the MediaFile to update.
            probe_data: Parsed ffprobe output dict with ``format`` and
                ``video_streams`` keys.

        Returns:
            The updated MediaFile instance.

        Raises:
            ValueError: If the media file is not found.
        """
        file = await self.db.get(MediaFile, media_file_guid)
        if not file:
            logger.error("Media file %s not found for probe update", media_file_guid)
            raise ValueError(f"Media file {media_file_guid} not found")

        file.probe_data = json.dumps(probe_data)

        # Extract format-level metadata
        format_info = probe_data.get("format", {})
        if format_info.get("duration"):
            file.duration = float(format_info["duration"])
        if format_info.get("size"):
            file.file_size = int(format_info["size"])
        if format_info.get("bit_rate"):
            file.bitrate = int(format_info["bit_rate"]) // 1000  # kbps

        # Extract video stream metadata
        video_streams = probe_data.get("video_streams", [])
        if video_streams:
            first_video = video_streams[0]
            if first_video.get("width"):
                file.width = first_video["width"]
            if first_video.get("height"):
                file.height = first_video["height"]
            if first_video.get("codec_name"):
                file.codec = first_video["codec_name"]

        # Derive quality from resolution
        file.quality = self.quality_from_height(file.height)

        await self.db.commit()
        logger.info(
            "Updated media file %s from probe data: quality=%s, duration=%.1fs, codec=%s",
            media_file_guid, file.quality, file.duration or 0, file.codec,
        )
        return file
