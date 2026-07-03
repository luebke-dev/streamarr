"""
Unified Media API Endpoints

Provides a single set of endpoints for all media types (movies, shows, games, music, books).
Uses MediaType parameter to filter and handle different content types.
"""

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import math
import os
import tempfile
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate import worker as worker_tasks
from pyrate.api.dependencies import (
    CurrentSuperuser,
    CurrentUser,
    DatabaseSession,
    UserPermissionsDep,
)
from pyrate.api.v1.media_filters import MediaListQuery, media_type_for_library
from pyrate.auth.dependencies import get_current_superuser, get_current_user_optional
from pyrate.libraries import get_library_type_for_media_item_type
from pyrate.models.downloads import Download
from pyrate.models.library import Library
from pyrate.models.media import (
    AvailabilityStatus,
    MediaItem,
    MediaRelease,
    MediaReleaseLink,
    MediaType,
)
from pyrate.models.media_watch import MediaWatch
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.schemas.media import (
    AlbumWithTracks,
    MediaExternalLinkRead,
    MediaItemCreate,
    MediaItemDetail,
    MediaItemRead,
    MediaItemSummary,
    MediaItemUpdate,
    MediaReleaseCreate,
    MediaReleaseRead,
    MediaSearchResponse,
    PaginatedMediaReleasesResponse,
    PaginatedMediaSummaryResponse,
    SeasonWithEpisodes,
    ShowWithHierarchy,
)
from pyrate.services import availability as availability_service
from pyrate.services.activity_log import ActivityLogService
from pyrate.services.cache_control import clear_rendered_layout_cache
from pyrate.services.download_status import download_phase
from pyrate.services.library import LibraryService
from pyrate.services.media import MediaService
from pyrate.services.media_access import (
    allowed_media_types_for_permissions,
    max_age_for_user,
    require_library_access_for_media_type,
    require_media_mutation_access,
    require_media_read_access,
)
from pyrate.services.media_detail import MediaDetailService
from pyrate.services.media_serializer import (
    external_links_for_media as _external_links_for_media,
)
from pyrate.services.media_serializer import (
    load_media_extra_data as _load_media_extra_data,
)
from pyrate.services.media_serializer import (
    minimal_media_item_detail as _minimal_media_item_detail,
)
from pyrate.services.media_streams import MediaStreamOptionsService
from pyrate.services.metadata import MetadataService
from pyrate.services.observability import record_artwork_cache_event
from pyrate.services.permission import PermissionService
from pyrate.services.rate_limiter import check_and_record
from pyrate.services.recommendation import RecommendationService
from pyrate.services.show_resume import ShowResumeError, ShowResumeService
from pyrate.services.translation import TranslationService
from pyrate.utils.net import UnsafeUrlError, safe_get

add_download = worker_tasks.add_download
add_music_download = worker_tasks.add_music_download
add_show_download = worker_tasks.add_show_download

logger = logging.getLogger(__name__)

router = APIRouter()

ImageType = Literal["poster", "backdrop"]
ImageFormat = Literal["jpg", "jpeg", "png", "webp", "avif"]


class MediaImagesResponse(BaseModel):
    poster_path: str | None
    backdrop_path: str | None


class MediaImageUpdate(BaseModel):
    path: str | None = Field(
        None,
        description="Image URL or stored asset path. Null clears the image.",
        max_length=2048,
    )


class MediaImagesUpdate(BaseModel):
    poster_path: str | None = Field(default=None, max_length=2048)
    backdrop_path: str | None = Field(default=None, max_length=2048)


class MediaImageUpload(BaseModel):
    file_name: str | None = Field(default=None, max_length=255)
    content_type: str = Field(max_length=100)
    content_base64: str = Field(min_length=1)


class MediaImageUploadResponse(MediaImagesResponse):
    stored_path: str
    content_type: str
    size_bytes: int


class RemoteImageResult(BaseModel):
    provider: str
    provider_id: str
    image_type: ImageType
    url: str
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    language: str | None = None
    score: float | None = None


class RemoteImageSearchResponse(BaseModel):
    items: list[RemoteImageResult]
    total: int


class MediaExternalLinksResponse(BaseModel):
    items: list[MediaExternalLinkRead]
    total: int


class MediaImageTransformResponse(BaseModel):
    image_type: ImageType
    source_url: str
    transformed_url: str
    width: int | None = None
    height: int | None = None
    max_width: int | None = None
    max_height: int | None = None
    quality: int | None = None
    format: ImageFormat | None = None
    fill_width: int | None = None
    fill_height: int | None = None


