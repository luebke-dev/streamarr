"""Disk-backed cache for original poster/backdrop images.

The overlay renderer needs the *original* bytes of an item's poster to
composite badges on top. We download once, store the raw bytes under
``<cache_root>/originals/<media_guid>.<ext>`` and serve them from disk
on subsequent renders.

The cache root is configurable via the ``overlays.cache_dir`` setting
(default ``data/image_cache``); the same root also stores rendered
overlay outputs under ``overlays/<media_guid>/<source_hash>.jpg``.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Final

import httpx

from pyrate.utils.http import make_async_client
from pyrate.utils.net import UnsafeUrlError, safe_get
from pyrate.utils.retry import http_with_retries

logger = logging.getLogger(__name__)


_DEFAULT_CACHE_ROOT = Path("data/image_cache")
_MAX_BYTES: Final[int] = 8 * 1024 * 1024  # 8 MB — generous for high-res posters
_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
}


class ImageCacheError(Exception):
    """Raised when an original cannot be fetched or cached."""


class ImageCacheService:
    """Maintain on-disk copies of original media images.

    Concurrency: callers may race to fetch the same media GUID. We
    serialize per-GUID with an in-memory asyncio lock so the resulting
    cache file is atomic and we don't waste bandwidth re-downloading.
    """

    def __init__(
        self,
        *,
        cache_root: str | Path | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.cache_root = Path(cache_root or _DEFAULT_CACHE_ROOT)
        self.originals_dir = self.cache_root / "originals"
        self.overlays_dir = self.cache_root / "overlays"
        self.http_client = http_client or make_async_client()
        self._owns_client = http_client is None
        self._locks: dict[str, asyncio.Lock] = {}

    async def close(self) -> None:
        if self._owns_client:
            await self.http_client.aclose()

    # ------------------------------------------------------------------
    # Originals
    # ------------------------------------------------------------------

    def _lock_for(self, guid: uuid.UUID) -> asyncio.Lock:
        key = str(guid)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def find_original(self, media_guid: uuid.UUID) -> Path | None:
        """Return the cached file path for ``media_guid`` if present."""
        for ext in (".jpg", ".png", ".webp", ".avif"):
            candidate = self.originals_dir / f"{media_guid}{ext}"
            if candidate.exists():
                return candidate
        return None

    async def get_original(
        self, media_guid: uuid.UUID, source_url: str | None
    ) -> Path:
        """Return a disk path containing the original bytes.

        Downloads ``source_url`` on first access. Raises
        :class:`ImageCacheError` when no URL is given and nothing is
        cached yet.
        """
        cached = self.find_original(media_guid)
        if cached is not None:
            return cached
        if not source_url:
            raise ImageCacheError(
                f"No source URL and no cached original for {media_guid}"
            )

        async with self._lock_for(media_guid):
            cached = self.find_original(media_guid)
            if cached is not None:
                return cached
            return await self._download(media_guid, source_url)

    async def _download(
        self, media_guid: uuid.UUID, source_url: str
    ) -> Path:
        async def do_request() -> httpx.Response:
            return await safe_get(source_url, client=self.http_client)

        try:
            response = await http_with_retries(
                do_request, max_retries=4, base_delay=1.0, log_label="image-cache"
            )
        except UnsafeUrlError as exc:
            raise ImageCacheError(
                f"Refusing to fetch unsafe image URL {source_url}: {exc}"
            )
        if response is None:
            raise ImageCacheError(
                f"Image fetch exhausted retries: {source_url}"
            )
        if response.status_code >= 400:
            raise ImageCacheError(
                f"Image fetch {source_url} returned {response.status_code}"
            )
        if len(response.content) > _MAX_BYTES:
            raise ImageCacheError(
                f"Image at {source_url} exceeds {_MAX_BYTES} bytes"
            )

        content_type = (
            response.headers.get("content-type", "") or ""
        ).split(";", 1)[0].lower()
        ext = _CONTENT_TYPE_EXT.get(content_type)
        if ext is None:
            guess_ext, _ = mimetypes.guess_extension(content_type), None
            ext = guess_ext if guess_ext in {".jpg", ".png", ".webp"} else ".jpg"

        self.originals_dir.mkdir(parents=True, exist_ok=True)
        target = self.originals_dir / f"{media_guid}{ext}"
        # Atomic-ish write: stage then rename. asyncio.to_thread keeps the
        # event loop unblocked for large posters.
        staging = target.with_suffix(target.suffix + ".part")
        await asyncio.to_thread(staging.write_bytes, response.content)
        await asyncio.to_thread(staging.replace, target)
        logger.debug("image-cache stored %s (%d bytes)", target, len(response.content))
        return target

    # ------------------------------------------------------------------
    # Overlay outputs
    # ------------------------------------------------------------------

    def overlay_path(
        self, media_guid: uuid.UUID, source_hash: str, ext: str = ".jpg"
    ) -> Path:
        """Compute the on-disk path for a rendered overlay output."""
        return self.overlays_dir / str(media_guid) / f"{source_hash}{ext}"

    async def write_overlay(
        self,
        media_guid: uuid.UUID,
        source_hash: str,
        data: bytes,
        ext: str = ".jpg",
    ) -> Path:
        """Persist rendered ``data`` for ``media_guid``."""
        target = self.overlay_path(media_guid, source_hash, ext)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_suffix(target.suffix + ".part")
        await asyncio.to_thread(staging.write_bytes, data)
        await asyncio.to_thread(staging.replace, target)
        return target

    async def prune_overlays_for_item(
        self, media_guid: uuid.UUID, keep_hashes: set[str]
    ) -> int:
        """Remove cached overlay outputs that are no longer current."""
        directory = self.overlays_dir / str(media_guid)
        if not directory.exists():
            return 0

        def _prune() -> int:
            removed = 0
            for entry in directory.iterdir():
                if not entry.is_file():
                    continue
                if entry.stem in keep_hashes:
                    continue
                try:
                    entry.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
            return removed

        return await asyncio.to_thread(_prune)
