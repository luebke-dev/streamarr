"""Photo and home-video library plugin."""

import os
from pathlib import Path
from typing import Any

from pyrate.libraries.base import LibraryBase

PHOTO_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".heic",
    ".heif",
    ".avif",
    ".tif",
    ".tiff",
    ".bmp",
}

HOME_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".mkv",
    ".webm",
    ".avi",
    ".mts",
    ".m2ts",
    ".3gp",
}

ALL_EXTENSIONS = PHOTO_EXTENSIONS | HOME_VIDEO_EXTENSIONS


class PhotoLibraryPlugin(LibraryBase):
    """Plugin for managing photos and home videos."""

    def get_name(self) -> str:
        return "Photo Library"

    def get_library_type(self) -> str:
        return "PHOTOS"

    def get_media_item_types(self) -> list[dict[str, Any]]:
        return [
            {"name": "PHOTOS", "label": "Photo", "parent_type": None},
            {"name": "HOME_VIDEOS", "label": "Home Video", "parent_type": None},
        ]

    async def get_default_path(self) -> str:
        return "/library/photos"

    async def validate_path(self, path: str) -> bool:
        try:
            p = Path(path)
            if p.exists():
                return p.is_dir()
            return p.parent.exists() and os.access(p.parent, os.W_OK)
        except Exception:
            return False

    def get_library_icon(self) -> str:
        return "mdi-image-multiple"

    def get_item_icon(self) -> str:
        return "mdi-image"

    def get_play_button_icon(self) -> str:
        return "mdi-eye"

    def get_play_button_label(self) -> str:
        return "common.view"

    async def get_supported_extensions(self) -> list[str]:
        return sorted(ALL_EXTENSIONS)

    async def validate_media_file(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in ALL_EXTENSIONS

    async def get_library_stats(self, path: str) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "path": path,
            "file_count": 0,
            "photo_count": 0,
            "home_video_count": 0,
            "total_size": 0,
            "file_types": {},
        }
        p = Path(path)
        if not p.exists():
            return stats

        for file_path in p.rglob("*"):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            if ext not in ALL_EXTENSIONS:
                continue
            stats["file_count"] += 1
            stats["total_size"] += file_path.stat().st_size
            stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1
            if ext in PHOTO_EXTENSIONS:
                stats["photo_count"] += 1
            else:
                stats["home_video_count"] += 1
        return stats

    async def scan_library(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        p = Path(path)
        if not p.exists():
            return items

        for file_path in sorted(p.rglob("*")):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            if ext not in ALL_EXTENSIONS:
                continue
            stat = file_path.stat()
            media_type = "PHOTOS" if ext in PHOTO_EXTENSIONS else "HOME_VIDEOS"
            items.append(
                {
                    "title": file_path.stem,
                    "media_type": media_type,
                    "file_path": str(file_path),
                    "file_name": file_path.name,
                    "file_size": stat.st_size,
                    "format": ext.lstrip("."),
                    "extra_data": {
                        "album_path": str(file_path.parent.relative_to(p))
                        if file_path.parent != p
                        else None,
                    },
                }
            )
        return items
