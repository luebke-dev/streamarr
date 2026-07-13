"""Webhook endpoints for external service callbacks.

All custom downloaders (spotify, torrent, usenet) emit the same terminal
webhook payload::

    {
        "id": <job_id>,          # external job id
        "status": <status>,      # "completed" | "done" | "failed"
        "path": <output_base>,   # the downloader's OWN output base path
        "files": [<basename>...],# whitelist of produced files (optional)
        "error": <str>,          # present on failure
        ...                      # name/category/destination are informational
    }

so the three endpoints share a single normalization + handling path
(:func:`_handle_downloader_webhook`).

Path translation (downloader container path -> backend mount path) is
configured in ONE place — :data:`_DEFAULT_MOUNT_MAP`, overridable via the
``DOWNLOADER_MOUNT_MAP`` env var — instead of being duplicated as
per-client ``REMOTE_PREFIX``/``LOCAL_PREFIX`` constants. The downloader
reports its own output base path in ``path`` and the backend applies the
configured remote->local translation for that downloader, so the import no
longer depends on hard-coded container-path constants scattered across the
Python client adapters.
"""

import hmac
import json
import logging
import os

from fastapi import APIRouter, Header, HTTPException, status

from streamarr.api.dependencies import DatabaseSession
from streamarr.config import settings
from streamarr.models.downloads import DownloadStatus
from streamarr.services.download import DownloadService
from streamarr.services.observability import (
    record_download_retry_event,
    record_download_transition,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_WARNED_ABOUT_MISSING_SECRET = False

# Single source of truth for translating a downloader's own output base path
# (as reported in the webhook ``path``) to the path the backend/worker sees
# for the same files. Keyed by downloader name -> (remote_prefix, local_prefix).
# Keying by name is required because two downloaders can write to the same
# in-container path (torrent and usenet-remote both use ``/downloads``) yet be
# mounted at different backend paths. Defaults mirror the bind-mounts in
# docker-compose.yml; override wholesale via the ``DOWNLOADER_MOUNT_MAP`` env
# var (JSON: ``{"<name>": ["<remote_prefix>", "<local_prefix>"], ...}``).
_DEFAULT_MOUNT_MAP: dict[str, tuple[str, str]] = {
    "torrent": ("/downloads", "/torrent-downloads"),
    "spotdl": ("/data/downloads", "/spotdl-downloads"),
    "usenet": ("/downloads", "/downloads"),
}


def _load_mount_map() -> dict[str, tuple[str, str]]:
    """Return the configured downloader mount map (env override or default)."""
    raw = os.environ.get("DOWNLOADER_MOUNT_MAP")
    if not raw:
        return _DEFAULT_MOUNT_MAP
    try:
        parsed = json.loads(raw)
        return {str(k): (str(v[0]), str(v[1])) for k, v in parsed.items()}
    except (ValueError, TypeError, KeyError, IndexError):
        logger.error(
            "Invalid DOWNLOADER_MOUNT_MAP (%r); falling back to defaults", raw
        )
        return _DEFAULT_MOUNT_MAP


def map_download_path(downloader_name: str, remote_path: str) -> str:
    """Translate a downloader's output path to the backend mount path.

    The downloader reports its OWN output base path; this applies the single
    configurable remote->local mount translation for that downloader. An empty
    input resolves to the downloader's local base directory (so callers can use
    it as the "no explicit destination" fallback). Unknown downloaders or
    non-matching prefixes are returned unchanged.
    """
    pair = _load_mount_map().get(downloader_name)
    if not pair:
        return remote_path
    remote_prefix, local_prefix = pair
    if not remote_path:
        return local_prefix
    if remote_prefix and remote_path.startswith(remote_prefix):
        return local_prefix + remote_path[len(remote_prefix):]
    return remote_path


def _is_within_allowed_roots(mapped_path: str) -> bool:
    """Return True iff ``mapped_path`` resolves inside a configured download root.

    The configured mount map's local prefixes are the only directories a
    downloader is ever expected to write into. Enforcing containment here means
    a caller who merely holds the shared webhook secret still can't point the
    importer at an arbitrary server-side directory (e.g. ``path=/etc``): unknown
    prefixes pass through :func:`map_download_path` unchanged and are rejected
    here. ``..`` segments are collapsed before the check so they can't escape.
    """
    if not mapped_path:
        return False
    roots = {local for _, local in _load_mount_map().values() if local}
    if not roots:
        return False
    norm = os.path.normpath(mapped_path)
    for root in roots:
        root_norm = os.path.normpath(root)
        if norm == root_norm or norm.startswith(root_norm + os.sep):
            return True
    return False


def _verify_webhook_secret(x_webhook_secret: str | None, downloader_name: str) -> None:
    """Fail with 401 if the shared-secret header doesn't match.

    Fails closed: if ``DOWNLOADER_WEBHOOK_SECRET`` is unset the endpoint is
    unavailable rather than accepting unauthenticated callbacks.
    """
    global _WARNED_ABOUT_MISSING_SECRET
    configured = settings.downloader_webhook_secret

    if not configured:
        if not _WARNED_ABOUT_MISSING_SECRET:
            logger.error(
                "DOWNLOADER_WEBHOOK_SECRET is not set — rejecting %s webhooks. "
                "Set the env var to enable downloader callbacks.",
                downloader_name,
            )
            _WARNED_ABOUT_MISSING_SECRET = True
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret is not configured",
        )

    if not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, configured):
        logger.warning("Rejecting %s webhook: invalid or missing secret", downloader_name)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )


