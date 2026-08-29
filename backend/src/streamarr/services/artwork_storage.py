"""Canonical storage for uploaded and library-local artwork assets."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


def artwork_storage_root() -> Path:
    configured = os.getenv("STREAMARR_ARTWORK_DIR") or os.getenv(
        "STREAMARR_ARTWORK_CACHE_DIR"
    )
    if configured:
        root = Path(configured)
    elif Path("/cache").is_dir():
        root = Path("/cache/artwork")
    else:
        root = Path(tempfile.gettempdir()) / "streamarr-artwork"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def store_local_artwork(
    media_guid: uuid.UUID,
    image_type: str,
    source_path: Path,
) -> str | None:
    """Copy trusted library-local artwork into Streamarr-managed storage."""
    extension = source_path.suffix.casefold()
    if extension not in _ALLOWED_EXTENSIONS or not source_path.is_file():
        return None
    stat = source_path.stat()
    asset_name = f"{media_guid}-{image_type}-local-{stat.st_mtime_ns}{extension}"
    target = artwork_storage_root() / asset_name
    if not target.exists():
        staging = target.with_suffix(target.suffix + ".part")
        shutil.copyfile(source_path, staging)
        staging.replace(target)
    return f"/api/media/{media_guid}/images/{image_type}/content/{asset_name}"