class RemoteImageSelect(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    provider_id: str = Field(min_length=1, max_length=255)


class MetadataIdentifyResult(BaseModel):
    provider: str
    provider_id: str
    title: str
    original_title: str | None = None
    description: str | None = None
    tagline: str | None = None
    release_date: datetime | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    score: float | None = None


class MetadataIdentifyResponse(BaseModel):
    items: list[MetadataIdentifyResult]
    total: int


class MetadataIdentifyApply(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    provider_id: str = Field(min_length=1, max_length=255)


class MediaTrailer(BaseModel):
    id: str
    name: str
    url: str
    provider: str = "metadata"
    provider_id: str | None = None
    site: str | None = None
    language: str | None = None
    official: bool | None = None
    published_at: datetime | None = None


class MediaTrailersResponse(BaseModel):
    items: list[MediaTrailer]
    total: int


class MediaTrailersUpdate(BaseModel):
    items: list[MediaTrailer] = Field(default_factory=list, max_length=50)


class ManualMetadataUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    original_title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    tagline: str | None = Field(default=None, max_length=500)
    release_date: datetime | None = None
    content_rating: str | None = Field(default=None, max_length=64)
    min_age: int | None = Field(default=None, ge=0, le=21)
    sequence_number: int | None = None
    poster_path: str | None = Field(default=None, max_length=2048)
    backdrop_path: str | None = Field(default=None, max_length=2048)
    custom_metadata: dict | None = None


_FALLBACK_DOWNLOAD_ROOTS = (
    Path("/library"),
    Path("/downloads"),
    Path("/cache"),
)


def _safe_file_name(name: str | None, file_path: str) -> str:
    """Return a browser-safe file name without trusting stored path separators."""
    candidate = name or Path(file_path).name
    return Path(candidate).name or "download"


def _resolve_download_path(file_path: str, allowed_roots: list[Path]) -> Path:
    """Resolve a media file path and ensure it is inside an expected media root."""
    candidate = Path(file_path).resolve()
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    for root in allowed_roots:
        try:
            resolved_root = root.resolve()
        except FileNotFoundError:
            continue
        if candidate.is_relative_to(resolved_root):
            return candidate

    logger.warning(
        "Refused to download file outside allowed roots: %s (resolved=%s)",
        file_path,
        candidate,
    )
    raise HTTPException(status_code=404, detail="File not found")


async def _allowed_download_roots(db: AsyncSession, media_item: MediaItem) -> list[Path]:
    roots = list(_FALLBACK_DOWNLOAD_ROOTS)
    if media_item.library_guid:
        library = await db.get(Library, media_item.library_guid)
        if library and library.path:
            roots.insert(0, Path(library.path))
            return roots

    library_type = get_library_type_for_media_item_type(media_item.media_type.value)
    if not library_type:
        return roots

    rows = await db.execute(
        select(Library.path)
        .where(Library.type == library_type, Library.path.isnot(None))
        .order_by(Library.enabled.desc(), Library.created_at.asc())
    )
    for path in rows.scalars().all():
        roots.insert(0, Path(path))
    return roots


def _normalize_remote_image(raw: dict) -> dict | None:
    image_type = raw.get("image_type") or raw.get("type")
    url = raw.get("url") or raw.get("path")
    provider_id = raw.get("provider_id") or raw.get("id") or raw.get("guid") or url
    if image_type not in {"poster", "backdrop"}:
        return None
    if not isinstance(url, str) or not url.strip():
        return None

    provider = raw.get("provider") if isinstance(raw.get("provider"), str) else "metadata"
    thumbnail_url = raw.get("thumbnail_url")
    if not isinstance(thumbnail_url, str):
        thumbnail_url = raw.get("thumbnail") if isinstance(raw.get("thumbnail"), str) else None

    score = raw.get("score")
    if not isinstance(score, (int, float)):
        score = None
    width = raw.get("width")
    if not isinstance(width, int):
        width = None
    height = raw.get("height")
    if not isinstance(height, int):
        height = None
    language = raw.get("language") if isinstance(raw.get("language"), str) else None

    return {
        "provider": provider.strip(),
        "provider_id": str(provider_id),
        "image_type": image_type,
        "url": url.strip(),
        "thumbnail_url": thumbnail_url,
        "width": width,
        "height": height,
        "language": language,
        "score": score,
    }


def _remote_image_candidates(media_item: MediaItem) -> list[dict]:
    extra_data = _load_media_extra_data(media_item)
    candidates: list[dict] = []
    for key in ("remote_images", "image_provider_results"):
        raw_candidates = extra_data.get(key)
        if isinstance(raw_candidates, list):
            candidates.extend(raw for raw in raw_candidates if isinstance(raw, dict))

    if media_item.poster_path:
        candidates.append(
            {"provider": "current", "id": "poster", "type": "poster", "url": media_item.poster_path}
        )
    if media_item.backdrop_path:
        candidates.append(
            {"provider": "current", "id": "backdrop", "type": "backdrop", "url": media_item.backdrop_path}
        )

    normalized = [_normalize_remote_image(raw) for raw in candidates]
    return [candidate for candidate in normalized if candidate is not None]


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _normalize_trailer(raw: dict) -> dict | None:
    url = raw.get("url") or raw.get("path") or raw.get("uri")
    provider_id = raw.get("provider_id") or raw.get("id") or raw.get("key") or url
    name = raw.get("name") or raw.get("title") or "Trailer"
    trailer_type = (raw.get("type") or raw.get("video_type") or "trailer").lower()
    if trailer_type not in {"trailer", "teaser", "clip"}:
        return None
    if not isinstance(url, str) or not url.strip():
        site = raw.get("site") if isinstance(raw.get("site"), str) else None
        key = raw.get("key") if isinstance(raw.get("key"), str) else None
        if site and key and site.lower() == "youtube":
            url = f"https://www.youtube.com/watch?v={key}"
        else:
            return None

    provider = raw.get("provider") if isinstance(raw.get("provider"), str) else "metadata"
    site = raw.get("site") if isinstance(raw.get("site"), str) else None
    language = raw.get("language") or raw.get("iso_639_1")
    if not isinstance(language, str):
        language = None
    official = raw.get("official")
    if not isinstance(official, bool):
        official = None

    return {
        "id": str(provider_id),
        "name": str(name),
        "url": url.strip(),
        "provider": provider.strip() or "metadata",
        "provider_id": str(provider_id) if provider_id is not None else None,
        "site": site,
        "language": language,
        "official": official,
        "published_at": _parse_datetime(raw.get("published_at") or raw.get("published_date")),
    }


def _trailer_candidates(media_item: MediaItem) -> list[dict]:
    extra_data = _load_media_extra_data(media_item)
    candidates: list[dict] = []
    for key in ("trailers", "remote_trailers", "video_provider_results", "videos"):
        raw_candidates = extra_data.get(key)
        if isinstance(raw_candidates, list):
            candidates.extend(raw for raw in raw_candidates if isinstance(raw, dict))

    normalized = [_normalize_trailer(raw) for raw in candidates]
    deduped: dict[tuple[str, str], dict] = {}
    for candidate in normalized:
        if candidate is None:
            continue
        deduped[(candidate["provider"].lower(), candidate["id"])] = candidate
    return list(deduped.values())


def _find_remote_image(
    media_item: MediaItem,
    *,
    image_type: ImageType,
    provider: str,
    provider_id: str,
) -> dict | None:
    provider_key = provider.strip().lower()
    provider_id_key = provider_id.strip()
    for candidate in _remote_image_candidates(media_item):
        if (
            candidate["image_type"] == image_type
            and candidate["provider"].lower() == provider_key
            and candidate["provider_id"] == provider_id_key
        ):
            return candidate
    return None


def _image_language_matches(
    candidate: dict,
    *,
    language: str | None,
    include_language_neutral: bool,
) -> bool:
    if not language:
        return True

    candidate_language = candidate.get("language")
    if not candidate_language:
        return include_language_neutral
    return str(candidate_language).casefold() == language.casefold()


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


_IMAGE_UPLOAD_TYPES = {
    "image/jpeg": ("jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/png": ("png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (
        "webp",
        lambda data: data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    ),
    "image/avif": ("avif", lambda data: data[4:8] == b"ftyp" and b"avif" in data[8:32]),
}
_MAX_UPLOADED_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_REMOTE_IMAGE_BYTES = 15 * 1024 * 1024
_ARTWORK_PROXY_HOSTS = {
    "image.tmdb.org",
    "images.igdb.com",
    "covers.openlibrary.org",
    "i.scdn.co",
}
_ARTWORK_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _artwork_cache_enabled() -> bool:
    return _env_flag("PYRATE_ARTWORK_CACHE_ENABLED", False)


def _artwork_cache_root() -> Path:
    root = Path(os.getenv("PYRATE_ARTWORK_CACHE_DIR", "/cache/artwork"))
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


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


def _decode_image_upload(payload: MediaImageUpload) -> tuple[bytes, str, str]:
    content_type = payload.content_type.split(";", 1)[0].strip().lower()
    type_config = _IMAGE_UPLOAD_TYPES.get(content_type)
    if type_config is None:
        raise HTTPException(status_code=400, detail="Unsupported image content type")

    try:
        image_bytes = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Invalid base64 image content")

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image content is empty")
    if len(image_bytes) > _MAX_UPLOADED_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image content is too large")

    extension, validator = type_config
    if not validator(image_bytes):
        raise HTTPException(status_code=400, detail="Image bytes do not match content type")
    return image_bytes, content_type, extension


def _stored_image_path(asset_name: str) -> Path:
    if "/" in asset_name or "\\" in asset_name:
        raise HTTPException(status_code=404, detail="Image not found")
    path = (_artwork_storage_root() / asset_name).resolve()
    if not path.is_relative_to(_artwork_storage_root()):
        raise HTTPException(status_code=404, detail="Image not found")
    return path


def _stored_image_media_type(storage_path: Path) -> str:
    extension = storage_path.suffix.lower().lstrip(".")
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "avif": "image/avif",
    }.get(extension, "application/octet-stream")


async def _fetch_remote_image(source_url: str) -> tuple[bytes, str]:
    try:
        response = await safe_get(source_url, timeout=10.0, block_private=True)
    except UnsafeUrlError:
        raise HTTPException(status_code=422, detail="Only HTTP(S) images can be proxied")
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Remote image returned status {response.status_code}",
        )

    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Remote URL did not return an image")
    if len(response.content) > _MAX_REMOTE_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Remote image is too large")
    return response.content, content_type


def _pil_format_for_image_format(image_format: ImageFormat | None, storage_path: Path) -> str:
    if image_format is None:
        image_format = (
            "jpg"
            if storage_path.suffix.lower() in {".jpg", ".jpeg"}
            else storage_path.suffix.lower().lstrip(".")
        )
    if image_format == "jpg":
        image_format = "jpeg"
    return image_format.upper()


def _pil_format_for_content_type(image_format: ImageFormat | None, content_type: str) -> str:
    if image_format is None:
        image_format = {
            "image/jpeg": "jpeg",
            "image/png": "png",
            "image/webp": "webp",
            "image/avif": "avif",
        }.get(content_type, "png")
    if image_format == "jpg":
        image_format = "jpeg"
    return image_format.upper()


def _image_media_type_for_pil_format(output_format: str) -> str:
    return {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
        "AVIF": "image/avif",
    }.get(output_format, "application/octet-stream")


def _apply_image_transform(
    image,
    *,
    width: int | None,
    height: int | None,
    max_width: int | None,
    max_height: int | None,
    fill_width: int | None,
    fill_height: int | None,
):
    from PIL import Image, ImageOps

    if fill_width or fill_height:
        if not fill_width or not fill_height:
            raise HTTPException(
                status_code=400,
                detail="Both fill_width and fill_height are required for fill transforms",
            )
        return ImageOps.fit(image, (fill_width, fill_height), method=Image.Resampling.LANCZOS)
    if width or height:
        target_width = width or round(image.width * (height / image.height))
        target_height = height or round(image.height * (width / image.width))
        return image.resize((target_width, target_height), Image.Resampling.LANCZOS)
    if max_width or max_height:
        image.thumbnail(
            (
                max_width or image.width,
                max_height or image.height,
            ),
            Image.Resampling.LANCZOS,
        )
    return image


def _serialize_transformed_image(image, output_format: str, quality: int | None) -> bytes:
    if output_format == "JPEG" and image.mode in {"RGBA", "LA"}:
        from PIL import Image

        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        image = background

    output = BytesIO()
    save_kwargs = {}
    if output_format in {"JPEG", "WEBP", "AVIF"}:
        save_kwargs["quality"] = quality or 85
    image.save(output, format=output_format, **save_kwargs)
    return output.getvalue()


def _transform_image_bytes(
    image_bytes: bytes,
    *,
    content_type: str,
    width: int | None,
    height: int | None,
    max_width: int | None,
    max_height: int | None,
    quality: int | None,
    image_format: ImageFormat | None,
    fill_width: int | None,
    fill_height: int | None,
) -> tuple[bytes, str]:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Image transform backend is not installed",
        )

    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    except UnidentifiedImageError:
        raise HTTPException(status_code=415, detail="Image is not transformable")

    image = _apply_image_transform(
        image,
        width=width,
        height=height,
        max_width=max_width,
        max_height=max_height,
        fill_width=fill_width,
        fill_height=fill_height,
    )
    output_format = _pil_format_for_content_type(image_format, content_type)
    return (
        _serialize_transformed_image(image, output_format, quality),
        _image_media_type_for_pil_format(output_format),
    )


def _transformed_image_bytes_response(
    image_bytes: bytes,
    *,
    content_type: str,
    width: int | None,
    height: int | None,
    max_width: int | None,
    max_height: int | None,
    quality: int | None,
    image_format: ImageFormat | None,
    fill_width: int | None,
    fill_height: int | None,
) -> Response:
    content, media_type = _transform_image_bytes(
        image_bytes,
        content_type=content_type,
        width=width,
        height=height,
        max_width=max_width,
        max_height=max_height,
        quality=quality,
        image_format=image_format,
        fill_width=fill_width,
        fill_height=fill_height,
    )
    return Response(
        content=content,
        media_type=media_type,
    )


