"""Artwork proxy/cache helpers extracted from the media router.

Pure functions (env flags, cache keys/paths, the proxy host allowlist, image
transform-query building) with no request/router dependencies. Kept out of the
large ``api/v1/media.py`` so that module carries endpoints, not cache plumbing.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException

from pyrate.services.cache_control import (
    artwork_cache_enabled as _artwork_cache_enabled,
)
from pyrate.services.cache_control import (
    artwork_cache_root as _artwork_cache_root_base,
)

# Hosts whose artwork the proxy endpoint is allowed to fetch (SSRF guard).
_ARTWORK_PROXY_HOSTS = {
    "image.tmdb.org",
    "images.igdb.com",
    "covers.openlibrary.org",
    "i.scdn.co",
}
_ARTWORK_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _append_image_transform_query(source_url: str, params: dict[str, int | str]) -> str:
    if not params:
        return source_url

    parts = urlsplit(source_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items()})
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _artwork_cache_root() -> Path:
    # Writer side: the cache directory must exist before we write into it. Shares
    # the flag/root source of truth with the cleanup/stats side (cache_control).
    return _artwork_cache_root_base(create=True)


def _validate_artwork_proxy_url(source_url: str) -> None:
    parts = urlsplit(source_url)
    if parts.scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail="Only HTTP(S) artwork can be proxied")
    if parts.hostname is None or parts.hostname.lower() not in _ARTWORK_PROXY_HOSTS:
        raise HTTPException(status_code=422, detail="Artwork host is not allowed")


def _artwork_cache_key(source_url: str, transform_params: dict[str, object]) -> str:
    payload = json.dumps(
        {"url": source_url, "transform": transform_params},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _artwork_extension(media_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/avif": "avif",
        "image/gif": "gif",
    }.get(media_type, "img")


def _artwork_cache_path(cache_key: str, media_type: str) -> Path:
    extension = _artwork_extension(media_type)
    return (_artwork_cache_root() / f"{cache_key}.{extension}").resolve()


def _artwork_headers(cache_key: str, cache_status: str) -> dict[str, str]:
    return {
        "Cache-Control": _ARTWORK_CACHE_CONTROL,
        "ETag": f'"{cache_key}"',
        "X-Pyrate-Artwork-Cache": cache_status,
    }


def _artwork_storage_root() -> Path:
    configured = os.getenv("PYRATE_ARTWORK_DIR")
    root = Path(configured) if configured else Path(tempfile.gettempdir()) / "pyrate-artwork"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()