async def _handle_downloader_webhook(payload: dict, db, downloader_name: str) -> dict:
    """Common webhook handler for all custom downloaders.

    Expects the unified terminal payload (see module docstring). Path
    translation is done via :func:`map_download_path` for ``downloader_name``.
    """
    job_id = payload.get("id")
    job_status = payload.get("status")

    if not job_id or not job_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing id or status in payload",
        )

    if job_status not in ("done", "completed", "failed"):
        logger.debug("Ignoring %s webhook for non-terminal status: %s", downloader_name, job_status)
        return {"ignored": True, "reason": "non_terminal_status"}

    service = DownloadService(db)

    # Race condition: for fast completions (e.g. spotdl cache hits), the webhook
    # can arrive before the backend has finished creating the download record.
    # Retry a few times with a short delay.
    import asyncio
    download = None
    for attempt in range(5):
        download = await service.get_download_by_external_id(job_id)
        if download:
            break
        if attempt < 4:
            await asyncio.sleep(1)

    if not download:
        logger.warning("%s webhook for unknown job: %s", downloader_name, job_id)
        return {"ignored": True, "reason": "unknown_job"}

    if job_status in ("done", "completed"):
        old_status = download.status
        download.status = DownloadStatus.COMPLETED
        download.progress = 100.0
        await db.commit()
        record_download_transition(old_status, download.status, downloader_name)

        raw_path = payload.get("path") or payload.get("destination") or ""
        mapped_path = map_download_path(downloader_name, raw_path)
        expected_files = payload.get("files") or []

        logger.info(
            "%s webhook: job %s completed, path=%s → %s, expected files=%s",
            downloader_name, job_id, raw_path, mapped_path, expected_files,
        )

        # The webhook secret is one layer, not the sole control: never import
        # from a caller-supplied path that escapes the configured download
        # roots, even for an otherwise-valid completed job.
        if not _is_within_allowed_roots(mapped_path):
            logger.warning(
                "Rejecting %s webhook for job %s: path %r is outside allowed download roots",
                downloader_name, job_id, mapped_path,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Download path is outside allowed download roots",
            )

        from streamarr.worker import handle_completed_download

        await handle_completed_download.kiq(job_id, mapped_path, expected_files)
        return {"processed": True, "action": "import_queued", "path": mapped_path}

    elif job_status == "failed":
        error_msg = payload.get("error", "Download failed")
        # Authoritative infra-vs-release classification from the downloader
        # (it knows whether a local write/IO/disk fault or a bad release caused
        # the failure). Optional — older downloaders omit it, in which case the
        # service falls back to matching the error text.
        retriable = payload.get("retriable")
        if not isinstance(retriable, bool):
            retriable = None
        old_status = download.status
        download.status = DownloadStatus.FAILED
        download.error_reason = error_msg
        await db.commit()
        record_download_transition(old_status, download.status, downloader_name)

        logger.warning(
            "%s webhook: job %s failed (retriable=%s): %s",
            downloader_name, job_id, retriable, error_msg,
        )

        # Try alternative link for the same release before blacklisting
        alt_link = await service.try_alternative_link(download, error_msg, retriable)
        if alt_link:
            record_download_retry_event("alternative_link_selected")
            logger.info(
                "%s webhook: retrying same release with alternative link %s",
                downloader_name, alt_link.guid,
            )
            return {
                "processed": True,
                "action": "retry_alternative_link",
                "error": error_msg,
            }

        # No alternative links — blacklist the release and try the next one
        # (a retriable infra failure is never blacklisted; see blacklist_download).
        await service.blacklist_download(download, error_msg, retriable)
        media_item_guid = await service.get_media_item_guid_for_download(download)
        user_guid = str(download.user_guid) if download.user_guid else None

        if media_item_guid:
            from streamarr.worker import auto_download_media_item

            logger.info(
                "%s webhook: no alternative links, retrying media item %s with next release",
                downloader_name, media_item_guid,
            )
            await auto_download_media_item.kiq(str(media_item_guid), None, user_guid)
            record_download_retry_event("next_release_queued")

        return {
            "processed": True,
            "action": "failed_blacklisted_retry_queued",
            "error": error_msg,
            "media_item_guid": str(media_item_guid) if media_item_guid else None,
        }

    return {"ignored": True, "reason": f"unhandled_status_{job_status}"}


@router.post("/spotdl", status_code=200)
async def spotdl_webhook(
    payload: dict,
    db: DatabaseSession,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """Webhook for the Spotify downloader (spotify-downloader)."""
    _verify_webhook_secret(x_webhook_secret, "spotdl")
    return await _handle_downloader_webhook(payload, db, "spotdl")


@router.post("/torrent", status_code=200)
async def torrent_webhook(
    payload: dict,
    db: DatabaseSession,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """Webhook for the torrent downloader (torrent-downloader)."""
    _verify_webhook_secret(x_webhook_secret, "torrent")
    return await _handle_downloader_webhook(payload, db, "torrent")


@router.post("/usenet", status_code=200)
async def usenet_webhook(
    payload: dict,
    db: DatabaseSession,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """Webhook for the Usenet downloader (usenet-downloader)."""
    _verify_webhook_secret(x_webhook_secret, "usenet")
    return await _handle_downloader_webhook(payload, db, "usenet")