def _transformed_image_response(
    storage_path: Path,
    *,
    width: int | None,
    height: int | None,
    max_width: int | None,
    max_height: int | None,
    quality: int | None,
    image_format: ImageFormat | None,
    fill_width: int | None,
    fill_height: int | None,
) -> Response:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Image transform backend is not installed",
        )

    try:
        with Image.open(storage_path) as source_image:
            image = source_image.convert("RGBA")
    except UnidentifiedImageError:
        raise HTTPException(status_code=415, detail="Stored image is not transformable")

    image = _apply_image_transform(
        image,
        width=width,
        height=height,
        max_width=max_width,
        max_height=max_height,
        fill_width=fill_width,
        fill_height=fill_height,
    )

    output_format = _pil_format_for_image_format(image_format, storage_path)
    return Response(
        content=_serialize_transformed_image(image, output_format, quality),
        media_type=_image_media_type_for_pil_format(output_format),
    )


@router.get("/images/proxy")
async def proxy_artwork_image(
    request: Request,
    url: str = Query(..., min_length=1, max_length=4096),
    width: int | None = Query(None, ge=1, le=8192),
    height: int | None = Query(None, ge=1, le=8192),
    max_width: int | None = Query(None, ge=1, le=8192),
    max_height: int | None = Query(None, ge=1, le=8192),
    quality: int | None = Query(None, ge=1, le=100),
    format: ImageFormat | None = Query(None),
    fill_width: int | None = Query(None, ge=1, le=8192),
    fill_height: int | None = Query(None, ge=1, le=8192),
):
    """Proxy and optionally cache remote artwork from known metadata providers."""
    _validate_artwork_proxy_url(url)
    artwork_host = urlsplit(url).hostname or "unknown"

    transform_params = {
        key: value
        for key, value in {
            "width": width,
            "height": height,
            "max_width": max_width,
            "max_height": max_height,
            "quality": quality,
            "format": format,
            "fill_width": fill_width,
            "fill_height": fill_height,
        }.items()
        if value is not None
    }
    cache_key = _artwork_cache_key(url, transform_params)
    cache_enabled = _artwork_cache_enabled()
    if_none_match = request.headers.get("if-none-match")

    if cache_enabled:
        for cached_path in _artwork_cache_root().glob(f"{cache_key}.*"):
            media_type = _stored_image_media_type(cached_path)
            headers = _artwork_headers(cache_key, "hit")
            record_artwork_cache_event("hit", artwork_host)
            if if_none_match == headers["ETag"]:
                record_artwork_cache_event("not_modified", artwork_host)
                return Response(status_code=304, headers=headers)
            return FileResponse(cached_path, media_type=media_type, headers=headers)

    content, media_type = await _fetch_remote_image(url)
    if transform_params:
        content, media_type = await asyncio.to_thread(
            _transform_image_bytes,
            content,
            content_type=media_type,
            width=width,
            height=height,
            max_width=max_width,
            max_height=max_height,
            quality=quality,
            image_format=format,
            fill_width=fill_width,
            fill_height=fill_height,
        )

    cache_status = "disabled"
    if cache_enabled:
        cache_path = _artwork_cache_path(cache_key, media_type)
        tmp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
        tmp_path.write_bytes(content)
        tmp_path.replace(cache_path)
        cache_status = "miss"

    record_artwork_cache_event(cache_status, artwork_host)
    headers = _artwork_headers(cache_key, cache_status)
    if if_none_match == headers["ETag"] and cache_enabled:
        return Response(status_code=304, headers=headers)
    return Response(content=content, media_type=media_type, headers=headers)


async def warm_artwork_cache_urls(urls: list[str], limit: int = 40) -> None:
    """Best-effort background warmup for exact remote artwork variants."""
    if not _artwork_cache_enabled():
        return

    warmed = 0
    seen: set[str] = set()
    for url in urls:
        if warmed >= limit:
            return
        if not url or url in seen:
            continue
        seen.add(url)

        try:
            _validate_artwork_proxy_url(url)
            cache_key = _artwork_cache_key(url, {})
            if any(_artwork_cache_root().glob(f"{cache_key}.*")):
                continue

            content, media_type = await _fetch_remote_image(url)
            cache_path = _artwork_cache_path(cache_key, media_type)
            tmp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
            tmp_path.write_bytes(content)
            tmp_path.replace(cache_path)
            record_artwork_cache_event("warmup", urlsplit(url).hostname)
            warmed += 1
        except Exception as exc:
            record_artwork_cache_event("warmup_failed", urlsplit(url).hostname)
            logger.debug("Failed to warm artwork cache for %s: %s", url, exc)


def _normalize_identify_result(raw: dict) -> dict | None:
    title = raw.get("title") or raw.get("name")
    provider_id = raw.get("provider_id") or raw.get("id") or raw.get("guid")
    if not isinstance(title, str) or not title.strip() or not provider_id:
        return None
    provider = raw.get("provider") if isinstance(raw.get("provider"), str) else "metadata"
    score = raw.get("score")
    if not isinstance(score, (int, float)):
        score = None
    return {
        "provider": provider.strip(),
        "provider_id": str(provider_id),
        "title": title.strip(),
        "original_title": raw.get("original_title")
        if isinstance(raw.get("original_title"), str)
        else None,
        "description": raw.get("description")
        if isinstance(raw.get("description"), str)
        else raw.get("overview")
        if isinstance(raw.get("overview"), str)
        else None,
        "tagline": raw.get("tagline") if isinstance(raw.get("tagline"), str) else None,
        "release_date": _parse_datetime(
            raw.get("release_date") or raw.get("first_air_date") or raw.get("date")
        ),
        "poster_path": raw.get("poster_path")
        if isinstance(raw.get("poster_path"), str)
        else raw.get("poster")
        if isinstance(raw.get("poster"), str)
        else None,
        "backdrop_path": raw.get("backdrop_path")
        if isinstance(raw.get("backdrop_path"), str)
        else raw.get("backdrop")
        if isinstance(raw.get("backdrop"), str)
        else None,
        "score": score,
    }


def _identify_candidates(media_item: MediaItem) -> list[dict]:
    extra_data = _load_media_extra_data(media_item)
    candidates: list[dict] = []
    for key in ("identify_results", "remote_metadata_results"):
        raw_candidates = extra_data.get(key)
        if isinstance(raw_candidates, list):
            candidates.extend(raw for raw in raw_candidates if isinstance(raw, dict))

    normalized = [_normalize_identify_result(raw) for raw in candidates]
    return [candidate for candidate in normalized if candidate is not None]


def _find_identify_candidate(
    media_item: MediaItem,
    *,
    provider: str,
    provider_id: str,
) -> dict | None:
    provider_key = provider.strip().lower()
    provider_id_key = provider_id.strip()
    for candidate in _identify_candidates(media_item):
        if (
            candidate["provider"].lower() == provider_key
            and candidate["provider_id"] == provider_id_key
        ):
            return candidate
    return None


def _provider_media_type(media_item: MediaItem) -> str:
    media_type = media_item.media_type.value
    if media_type in {"SHOWS", "SEASONS", "EPISODES"}:
        return "show"
    if media_type == "GAMES":
        return "game"
    if media_type in {"MUSIC", "ARTISTS", "ALBUMS", "SONGS"}:
        return "music"
    return "movie"


def _provider_id_for_media_item(media_item: MediaItem, provider: str) -> str | None:
    extra_data = _load_media_extra_data(media_item)
    external_ids = extra_data.get("external_ids")
    if isinstance(external_ids, dict):
        provider_id = external_ids.get(provider)
        if provider_id:
            return str(provider_id)
    return None



# ==================== Media Items CRUD ====================


@router.get("", response_model=PaginatedMediaSummaryResponse)
async def list_media_items(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    filters: MediaListQuery = Depends(),
):
    """List media items with filtering and pagination."""
    service = LibraryService(db)

    if not filters.media_type and filters.library_guid:
        library = await service.get_library(filters.library_guid)
        if library:
            filters.media_type = media_type_for_library(library.type)
            logger.info(
                "Inferred media_type %s from library %s",
                filters.media_type,
                library.name,
            )

    if filters.media_type:
        require_library_access_for_media_type(
            current_user,
            permissions,
            filters.media_type,
        )

    filter_kwargs = filters.service_kwargs(
        user_guid=current_user.guid,
        max_age=max_age_for_user(current_user),
        allowed_media_types=allowed_media_types_for_permissions(
            current_user,
            permissions,
        ),
    )
    items = await service.list_media_items(
        **filter_kwargs,
        limit=filters.per_page,
        offset=filters.offset,
        order_by=filters.order_by,
        order_desc=filters.order_desc,
        slim=True,
    )
    total = await service.count_media_items(**filter_kwargs)
    total_pages = math.ceil(total / filters.per_page) if total > 0 else 1
    items_read = [MediaItemSummary.model_validate(item) for item in items]

    await TranslationService(db).apply_translations(
        items_read,
        current_user.ui_language,
    )

    return PaginatedMediaSummaryResponse(
        items=items_read,
        total=total,
        page=filters.page,
        per_page=filters.per_page,
        total_pages=total_pages,
    )

