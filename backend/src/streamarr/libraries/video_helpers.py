"""Shared helpers for video library plugins."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".m4v",
    ".wmv",
    ".flv",
    ".webm",
    ".mpg",
    ".mpeg",
}


def safe_library_child_path(root: str | Path, *parts: str | Path) -> Path | None:
    """Resolve a path under a library root and reject path traversal."""
    library_root = Path(root).resolve()
    candidate = library_root
    for part in parts:
        candidate = candidate / part
    resolved = candidate.resolve()
    if not resolved.is_relative_to(library_root):
        return None
    return resolved


def validate_library_path(path: str) -> bool:
    """Validate that a library path exists as a dir or can be created below its parent."""
    try:
        path_obj = Path(path)
        if path_obj.exists():
            return path_obj.is_dir()
        return path_obj.parent.exists() and os.access(path_obj.parent, os.W_OK)
    except OSError as e:
        logger.error("Error validating library path %s: %s", path, e)
        return False


def iter_video_files(path: str | Path):
    """Yield supported video files below a library path."""
    path_obj = Path(path)
    if not path_obj.exists():
        return

    for file_path in path_obj.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
            yield file_path


def library_video_stats(
    path: str,
    *,
    include_top_level_dir_count: bool = False,
    top_level_dir_count_key: str = "directory_count",
) -> dict[str, Any]:
    """Return common video-library file stats."""
    stats: dict[str, Any] = {
        "path": path,
        "file_count": 0,
        "total_size": 0,
        "file_types": {},
    }
    try:
        path_obj = Path(path)
        if not path_obj.exists():
            if include_top_level_dir_count:
                stats[top_level_dir_count_key] = 0
            return stats

        if include_top_level_dir_count:
            stats[top_level_dir_count_key] = sum(
                1 for child in path_obj.iterdir() if child.is_dir()
            )

        for file_path in iter_video_files(path_obj):
            ext = file_path.suffix.lower()
            stats["file_count"] += 1
            stats["total_size"] += file_path.stat().st_size
            stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1
    except OSError as e:
        logger.error("Error getting library stats for %s: %s", path, e)
    return stats


def video_file_info(file_path: Path) -> dict[str, Any]:
    """Return common file fields for a discovered video file."""
    return {
        "path": str(file_path),
        "filename": file_path.name,
        "size": file_path.stat().st_size,
        "extension": file_path.suffix.lower(),
    }
