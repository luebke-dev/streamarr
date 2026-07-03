"""AudioBook library plugin."""

import logging
import os
from pathlib import Path
from typing import Any

from pyrate.libraries.base import LibraryBase

logger = logging.getLogger(__name__)


class AudioBookLibraryPlugin(LibraryBase):
    """Plugin for managing audiobook libraries."""

    def get_name(self) -> str:
        return "AudioBook Library"

    def get_library_type(self) -> str:
        return "AUDIOBOOKS"

    def get_media_item_types(self) -> list[dict[str, Any]]:
        return [
            {"name": "AUDIOBOOKS", "label": "Audiobook", "parent_type": None},
            {"name": "AUDIOBOOK_CHAPTERS", "label": "Chapter", "parent_type": "AUDIOBOOKS"},
        ]

    async def get_default_path(self) -> str:
        return "/library/audiobooks"

    async def validate_path(self, path: str) -> bool:
        """Validate audiobook library path."""
        try:
            path_obj = Path(path)
            if path_obj.exists():
                return path_obj.is_dir()
            return path_obj.parent.exists() and os.access(path_obj.parent, os.W_OK)
        except Exception as e:
            logger.error("Error validating audiobook library path %s: %s", path, e)
            return False

    async def get_library_stats(self, path: str) -> dict[str, Any]:
        """Get statistics about the audiobook library."""
        stats = {
            "path": path,
            "file_count": 0,
            "total_size": 0,
            "file_types": {},
            "total_duration": 0,  # Could be calculated from audio files
        }

        try:
            path_obj = Path(path)
            if not path_obj.exists():
                return stats

            # Common audiobook formats
            audiobook_extensions = {
                ".m4b",  # MPEG-4 Audio Book (most common)
                ".m4a",  # MPEG-4 Audio
                ".mp3",  # MP3 audio
                ".aax",  # Audible Enhanced Audio
                ".aa",  # Audible Audio
                ".flac",  # FLAC lossless
                ".ogg",  # Ogg Vorbis
                ".opus",  # Opus codec
                ".wma",  # Windows Media Audio
                ".aac",  # Advanced Audio Coding
            }

            for file_path in path_obj.rglob("*"):
                if file_path.is_file():
                    ext = file_path.suffix.lower()
                    if ext in audiobook_extensions:
                        stats["file_count"] += 1
                        stats["total_size"] += file_path.stat().st_size
                        stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1

        except Exception as e:
            logger.error("Error getting audiobook library stats for %s: %s", path, e)

        return stats

    def get_settings_schema(self) -> dict[str, Any]:
        return {
            "enable_library": {"default": True, "key": "enabled"},
            "library_path": {"default": "/library/audiobooks"},
        }

    async def scan_library(self, path: str) -> list[dict[str, Any]]:
        """
        Scan audiobook library path for audio files and return discovered items.

        Args:
            path: The library path to scan

        Returns:
            List of discovered audiobook items with metadata
        """
        items = []

        try:
            path_obj = Path(path)
            if not path_obj.exists():
                return items

            audiobook_extensions = {
                ".m4b",
                ".m4a",
                ".mp3",
                ".aax",
                ".aa",
                ".flac",
                ".ogg",
                ".opus",
                ".wma",
                ".aac",
            }

            # Group files by directory (one audiobook per directory)
            audiobook_dirs = set()

            for file_path in path_obj.rglob("*"):
                if (
                    file_path.is_file()
                    and file_path.suffix.lower() in audiobook_extensions
                ):
                    # Get the parent directory as the audiobook identifier
                    audiobook_dir = file_path.parent
                    if audiobook_dir not in audiobook_dirs:
                        audiobook_dirs.add(audiobook_dir)

                        # Create an item for this audiobook
                        item = {
                            "path": str(audiobook_dir),
                            "title": audiobook_dir.name,
                            "type": "audiobook",
                            "files": [],
                        }

                        # Collect all audio files in this directory
                        for audio_file in audiobook_dir.glob("*"):
                            if audio_file.suffix.lower() in audiobook_extensions:
                                item["files"].append(
                                    {
                                        "path": str(audio_file),
                                        "name": audio_file.name,
                                        "size": audio_file.stat().st_size,
                                        "ext": audio_file.suffix.lower(),
                                    }
                                )

                        items.append(item)

        except Exception as e:
            logger.error("Error scanning audiobook library %s: %s", path, e)

        return items

    def get_supported_formats(self) -> list[str]:
        """
        Get list of supported audiobook file formats.

        Returns:
            List of file extensions
        """
        return [
            ".m4b",  # MPEG-4 Audio Book
            ".m4a",  # MPEG-4 Audio
            ".mp3",  # MP3 audio
            ".aax",  # Audible Enhanced Audio
            ".aa",  # Audible Audio
            ".flac",  # FLAC lossless
            ".ogg",  # Ogg Vorbis
            ".opus",  # Opus codec
            ".wma",  # Windows Media Audio
            ".aac",  # Advanced Audio Coding
        ]

    def get_config_schema(self) -> dict[str, Any]:
        """Get configuration schema for audiobook library."""
        return {
            "library_path": {
                "type": "string",
                "label": "Library Path",
                "hint": "Path where audiobooks are stored",
                "required": False,
                "default": "/library/audiobooks",
                "placeholder": "/library/audiobooks",
            },
            "scan_subdirectories": {
                "type": "boolean",
                "label": "Scan Subdirectories",
                "hint": "Recursively scan all subdirectories for audiobooks",
                "required": False,
                "default": True,
            },
            "supported_formats": {
                "type": "string",
                "label": "Supported Formats",
                "hint": "Comma-separated list of file extensions (e.g., .m4b,.mp3,.flac)",
                "required": False,
                "default": ".m4b,.m4a,.mp3,.flac,.ogg,.opus",
                "placeholder": ".m4b,.m4a,.mp3,.flac,.ogg,.opus",
            },
        }