@router.post("", response_model=MediaItemRead)
async def create_media_item(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item: MediaItemCreate,
):
    """Create a new media item."""
    service = LibraryService(db)

    media_item = await service.create_media_item(
        title=item.title,
        media_type=item.media_type,
        parent_guid=item.parent_guid,
        sequence_number=item.sequence_number,
        original_title=item.original_title,
        description=item.description,
        tagline=item.tagline,
        release_date=item.release_date,
        poster_path=item.poster_path,
        backdrop_path=item.backdrop_path,
        availability_status=item.availability_status,
        extra_data=item.extra_data,
    )

    # Re-fetch with relationships to avoid lazy-loading in async context
    media_item = await service.get_media_item(
        media_item.guid,
        load_files=True,
        load_releases=True,
        load_external_ids=True,
    )

    await clear_rendered_layout_cache("media_changed")
    return MediaItemRead.model_validate(media_item)


@router.get("/{item_guid}", response_model=MediaItemDetail)
async def get_media_item(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
    load_files: bool = Query(True, description="Load associated files"),
    load_releases: bool = Query(True, description="Load available releases"),
    load_external_ids: bool = Query(True, description="Load external IDs"),
):
    """Get a specific media item by GUID."""
    service = LibraryService(db)

    media_item = await service.get_media_item(
        item_guid,
        load_files=load_files,
        load_releases=load_releases,
        load_external_ids=load_external_ids,
    )

    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_read_access(
        current_user,
        permissions,
        media_item,
        hide_age_denials=True,
    )

    item_dict = await MediaDetailService(db).build_detail_payload(
        media_item,
        library_service=service,
        ui_language=current_user.ui_language,
        load_files=load_files,
        load_releases=load_releases,
        load_external_ids=load_external_ids,
    )
    return MediaItemDetail(**item_dict)


@router.get("/{item_guid}/trailers", response_model=MediaTrailersResponse)
async def get_media_trailers(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Return metadata-backed trailers for a media item."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_read_access(
        current_user,
        permissions,
        media_item,
        hide_age_denials=True,
    )

    trailers = [
        MediaTrailer(**candidate)
        for candidate in sorted(
            _trailer_candidates(media_item),
            key=lambda item: (
                item.get("published_at") or datetime.min.replace(tzinfo=UTC),
                item.get("official") is True,
            ),
            reverse=True,
        )
    ]
    return MediaTrailersResponse(items=trailers, total=len(trailers))


