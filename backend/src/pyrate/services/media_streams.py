"""Build selectable stream and quality options for media playback."""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote

from pyrate.libraries.base import structure_probe_data
from pyrate.models.media import MediaItem
from pyrate.services.media_serializer import load_media_extra_data

logger = logging.getLogger(__name__)

_RESOLUTION_PATTERN = re.compile(r"(2160|1080|720|480)[pi]", re.IGNORECASE)
_RESOLUTION_HEIGHT_MAP = {"2160": 2160, "1080": 1080, "720": 720, "480": 480}
_STANDARD_RESOLUTIONS = [
    {"label": "4K", "height": 2160},
    {"label": "1080p", "height": 1080},
    {"label": "720p", "height": 720},
    {"label": "480p", "height": 480},
]


class MediaStreamOptionsService:
    """Pure builder for stream-selection API payloads."""

    def build_options(self, media_item: MediaItem) -> dict:
        primary_file = self._primary_file(media_item)
        audio_streams, subtitle_streams = self._embedded_streams(primary_file)
        subtitle_streams.extend(self._managed_subtitle_streams(media_item))

        quality_options = self._quality_options(media_item)
        return {
            "audio_streams": audio_streams,
            "subtitle_streams": subtitle_streams,
            "quality_options": quality_options,
        }

    def _embedded_streams(self, primary_file) -> tuple[list[dict], list[dict]]:
        if not primary_file or not primary_file.probe_data:
            return [], []

        try:
            probe_data = self._normalized_probe_data(primary_file.probe_data)
        except json.JSONDecodeError:
            logger.warning("Failed to parse probe_data for file %s", primary_file.guid)
            return [], []

        audio_streams = [
            {
                "index": stream.get("index"),
                "language": stream.get("language") or "unknown",
                "title": stream.get("title"),
                "codec_name": stream.get("codec_name"),
                "channels": stream.get("channels"),
                "sample_rate": stream.get("sample_rate"),
                "bit_rate": stream.get("bit_rate"),
                "stream_index": audio_index,
            }
            for audio_index, stream in enumerate(probe_data.get("audio_streams", []))
        ]
        subtitle_streams = [
            {
                "index": stream.get("index"),
                "language": stream.get("language") or "unknown",
                "title": stream.get("title"),
                "codec_name": stream.get("codec_name"),
                "format": stream.get("codec_name"),
                "forced": stream.get("forced", False),
                "default": stream.get("default", False),
                "stream_index": subtitle_index,
                "source": "embedded",
                "url": None,
                "content_url": None,
            }
            for subtitle_index, stream in enumerate(
                probe_data.get("subtitle_streams", [])
            )
        ]
        return audio_streams, subtitle_streams

    def _normalized_probe_data(self, raw_probe_data: str) -> dict:
        probe_data = json.loads(raw_probe_data)
        if "video_streams" in probe_data or "audio_streams" in probe_data:
            return probe_data

        if "streams" in probe_data:
            return structure_probe_data(probe_data)

        if not (probe_data.get("audio_codec") or probe_data.get("video_codec")):
            return probe_data

        normalized = {
            "format": {},
            "video_streams": [],
            "audio_streams": [],
            "subtitle_streams": [],
        }
        if probe_data.get("audio_codec"):
            normalized["audio_streams"].append(
                {
                    "index": 0,
                    "codec_name": probe_data["audio_codec"],
                    "language": "unknown",
                    "title": None,
                    "channels": self._legacy_audio_channels(
                        probe_data.get("audio_channels", "")
                    ),
                    "sample_rate": None,
                    "bit_rate": None,
                }
            )
        return normalized

    @staticmethod
    def _legacy_audio_channels(value) -> int | None:
        if not value:
            return None
        try:
            return int(float(value) + 0.5)
        except (ValueError, TypeError):
            return None

    def _quality_options(self, media_item: MediaItem) -> list[dict]:
        quality_options = [
            self._file_quality_option(file, idx)
            for idx, file in enumerate(media_item.files or [])
        ]
        max_file_height = max((opt["height"] for opt in quality_options), default=0)
        existing_heights = {opt["height"] for opt in quality_options}

        quality_options.extend(
            self._transcode_quality_options(max_file_height, existing_heights)
        )
        quality_options.extend(
            self._release_quality_options(
                media_item,
                max_file_height=max_file_height,
                existing_heights=existing_heights,
            )
        )
        quality_options.sort(key=lambda opt: opt["height"], reverse=True)
        return quality_options

    @staticmethod
    def _primary_file(media_item: MediaItem):
        sorted_files = sorted(
            media_item.files or [],
            key=lambda f: (
                0
                if f.quality and "2160" in f.quality
                else 1
                if f.quality and "1080" in f.quality
                else 2
                if f.quality and "720" in f.quality
                else 3
            ),
        )
        return sorted_files[0] if sorted_files else None

    @staticmethod
    def _file_quality_option(file, idx: int) -> dict:
        quality_label = file.quality or "Unknown"
        height = file.height or 0

        if height >= 2160 or (file.quality and "2160" in file.quality):
            quality_label = "4K"
            height = 2160
        elif height >= 1080 or (file.quality and "1080" in file.quality):
            quality_label = "1080p"
            height = 1080
        elif height >= 720 or (file.quality and "720" in file.quality):
            quality_label = "720p"
            height = 720
        elif height >= 480 or (file.quality and "480" in file.quality):
            quality_label = "480p"
            height = 480

        return {
            "label": quality_label,
            "height": height,
            "quality": file.quality,
            "file_guid": str(file.guid),
            "release_guid": None,
            "is_downloaded": True,
            "is_available": True,
            "is_current": idx == 0,
            "source": "file",
        }

    @staticmethod
    def _transcode_quality_options(
        max_file_height: int,
        existing_heights: set[int],
    ) -> list[dict]:
        options = []
        for resolution in _STANDARD_RESOLUTIONS:
            if (
                resolution["height"] < max_file_height
                and resolution["height"] not in existing_heights
            ):
                options.append(
                    {
                        "label": resolution["label"],
                        "height": resolution["height"],
                        "quality": resolution["label"],
                        "file_guid": None,
                        "release_guid": None,
                        "is_downloaded": False,
                        "is_available": True,
                        "is_current": False,
                        "source": "transcode",
                    }
                )
                existing_heights.add(resolution["height"])
        return options

    def _release_quality_options(
        self,
        media_item: MediaItem,
        *,
        max_file_height: int,
        existing_heights: set[int],
    ) -> list[dict]:
        options = []
        for release in media_item.releases or []:
            release_height = self._parse_release_height(release)
            if (
                release_height
                and release_height > max_file_height
                and release_height not in existing_heights
            ):
                label = next(
                    (
                        resolution["label"]
                        for resolution in _STANDARD_RESOLUTIONS
                        if resolution["height"] == release_height
                    ),
                    f"{release_height}p",
                )
                options.append(
                    {
                        "label": label,
                        "height": release_height,
                        "quality": label,
                        "file_guid": None,
                        "release_guid": str(release.guid),
                        "is_downloaded": False,
                        "is_available": False,
                        "is_current": False,
                        "source": "release",
                    }
                )
                existing_heights.add(release_height)
        return options

    @staticmethod
    def _parse_release_height(release) -> int | None:
        if release.release_metadata and isinstance(release.release_metadata, dict):
            resolution = release.release_metadata.get("resolution", "")
            if resolution:
                match = _RESOLUTION_PATTERN.search(resolution)
                if match:
                    return _RESOLUTION_HEIGHT_MAP.get(match.group(1))

        if release.quality:
            match = _RESOLUTION_PATTERN.search(release.quality)
            if match:
                return _RESOLUTION_HEIGHT_MAP.get(match.group(1))

        if release.title:
            match = _RESOLUTION_PATTERN.search(release.title)
            if match:
                return _RESOLUTION_HEIGHT_MAP.get(match.group(1))

        return None

    @staticmethod
    def _managed_subtitle_streams(media_item: MediaItem) -> list[dict]:
        raw_subtitles = (
            load_media_extra_data(media_item).get("subtitles")
            or load_media_extra_data(media_item).get("subtitle_tracks")
            or []
        )
        if not isinstance(raw_subtitles, list):
            return []

        streams = []
        for index, raw in enumerate(raw_subtitles):
            if not isinstance(raw, dict):
                continue
            language = raw.get("language") or raw.get("lang")
            if not isinstance(language, str) or not language.strip():
                continue
            subtitle_id = str(raw.get("id") or raw.get("guid") or f"managed-{index}")
            path = raw.get("path") if isinstance(raw.get("path"), str) else None
            url = raw.get("url") if isinstance(raw.get("url"), str) else None
            is_uploaded = bool(path and path.startswith("uploaded:"))
            streams.append(
                {
                    "id": subtitle_id,
                    "index": None,
                    "language": language.strip(),
                    "title": raw.get("title")
                    if isinstance(raw.get("title"), str)
                    else None,
                    "codec_name": raw.get("format")
                    if isinstance(raw.get("format"), str)
                    else None,
                    "format": raw.get("format")
                    if isinstance(raw.get("format"), str)
                    else None,
                    "forced": bool(raw.get("is_forced") or raw.get("forced")),
                    "default": bool(raw.get("is_default") or raw.get("default")),
                    "stream_index": None,
                    "source": "uploaded" if is_uploaded else "managed",
                    "url": url,
                    "content_url": (
                        f"/api/media/{media_item.guid}/subtitles/"
                        f"{quote(subtitle_id, safe='')}/content"
                        if (is_uploaded or url)
                        else None
                    ),
                }
            )
        return streams