@router.put("/{item_guid}/trailers", response_model=MediaTrailersResponse)
async def update_media_trailers(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    update: MediaTrailersUpdate,
):
    """Replace manually managed trailers for a media item."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    extra_data = _load_media_extra_data(media_item)
    extra_data["trailers"] = [
        item.model_dump(mode="json", exclude_none=True) for item in update.items
    ]
    media_item.extra_data = json.dumps(extra_data, sort_keys=True)
    media_item.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(media_item)

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="metadata.trailers_update",
            message=f"Updated trailers for {media_item.title}",
            entity_type="media_item",
            entity_guid=media_item.guid,
            extra_data=json.dumps({"count": len(update.items)}, sort_keys=True),
        ),
        actor_guid=current_user.guid,
        commit=False,
    )
    await db.commit()
    await db.refresh(media_item)

    await clear_rendered_layout_cache("media_changed")
    trailers = [MediaTrailer(**candidate) for candidate in _trailer_candidates(media_item)]
    return MediaTrailersResponse(items=trailers, total=len(trailers))


@router.patch("/{item_guid}", response_model=MediaItemRead)
async def update_media_item(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    update: MediaItemUpdate,
):
    """Update a media item."""
    service = LibraryService(db)

    # Build update dict from non-None fields
    update_data = update.model_dump(exclude_unset=True)

    media_item = await service.update_media_item(item_guid, **update_data)

    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    # Re-fetch with relationships to avoid lazy-loading in async context
    media_item = await service.get_media_item(
        media_item.guid,
        load_files=True,
        load_releases=True,
        load_external_ids=True,
    )

    await clear_rendered_layout_cache("media_changed")
    return MediaItemRead.model_validate(media_item)


@router.put("/{item_guid}/metadata/manual", response_model=MediaItemRead)
async def update_media_item_manual_metadata(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    update: ManualMetadataUpdate,
):
    """Apply audited manual metadata edits to a media item."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    update_data = update.model_dump(exclude_unset=True)
    custom_metadata = update_data.pop("custom_metadata", None)
    changed_fields: list[str] = []

    for field_name, value in update_data.items():
        if getattr(media_item, field_name) != value:
            setattr(media_item, field_name, value)
            changed_fields.append(field_name)

    if custom_metadata is not None:
        extra_data = _load_media_extra_data(media_item)
        manual_metadata = extra_data.get("manual_metadata")
        if not isinstance(manual_metadata, dict):
            manual_metadata = {}
        manual_metadata.update(custom_metadata)
        extra_data["manual_metadata"] = manual_metadata
        media_item.extra_data = json.dumps(extra_data, sort_keys=True)
        changed_fields.append("custom_metadata")

    media_item.last_metadata_updated_at = datetime.now(UTC)
    media_item.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(media_item)

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="metadata.manual_update",
            message=f"Manually updated metadata for {media_item.title}",
            entity_type="media_item",
            entity_guid=media_item.guid,
            extra_data=json.dumps(
                {
                    "changed_fields": sorted(set(changed_fields)),
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
        commit=False,
    )
    await db.commit()
    await db.refresh(media_item)

    media_item = await service.get_media_item(
        media_item.guid,
        load_files=True,
        load_releases=True,
        load_external_ids=True,
    )
    await clear_rendered_layout_cache("media_changed")
    return MediaItemRead.model_validate(media_item)


@router.get("/{item_guid}/metadata/identify", response_model=MetadataIdentifyResponse)
async def search_media_identify_candidates(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    item_guid: uuid.UUID,
    provider: str | None = Query(None),
):
    """Return provider identification candidates stored for a media item."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    provider_filter = provider.strip().lower() if provider else None
    candidates = []
    for candidate in _identify_candidates(media_item):
        if provider_filter and candidate["provider"].lower() != provider_filter:
            continue
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: item.get("score") if item.get("score") is not None else 0,
        reverse=True,
    )
    items = [MetadataIdentifyResult(**candidate) for candidate in candidates]
    return MetadataIdentifyResponse(items=items, total=len(items))


@router.get(
    "/{item_guid}/metadata/identify/live",
    response_model=MetadataIdentifyResponse,
)
async def search_live_media_identify_candidates(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    item_guid: uuid.UUID,
    provider: str,
    query: str | None = Query(None, min_length=1),
    limit: int = Query(10, ge=1, le=25),
):
    """Query a configured metadata provider for live identification candidates."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    try:
        candidates = await MetadataService(db).search_identify_candidates(
            domain=provider.strip().lower(),
            query=query or media_item.title,
            media_type=_provider_media_type(media_item),
            year=media_item.release_date.year if media_item.release_date else None,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    normalized = [_normalize_identify_result(candidate) for candidate in candidates]
    items = [
        MetadataIdentifyResult(**candidate)
        for candidate in normalized
        if candidate is not None
    ]
    return MetadataIdentifyResponse(items=items, total=len(items))


@router.put("/{item_guid}/metadata/identify", response_model=MediaItemRead)
async def apply_media_identify_candidate(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    body: MetadataIdentifyApply,
):
    """Apply a stored provider identification candidate to a media item."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    candidate = _find_identify_candidate(
        media_item,
        provider=body.provider,
        provider_id=body.provider_id,
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Metadata identify result not found")

    fields = (
        "title",
        "original_title",
        "description",
        "tagline",
        "release_date",
        "poster_path",
        "backdrop_path",
    )
    changed_fields: list[str] = []
    for field_name in fields:
        value = candidate.get(field_name)
        if value is not None and getattr(media_item, field_name) != value:
            setattr(media_item, field_name, value)
            changed_fields.append(field_name)

    extra_data = _load_media_extra_data(media_item)
    external_ids = extra_data.get("external_ids")
    if not isinstance(external_ids, dict):
        external_ids = {}
    external_ids[candidate["provider"]] = candidate["provider_id"]
    extra_data["external_ids"] = external_ids
    media_item.extra_data = json.dumps(extra_data, sort_keys=True)
    changed_fields.append("external_ids")

    media_item.last_metadata_updated_at = datetime.now(UTC)
    media_item.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(media_item)

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="metadata.identify_apply",
            message=f"Applied {candidate['provider']} metadata to {media_item.title}",
            entity_type="media_item",
            entity_guid=media_item.guid,
            extra_data=json.dumps(
                {
                    "provider": candidate["provider"],
                    "provider_id": candidate["provider_id"],
                    "changed_fields": sorted(set(changed_fields)),
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
        commit=False,
    )
    await db.commit()
    await db.refresh(media_item)

    media_item = await service.get_media_item(
        media_item.guid,
        load_files=True,
        load_releases=True,
        load_external_ids=True,
    )
    await clear_rendered_layout_cache("media_changed")
    return MediaItemRead.model_validate(media_item)


@router.delete("/{item_guid}")
async def delete_media_item(
    db: DatabaseSession,
    current_user: CurrentUser,
    item_guid: uuid.UUID,
):
    """Delete a media item (cascades to files, releases, etc.)."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_mutation_access(current_user, media_item)

    await service.delete_media_item(item_guid)
    await clear_rendered_layout_cache("media_changed")
    return {"message": "Media item deleted successfully"}


# ==================== Search ====================


@router.get("/search/query", response_model=MediaSearchResponse)
async def search_media_items(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    # 1..200 chars — long enough for real titles, short enough to keep LIKE
    # patterns cheap even without an index.
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    media_type: MediaType | None = Query(None, description="Filter by media type"),
    library_guid: uuid.UUID | None = Query(None, description="Filter by library"),
    limit: int = Query(50, ge=1, le=100, description="Max results"),
):
    """Search media items by title."""
    # Check library access for filtered media type
    if media_type:
        require_library_access_for_media_type(current_user, permissions, media_type)

    service = LibraryService(db)

    results = await service.search_media_items(
        query_string=q,
        media_type=media_type,
        limit=limit,
        slim=True,
        allowed_media_types=allowed_media_types_for_permissions(current_user, permissions),
        max_age=max_age_for_user(current_user),
    )

    results_read = [MediaItemSummary.model_validate(item) for item in results]

    ts = TranslationService(db)
    await ts.apply_translations(results_read, current_user.ui_language)

    return MediaSearchResponse(results=results_read, total=len(results_read))


# ==================== Hierarchical Operations ====================


@router.get("/{item_guid}/similar", response_model=list[MediaItemSummary])
async def get_media_item_similar(
    db: DatabaseSession,
    item_guid: uuid.UUID,
    limit: int = Query(20, ge=1, le=50),
    current_user=Depends(get_current_user_optional),
):
    """Return items similar to the given movie or show.

    Item-anchored; computed on demand (not list-backed). Uses TMDB
    similar + recommendations merged with an internal genre-overlap fallback.
    """
    item_res = await db.execute(
        select(MediaItem).where(MediaItem.guid == item_guid)
    )
    item = item_res.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")

    svc = RecommendationService(db)
    try:
        similar_items = await svc.get_similar_items(
            item,
            user_uuid=(current_user.guid if current_user else None),
            limit=limit,
        )
    finally:
        await svc.close()

    out: list[MediaItemSummary] = []
    for mi in similar_items:
        out.append(
            MediaItemSummary(
                guid=mi.guid,
                media_type=mi.media_type,
                title=mi.title,
                original_title=mi.original_title,
                description=mi.description,
                release_date=mi.release_date,
                poster_path=mi.poster_path,
                backdrop_path=mi.backdrop_path,
                availability_status=mi.availability_status,
                parent_guid=mi.parent_guid,
                sequence_number=mi.sequence_number,
            )
        )
    return out


@router.get("/{item_guid}/children", response_model=list[MediaItemRead])
async def get_media_item_children(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
    order_by_sequence: bool = Query(
        True, description="Order by sequence number (season #, episode #, track #)"
    ),
):
    """
    Get child media items.

    Examples:
    - Seasons of a show
    - Episodes of a season
    - Tracks of an album
    """
    service = LibraryService(db)

    children = await service.get_children(
        parent_guid=item_guid, order_by_sequence=order_by_sequence
    )

    child_guids = [child.guid for child in children]
    grandchild_counts: dict[uuid.UUID, int] = {}
    if child_guids:
        count_result = await db.execute(
            select(MediaItem.parent_guid, func.count(MediaItem.guid))
            .where(MediaItem.parent_guid.in_(child_guids))
            .group_by(MediaItem.parent_guid)
        )
        grandchild_counts = {row[0]: row[1] for row in count_result.all()}

    result = []
    for child in children:
        child_read = MediaItemRead.model_validate(child)
        child_read.children_count = grandchild_counts.get(child.guid, 0)
        result.append(child_read)

    ts = TranslationService(db)
    await ts.apply_translations(result, current_user.ui_language)

    return result


@router.get("/shows/{show_guid}/hierarchy", response_model=ShowWithHierarchy)
async def get_show_hierarchy(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    show_guid: uuid.UUID,
):
    """
    Get complete show hierarchy with all seasons and episodes.

    Returns structured data with show → seasons → episodes.
    """
    service = LibraryService(db)

    # Get show
    show = await service.get_media_item(
        show_guid, load_files=True, load_releases=True, load_external_ids=True
    )
    if not show or show.media_type not in [MediaType.SHOWS, "SHOWS"]:
        raise HTTPException(status_code=404, detail="Show not found")

    require_media_read_access(
        current_user,
        permissions,
        show,
        hide_age_denials=True,
    )

    seasons = await service.get_children(show_guid, order_by_sequence=True)
    episodes_by_season = await service.get_children_bulk(
        [season.guid for season in seasons], order_by_sequence=True
    )

    hierarchy = ShowWithHierarchy(show=MediaItemRead.model_validate(show), seasons=[])
    for season in seasons:
        episodes = episodes_by_season.get(season.guid, [])
        hierarchy.seasons.append(
            SeasonWithEpisodes(
                season=MediaItemRead.model_validate(season),
                episodes=[MediaItemRead.model_validate(ep) for ep in episodes],
            )
        )

    return hierarchy


@router.get("/albums/{album_guid}/tracks", response_model=AlbumWithTracks)
async def get_album_tracks(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    album_guid: uuid.UUID,
):
    """Get album with all tracks."""
    service = LibraryService(db)

    # Get album
    album = await service.get_media_item(
        album_guid, load_files=True, load_releases=True, load_external_ids=True
    )
    if not album or album.media_type not in [MediaType.ALBUMS, "ALBUMS", "album"]:
        raise HTTPException(status_code=404, detail="Album not found")

    require_media_read_access(
        current_user,
        permissions,
        album,
        hide_age_denials=True,
    )

    # Get tracks
    tracks = await service.get_children(album_guid, order_by_sequence=True)

    return AlbumWithTracks(
        album=MediaItemRead.model_validate(album),
        tracks=[MediaItemRead.model_validate(track) for track in tracks],
    )


# ==================== Releases ====================


@router.get("/{item_guid}/releases", response_model=PaginatedMediaReleasesResponse)
async def get_media_item_releases(
    db: DatabaseSession,
    current_user: CurrentUser,
    item_guid: uuid.UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    rescore: bool = Query(True, description="Re-score releases with current rules"),
):
    """Get available releases for a media item.

    Releases are re-scored on each request by default to reflect any
    changes to scoring rules or preferences.
    """
    service = LibraryService(db)

    # Verify item exists
    media_item = await service.get_media_item(item_guid, load_releases=True)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    # Get releases
    releases = media_item.releases

    # Re-score releases if requested
    if rescore and releases:
        releases = await service.rescore_releases(media_item, releases)

    total = len(releases)

    # Sort by score descending before pagination
    releases = sorted(releases, key=lambda r: r.score or 0, reverse=True)

    start = (page - 1) * per_page
    end = start + per_page
    paginated_releases = releases[start:end]

    total_pages = math.ceil(total / per_page) if total > 0 else 1

    releases_read = [MediaReleaseRead.model_validate(r) for r in paginated_releases]

    return PaginatedMediaReleasesResponse(
        items=releases_read,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.delete("/{item_guid}/releases/{release_guid}", status_code=204)
async def delete_media_release(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    item_guid: uuid.UUID,
    release_guid: uuid.UUID,
):
    """Delete a single release for a media item (admin only)."""
    service = MediaService(db)
    if not await service.delete_release(release_guid, media_item_guid=item_guid):
        raise HTTPException(status_code=404, detail="Release not found")


@router.delete("/{item_guid}/releases", status_code=204)
async def delete_all_media_releases(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    item_guid: uuid.UUID,
):
    """Delete all releases for a media item (admin only)."""
    if await db.get(MediaItem, item_guid) is None:
        raise HTTPException(status_code=404, detail="Media item not found")
    service = MediaService(db)
    await service.delete_all_releases(item_guid)


@router.post("/{item_guid}/releases", response_model=MediaReleaseRead)
async def create_media_release(
    db: DatabaseSession,
    current_user: CurrentUser,
    item_guid: uuid.UUID,
    release: MediaReleaseCreate,
):
    """Create a new release for a media item."""
    service = LibraryService(db)

    # Verify item exists
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_mutation_access(current_user, media_item)

    # Create release
    new_release = await service.create_media_release(
        media_item_guid=item_guid,
        title=release.title,
        size=release.size,
        quality=release.quality,
        score=release.score,
        indexer_guid=release.indexer_guid,
        publish_date=release.publish_date,
    )

    # Re-fetch with links to avoid lazy-loading in async context

    result = await db.execute(
        select(MediaRelease)
        .where(MediaRelease.guid == new_release.guid)
        .options(selectinload(MediaRelease.links))
    )
    new_release = result.scalars().first()

    return MediaReleaseRead.model_validate(new_release)


@router.post("/{item_guid}/releases/search", status_code=202)
async def search_media_releases(
    db: DatabaseSession,
    item_guid: uuid.UUID,
    current_user: CurrentSuperuser,
):
    """Trigger a release search for a media item (admin only).

    Queues a background task to search all configured indexers for releases.
    Results will appear in the releases list once the search completes.
    """
    if await db.get(MediaItem, item_guid) is None:
        raise HTTPException(status_code=404, detail="Media item not found")
    await worker_tasks.search_media_item_releases.kiq(
        str(item_guid),
        str(current_user.guid),
    )

    return {"message": "Release search queued", "item_guid": str(item_guid)}


@router.post("/{item_guid}/releases/{release_guid}/download", status_code=202)
async def download_media_release(
    db: DatabaseSession,
    current_user: CurrentUser,
    item_guid: uuid.UUID,
    release_guid: uuid.UUID,
):
    """Trigger a manual download for a specific release.

    Queues the release for download using the first available download link.
    """

    # Verify media item exists
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    # Get the release with its links
    result = await db.execute(
        select(MediaRelease)
        .where(
            MediaRelease.guid == release_guid, MediaRelease.media_item_guid == item_guid
        )
        .options(selectinload(MediaRelease.links))
    )
    release = result.scalar_one_or_none()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    if not release.links:
        raise HTTPException(status_code=400, detail="Release has no download links")

    # Enforce per-user indexer-downloads rate limit (manual release-pick).
    perms = await PermissionService(db).resolve_user_permissions(current_user.guid)
    allowed = await check_and_record(
        current_user.guid, "indexer_downloads",
        perms.indexer_downloads_limit,
        perms.indexer_downloads_period_minutes,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Download rate limit reached. Please wait.",
        )

    # Pick the first link
    link = release.links[0]

    # Dispatch the appropriate worker task based on media type
    if media_item.media_type in (MediaType.SONGS, MediaType.ALBUMS):
        await add_music_download.kiq(
            str(link.guid),
            str(current_user.guid),
        )
    elif media_item.media_type == MediaType.SHOWS:
        await add_show_download.kiq(
            str(link.guid),
            str(current_user.guid),
        )
    else:
        await add_download.kiq(str(link.guid), str(current_user.guid))

    return {"status": "queued", "release_title": release.title}


@router.get("/{item_guid}/downloads")
async def get_media_item_downloads(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    item_guid: uuid.UUID,
):
    """Get all downloads associated with a media item (superuser only)."""

    # Verify item exists
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    # Join: Download → MediaReleaseLink → MediaRelease (filtered by media_item_guid)
    result = await db.execute(
        select(Download)
        .join(
            MediaReleaseLink, Download.media_release_link_guid == MediaReleaseLink.guid
        )
        .join(MediaRelease, MediaReleaseLink.media_release_guid == MediaRelease.guid)
        .where(MediaRelease.media_item_guid == item_guid)
        .options(
            selectinload(Download.media_release_link),
            selectinload(Download.started_by),
        )
        .order_by(Download.created_at.desc())
    )
    downloads = result.scalars().all()

    return [
        {
            "guid": str(d.guid),
            "title": d.title,
            "status": d.status,
            "status_phase": download_phase(d.status),
            "status_detail": d.error_reason,
            "progress": d.progress,
            "external_id": d.external_id,
            "error_reason": d.error_reason,
            "created_at": d.created_at,
            "started_by_name": (
                f"{d.started_by.first_name} {d.started_by.last_name}".strip()
                if d.started_by
                else None
            ),
        }
        for d in downloads
    ]


# ==================== External IDs ====================


@router.get("/{item_guid}/external-links", response_model=MediaExternalLinksResponse)
async def get_media_external_links(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Return normalized provider URLs for a media item's stored external IDs."""
    service = LibraryService(db)
    media_item = await service.get_media_item(
        item_guid,
        load_files=False,
        load_releases=False,
        load_external_ids=True,
    )
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_read_access(
        current_user,
        permissions,
        media_item,
        hide_age_denials=True,
    )

    items = _external_links_for_media(media_item)
    return MediaExternalLinksResponse(items=items, total=len(items))


@router.get("/external/{provider}/{external_id}", response_model=MediaItemDetail | None)
async def get_by_external_id(
    db: DatabaseSession,
    current_user: CurrentUser,
    provider: str,
    external_id: str,
    media_type: MediaType | None = Query(None, description="Filter by media type"),
):
    """Get media item by external ID (e.g., TMDB, IGDB)."""
    service = LibraryService(db)

    media_item = await service.get_by_external_id(
        provider=provider, external_id=external_id, media_type=media_type
    )

    if not media_item:
        raise HTTPException(
            status_code=404, detail="Media item not found with that external ID"
        )

    media_item = await service.get_media_item(
        media_item.guid,
        load_files=False,
        load_releases=False,
        load_external_ids=True,
    )
    return _minimal_media_item_detail(media_item)


# ==================== Availability Status ====================


@router.patch("/{item_guid}/availability")
async def update_availability_status(
    db: DatabaseSession,
    current_user: CurrentUser,
    item_guid: uuid.UUID,
    status: AvailabilityStatus,
):
    """Update the availability status of a media item."""
    service = LibraryService(db)

    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_mutation_access(current_user, media_item)

    media_item = await service.update_availability_status(item_guid, status)

    return {"message": "Availability status updated", "status": status}


# ==================== Stream Information ====================


@router.get("/{item_guid}/streams")
async def get_media_streams(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """
    Get audio, subtitle, and quality options for a media item.

    Returns the available audio streams, subtitle streams, and quality options
    based on the media item's files and probe data.
    """
    service = LibraryService(db)
    media_item = await service.get_media_item(
        item_guid, load_files=True, load_releases=True
    )
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_read_access(
        current_user,
        permissions,
        media_item,
        hide_age_denials=True,
    )

    return MediaStreamOptionsService().build_options(media_item)


@router.get("/{item_guid}/media-sources")
async def get_media_sources(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Return concrete selectable media sources for a media item."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid, load_files=True)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_read_access(
        current_user,
        permissions,
        media_item,
        hide_age_denials=True,
    )

    sources = []
    sorted_files = sorted(
        media_item.files or [],
        key=lambda file: (
            -(file.height or 0),
            -(file.bitrate or 0),
            file.file_name or file.file_path,
        ),
    )
    for index, media_file in enumerate(sorted_files):
        sources.append(
            {
                "id": str(media_file.guid),
                "file_guid": str(media_file.guid),
                "name": media_file.file_name or media_file.file_path.rsplit("/", 1)[-1],
                "path": media_file.file_path,
                "container": media_file.format,
                "codec": media_file.codec,
                "quality": media_file.quality,
                "width": media_file.width,
                "height": media_file.height,
                "bitrate": media_file.bitrate,
                "duration_seconds": media_file.duration,
                "file_size": media_file.file_size,
                "is_default": index == 0,
                "supports_direct_play": True,
                "supports_direct_stream": True,
                "download_url": f"/api/media/{media_item.guid}/files/{media_file.guid}/download",
                "stream_url": f"/api/stream/{media_item.guid}?file_guid={media_file.guid}",
            }
        )

    return {
        "item_guid": str(media_item.guid),
        "title": media_item.title,
        "media_type": media_item.media_type.value,
        "items": sources,
        "total": len(sources),
    }


@router.post("/{item_guid}/refresh-metadata")
async def refresh_media_metadata(
    db: DatabaseSession,
    current_user: CurrentUser,
    item_guid: uuid.UUID,
):
    """
    Trigger a metadata refresh for a media item.

    This queues a background task to fetch updated metadata from external providers
    (TMDB for movies/shows, IGDB for games, etc.).
    """
    service = LibraryService(db)

    # Verify item exists
    media_item = await service.get_media_item(
        item_guid, load_files=False, load_releases=False
    )
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_mutation_access(current_user, media_item)

    # Queue the refresh task
    await worker_tasks.refresh_media_item_metadata.kiq(str(item_guid))

    return {"message": "Metadata refresh queued", "item_guid": item_guid}


# ==================== Availability ====================


@router.get("/{item_guid}/availability")
async def get_media_availability(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Get availability status for a media item. Triggers auto-search if needed."""
    result = await db.execute(select(MediaItem).where(MediaItem.guid == item_guid))
    media_item = result.scalars().first()
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")
    require_media_read_access(
        current_user,
        permissions,
        media_item,
        hide_age_denials=True,
    )

    avail = await availability_service.check_availability(
        db,
        media_item,
        current_user.guid,
    )
    return {
        "status": avail.status,
        "target_guid": str(avail.target_guid) if avail.target_guid else None,
        "target_action": avail.target_action,
        "progress_seconds": avail.progress_seconds,
        "download_progress": avail.download_progress,
        "download_status": avail.download_status,
        "download_phase": getattr(avail, "download_phase", None),
        "download_status_detail": getattr(avail, "download_status_detail", None),
        "is_watched": avail.is_watched,
    }


@router.post("/{item_guid}/watch")
async def toggle_media_watch(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Toggle watch status for a media item (notify when available)."""
    # Check media item exists
    result = await db.execute(select(MediaItem).where(MediaItem.guid == item_guid))
    media_item = result.scalars().first()
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")
    require_media_read_access(
        current_user,
        permissions,
        media_item,
        hide_age_denials=True,
    )

    # Check if already watching
    existing = await db.execute(
        select(MediaWatch).where(
            MediaWatch.user_guid == current_user.guid,
            MediaWatch.media_item_guid == item_guid,
        )
    )
    watch = existing.scalars().first()

    if watch:
        await db.delete(watch)
        await db.commit()
        return {"is_watched": False}
    else:
        new_watch = MediaWatch(user_guid=current_user.guid, media_item_guid=item_guid)
        db.add(new_watch)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        return {"is_watched": True}


# ==================== Show Resume ====================


@router.get("/shows/{show_guid}/resume")
async def get_show_resume_episode(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    show_guid: uuid.UUID,
):
    """Get the recommended episode to play next for a show."""
    resume_service = ShowResumeService(db)
    show = await resume_service.get_show(show_guid)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    require_media_read_access(
        current_user,
        permissions,
        show,
        hide_age_denials=True,
    )

    try:
        resume = await resume_service.get_resume_episode(
            show_guid,
            user_guid=current_user.guid,
        )
    except ShowResumeError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc

    return {
        "episode": MediaItemRead.model_validate(resume.episode),
        "action": resume.action,
        "season_number": resume.season_number,
        "episode_number": resume.episode_number,
        "progress_seconds": resume.progress_seconds,
    }


# ==================== Episode Navigation ====================


async def _get_episode_or_raise(db: AsyncSession, episode_guid: uuid.UUID) -> MediaItem:
    """Validate that the given GUID is a child item (episode/track)."""
    result = await db.execute(select(MediaItem).where(MediaItem.guid == episode_guid))
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Episode not found")
    if not item.parent_guid:
        raise HTTPException(status_code=400, detail="This endpoint is only for episodes")
    return item


@router.get("/{episode_guid}/next-episode")
async def get_next_episode(
    db: DatabaseSession,
    current_user: CurrentUser,  # noqa: ARG001
    episode_guid: uuid.UUID,
):
    """Get the next episode/track in sequence, crossing season/album boundaries."""
    await _get_episode_or_raise(db, episode_guid)
    service = MediaService(db)
    result = await service.get_next_sibling(episode_guid)
    return {"next_episode": result}


@router.get("/{episode_guid}/previous-episode")
async def get_previous_episode(
    db: DatabaseSession,
    current_user: CurrentUser,  # noqa: ARG001
    episode_guid: uuid.UUID,
):
    """Get the previous episode/track in sequence, crossing season/album boundaries."""
    await _get_episode_or_raise(db, episode_guid)
    service = MediaService(db)
    result = await service.get_previous_sibling(episode_guid)
    return {"previous_episode": result}


# ==================== File Operations ====================


@router.get("/{item_guid}/images", response_model=MediaImagesResponse)
async def get_media_images(
    db: DatabaseSession,
    current_user: CurrentUser,  # noqa: ARG001
    item_guid: uuid.UUID,
):
    """Return poster/backdrop image paths for a media item."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")
    return MediaImagesResponse(
        poster_path=media_item.poster_path,
        backdrop_path=media_item.backdrop_path,
    )


@router.get("/{item_guid}/images/remote", response_model=RemoteImageSearchResponse)
async def search_media_remote_images(
    db: DatabaseSession,
    current_user: CurrentUser,  # noqa: ARG001
    item_guid: uuid.UUID,
    image_type: ImageType | None = Query(None),
    provider: str | None = Query(None),
    language: str | None = Query(None, max_length=16),
    include_language_neutral: bool = Query(True),
):
    """Return remote image candidates stored for a media item."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    provider_filter = provider.strip().lower() if provider else None
    candidates = []
    for candidate in _remote_image_candidates(media_item):
        if image_type and candidate["image_type"] != image_type:
            continue
        if provider_filter and candidate["provider"].lower() != provider_filter:
            continue
        if not _image_language_matches(
            candidate,
            language=language,
            include_language_neutral=include_language_neutral,
        ):
            continue
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: item.get("score") if item.get("score") is not None else 0,
        reverse=True,
    )
    items = [RemoteImageResult(**candidate) for candidate in candidates]
    return RemoteImageSearchResponse(items=items, total=len(items))


@router.get("/{item_guid}/images/remote/live", response_model=RemoteImageSearchResponse)
async def search_live_media_remote_images(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    item_guid: uuid.UUID,
    provider: str,
    provider_id: str | None = Query(None),
    image_type: ImageType | None = Query(None),
    language: str | None = Query(None, max_length=16),
    include_language_neutral: bool = Query(True),
):
    """Fetch remote image candidates from a configured metadata provider."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    provider_key = provider.strip().lower()
    resolved_provider_id = provider_id or _provider_id_for_media_item(
        media_item,
        provider_key,
    )
    if not resolved_provider_id:
        raise HTTPException(status_code=422, detail="Provider id is required")

    try:
        raw_candidates = await MetadataService(db).search_remote_images(
            domain=provider_key,
            provider_id=resolved_provider_id,
            media_type=_provider_media_type(media_item),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    candidates = []
    for raw_candidate in raw_candidates:
        candidate = _normalize_remote_image(raw_candidate)
        if candidate is None:
            continue
        if image_type and candidate["image_type"] != image_type:
            continue
        if not _image_language_matches(
            candidate,
            language=language,
            include_language_neutral=include_language_neutral,
        ):
            continue
        candidates.append(candidate)
    candidates.sort(
        key=lambda item: item.get("score") if item.get("score") is not None else 0,
        reverse=True,
    )
    items = [RemoteImageResult(**candidate) for candidate in candidates]
    return RemoteImageSearchResponse(items=items, total=len(items))


@router.get(
    "/{item_guid}/images/{image_type}/transform",
    response_model=MediaImageTransformResponse,
)
async def get_media_image_transform(
    db: DatabaseSession,
    current_user: CurrentUser,  # noqa: ARG001
    item_guid: uuid.UUID,
    image_type: ImageType,
    width: int | None = Query(None, ge=1, le=8192),
    height: int | None = Query(None, ge=1, le=8192),
    max_width: int | None = Query(None, ge=1, le=8192),
    max_height: int | None = Query(None, ge=1, le=8192),
    quality: int | None = Query(None, ge=1, le=100),
    format: ImageFormat | None = Query(None),
    fill_width: int | None = Query(None, ge=1, le=8192),
    fill_height: int | None = Query(None, ge=1, le=8192),
):
    """Return a normalized image transform descriptor for clients/proxies."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    source_url = media_item.poster_path if image_type == "poster" else media_item.backdrop_path
    if not source_url:
        raise HTTPException(status_code=404, detail=f"{image_type.title()} image not found")

    transform_params = {
        key: value
        for key, value in {
            "width": width,
            "height": height,
            "max_width": max_width,
            "max_height": max_height,
            "quality": quality,
            "format": format,
            "fill_width": fill_width,
            "fill_height": fill_height,
        }.items()
        if value is not None
    }
    return MediaImageTransformResponse(
        image_type=image_type,
        source_url=source_url,
        transformed_url=_append_image_transform_query(source_url, transform_params),
        width=width,
        height=height,
        max_width=max_width,
        max_height=max_height,
        quality=quality,
        format=format,
        fill_width=fill_width,
        fill_height=fill_height,
    )


@router.get("/{item_guid}/images/{image_type}/proxy")
async def proxy_media_image(
    db: DatabaseSession,
    current_user: CurrentUser,  # noqa: ARG001
    item_guid: uuid.UUID,
    image_type: ImageType,
    width: int | None = Query(None, ge=1, le=8192),
    height: int | None = Query(None, ge=1, le=8192),
    max_width: int | None = Query(None, ge=1, le=8192),
    max_height: int | None = Query(None, ge=1, le=8192),
    quality: int | None = Query(None, ge=1, le=100),
    format: ImageFormat | None = Query(None),
    fill_width: int | None = Query(None, ge=1, le=8192),
    fill_height: int | None = Query(None, ge=1, le=8192),
):
    """Fetch and return the selected remote poster/backdrop through pyrate."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    source_url = media_item.poster_path if image_type == "poster" else media_item.backdrop_path
    if not source_url:
        raise HTTPException(status_code=404, detail=f"{image_type.title()} image not found")

    content, media_type = await _fetch_remote_image(source_url)
    should_transform = any(
        value is not None
        for value in (
            width,
            height,
            max_width,
            max_height,
            quality,
            format,
            fill_width,
            fill_height,
        )
    )
    if should_transform:
        return await asyncio.to_thread(
            _transformed_image_bytes_response,
            content,
            content_type=media_type,
            width=width,
            height=height,
            max_width=max_width,
            max_height=max_height,
            quality=quality,
            image_format=format,
            fill_width=fill_width,
            fill_height=fill_height,
        )
    return Response(content=content, media_type=media_type)


@router.put("/{item_guid}/images/{image_type}", response_model=MediaImagesResponse)
async def set_media_image(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    item_guid: uuid.UUID,
    image_type: ImageType,
    payload: MediaImageUpdate,
):
    """Set or replace a poster/backdrop path for a media item."""
    service = LibraryService(db)
    field_name = "poster_path" if image_type == "poster" else "backdrop_path"
    media_item = await service.update_media_item(item_guid, **{field_name: payload.path})
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")
    await clear_rendered_layout_cache("media_artwork_changed")
    return MediaImagesResponse(
        poster_path=media_item.poster_path,
        backdrop_path=media_item.backdrop_path,
    )


@router.post(
    "/{item_guid}/images/{image_type}/upload",
    response_model=MediaImageUploadResponse,
)
async def upload_media_image(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    image_type: ImageType,
    payload: MediaImageUpload,
):
    """Persist uploaded poster/backdrop image content and select it for the item."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    image_bytes, content_type, extension = _decode_image_upload(payload)
    asset_name = f"{item_guid}-{image_type}-{uuid.uuid4().hex}.{extension}"
    storage_path = _stored_image_path(asset_name)
    storage_path.write_bytes(image_bytes)

    stored_path = f"/api/media/{item_guid}/images/{image_type}/content/{asset_name}"
    field_name = "poster_path" if image_type == "poster" else "backdrop_path"
    updated = await service.update_media_item(
        item_guid,
        commit=False,
        **{field_name: stored_path},
    )
    if not updated:
        storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="Media item not found")

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="metadata.image_upload",
            message=f"Uploaded {image_type} image for {updated.title}",
            entity_type="media_item",
            entity_guid=updated.guid,
            extra_data=json.dumps(
                {
                    "image_type": image_type,
                    "content_type": content_type,
                    "file_name": payload.file_name,
                    "path": stored_path,
                    "size_bytes": len(image_bytes),
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
        commit=False,
    )
    await db.commit()
    await db.refresh(updated)

    await clear_rendered_layout_cache("media_artwork_changed")
    return MediaImageUploadResponse(
        poster_path=updated.poster_path,
        backdrop_path=updated.backdrop_path,
        stored_path=stored_path,
        content_type=content_type,
        size_bytes=len(image_bytes),
    )


@router.get("/{item_guid}/images/{image_type}/content/{asset_name}")
async def get_uploaded_media_image_content(
    db: DatabaseSession,
    current_user: CurrentUser,  # noqa: ARG001
    item_guid: uuid.UUID,
    image_type: ImageType,
    asset_name: str,
):
    """Serve locally uploaded poster/backdrop content selected for a media item."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    selected_path = media_item.poster_path if image_type == "poster" else media_item.backdrop_path
    expected_path = f"/api/media/{item_guid}/images/{image_type}/content/{asset_name}"
    if selected_path != expected_path:
        raise HTTPException(status_code=404, detail="Image not found")

    storage_path = _stored_image_path(asset_name)
    if not storage_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(storage_path, media_type=_stored_image_media_type(storage_path))


@router.get("/{item_guid}/images/{image_type}/content/{asset_name}/transform")
async def transform_uploaded_media_image_content(
    db: DatabaseSession,
    current_user: CurrentUser,  # noqa: ARG001
    item_guid: uuid.UUID,
    image_type: ImageType,
    asset_name: str,
    width: int | None = Query(None, ge=1, le=8192),
    height: int | None = Query(None, ge=1, le=8192),
    max_width: int | None = Query(None, ge=1, le=8192),
    max_height: int | None = Query(None, ge=1, le=8192),
    quality: int | None = Query(None, ge=1, le=100),
    format: ImageFormat | None = Query(None),
    fill_width: int | None = Query(None, ge=1, le=8192),
    fill_height: int | None = Query(None, ge=1, le=8192),
):
    """Serve resized/transcoded content for a locally uploaded poster/backdrop."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    selected_path = media_item.poster_path if image_type == "poster" else media_item.backdrop_path
    expected_path = f"/api/media/{item_guid}/images/{image_type}/content/{asset_name}"
    if selected_path != expected_path:
        raise HTTPException(status_code=404, detail="Image not found")

    storage_path = _stored_image_path(asset_name)
    if not storage_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    return await asyncio.to_thread(
        _transformed_image_response,
        storage_path,
        width=width,
        height=height,
        max_width=max_width,
        max_height=max_height,
        quality=quality,
        image_format=format,
        fill_width=fill_width,
        fill_height=fill_height,
    )


@router.put("/{item_guid}/images", response_model=MediaImagesResponse)
async def set_media_images(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    payload: MediaImagesUpdate,
):
    """Set poster/backdrop paths in one request."""
    service = LibraryService(db)
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        media_item = await service.get_media_item(item_guid)
    else:
        media_item = await service.update_media_item(
            item_guid,
            commit=False,
            **update_data,
        )
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="metadata.images_update",
            message=f"Updated images for {media_item.title}",
            entity_type="media_item",
            entity_guid=media_item.guid,
            extra_data=json.dumps(
                {"updated_fields": sorted(update_data.keys())},
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
        commit=False,
    )
    await db.commit()
    await db.refresh(media_item)
    await clear_rendered_layout_cache("media_artwork_changed")
    return MediaImagesResponse(
        poster_path=media_item.poster_path,
        backdrop_path=media_item.backdrop_path,
    )


@router.put("/{item_guid}/images/{image_type}/remote", response_model=MediaImagesResponse)
async def select_media_remote_image(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    image_type: ImageType,
    payload: RemoteImageSelect,
):
    """Select a remote image candidate as the poster/backdrop path."""
    service = LibraryService(db)
    media_item = await service.get_media_item(item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    candidate = _find_remote_image(
        media_item,
        image_type=image_type,
        provider=payload.provider,
        provider_id=payload.provider_id,
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Remote image not found")

    field_name = "poster_path" if image_type == "poster" else "backdrop_path"
    updated = await service.update_media_item(
        item_guid,
        commit=False,
        **{field_name: candidate["url"]},
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Media item not found")

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="metadata.remote_image_select",
            message=f"Selected {image_type} image for {updated.title}",
            entity_type="media_item",
            entity_guid=updated.guid,
            extra_data=json.dumps(
                {
                    "image_type": image_type,
                    "provider": candidate["provider"],
                    "provider_id": candidate["provider_id"],
                    "url": candidate["url"],
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
        commit=False,
    )
    await db.commit()
    await db.refresh(updated)

    await clear_rendered_layout_cache("media_artwork_changed")
    return MediaImagesResponse(
        poster_path=updated.poster_path,
        backdrop_path=updated.backdrop_path,
    )


@router.delete("/{item_guid}/images/{image_type}", response_model=MediaImagesResponse)
async def delete_media_image(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    item_guid: uuid.UUID,
    image_type: ImageType,
):
    """Clear a poster/backdrop path for a media item."""
    service = LibraryService(db)
    field_name = "poster_path" if image_type == "poster" else "backdrop_path"
    media_item = await service.update_media_item(item_guid, **{field_name: None})
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")
    await clear_rendered_layout_cache("media_artwork_changed")
    return MediaImagesResponse(
        poster_path=media_item.poster_path,
        backdrop_path=media_item.backdrop_path,
    )


@router.delete("/{item_guid}/images", response_model=MediaImagesResponse)
async def delete_media_images(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
):
    """Clear all stored artwork paths for a media item."""
    service = LibraryService(db)
    media_item = await service.update_media_item(
        item_guid,
        commit=False,
        poster_path=None,
        backdrop_path=None,
    )
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="metadata.images_delete",
            message=f"Cleared images for {media_item.title}",
            entity_type="media_item",
            entity_guid=media_item.guid,
            extra_data=json.dumps(
                {"cleared_fields": ["poster_path", "backdrop_path"]},
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
        commit=False,
    )
    await db.commit()
    await db.refresh(media_item)
    await clear_rendered_layout_cache("media_artwork_changed")
    return MediaImagesResponse(
        poster_path=media_item.poster_path,
        backdrop_path=media_item.backdrop_path,
    )


@router.get("/{item_guid}/files/{file_guid}/download")
async def download_media_file(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
    file_guid: uuid.UUID,
):
    """Download a media file that belongs to the requested media item."""
    service = LibraryService(db)

    media_item = await service.get_media_item(item_guid, load_files=True)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_read_access(
        current_user,
        permissions,
        media_item,
        hide_age_denials=True,
    )

    media_file = next((f for f in media_item.files if f.guid == file_guid), None)
    if not media_file:
        raise HTTPException(status_code=404, detail="File not found")

    allowed_roots = await _allowed_download_roots(db, media_item)
    resolved_path = _resolve_download_path(media_file.file_path, allowed_roots)
    filename = _safe_file_name(media_file.file_name, media_file.file_path)

    return FileResponse(
        resolved_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.delete("/{item_guid}/files/{file_guid}", status_code=204)
async def delete_media_file(
    db: DatabaseSession,
    item_guid: uuid.UUID,
    file_guid: uuid.UUID,
    current_user=Depends(get_current_superuser),
    delete_from_disk: bool = Query(False, description="Also delete the file from disk"),
):
    """Delete a media file record (admin only).

    Removes the file entry from the database. Optionally also deletes
    the actual file from disk.
    """
    import os

    service = LibraryService(db)

    media_item = await service.get_media_item(item_guid, load_files=True)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    file = next((f for f in media_item.files if f.guid == file_guid), None)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = file.file_path

    await db.delete(file)
    await db.commit()

    if delete_from_disk and file_path:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as e:
            logger.warning("Could not delete file from disk %s: %s", file_path, e)


@router.post("/{item_guid}/files/{file_guid}/reprobe")
async def reprobe_media_file(
    db: DatabaseSession,
    current_user: CurrentUser,
    item_guid: uuid.UUID,
    file_guid: uuid.UUID,
):
    """Re-probe a media file with FFprobe to update metadata.

    This will re-analyze the file and update resolution, codec, duration,
    bitrate and other technical metadata.
    """
    service = LibraryService(db)

    # Verify media item exists
    media_item = await service.get_media_item(item_guid, load_files=True)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_mutation_access(current_user, media_item)

    # Find the file
    file = next((f for f in media_item.files if f.guid == file_guid), None)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    # Queue the probe task
    await worker_tasks.probe_media_file.kiq(str(file_guid))

    return {
        "message": "File probe queued",
        "file_guid": str(file_guid),
        "file_path": file.file_path,
    }


@router.post("/{item_guid}/files/reprobe-all")
async def reprobe_all_media_files(
    db: DatabaseSession,
    current_user: CurrentUser,
    item_guid: uuid.UUID,
):
    """Re-probe all files for a media item with FFprobe.

    This will re-analyze all files and update their metadata.
    """
    service = LibraryService(db)

    # Verify media item exists
    media_item = await service.get_media_item(item_guid, load_files=True)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_mutation_access(current_user, media_item)

    if not media_item.files:
        raise HTTPException(
            status_code=404, detail="No files found for this media item"
        )

    # Queue probe tasks for all files
    queued = []
    for file in media_item.files:
        await worker_tasks.probe_media_file.kiq(str(file.guid))
        queued.append(str(file.guid))

    return {
        "message": f"Queued {len(queued)} files for probing",
        "file_guids": queued,
    }
