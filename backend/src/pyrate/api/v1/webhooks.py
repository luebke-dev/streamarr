"""Webhook endpoints for external service callbacks.

All custom downloaders (spotify, torrent, usenet) use the same webhook
payload format so they share a common handler.
"""

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, status

from pyrate.api.dependencies import DatabaseSession
from pyrate.config import settings
from pyrate.models.downloads import DownloadStatus
from pyrate.services.download import DownloadService
from pyrate.services.observability import (
    record_download_retry_event,
    record_download_transition,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_WARNED_ABOUT_MISSING_SECRET = False


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


async def _handle_downloader_webhook(
    payload: dict, db, downloader_name: str, path_mapper
) -> dict:
    """Common webhook handler for all custom downloaders."""
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
        mapped_path = path_mapper(raw_path)
        expected_files = payload.get("files") or []

        logger.info(
            "%s webhook: job %s completed, path=%s → %s, expected files=%s",
            downloader_name, job_id, raw_path, mapped_path, expected_files,
        )

        from pyrate.worker import handle_completed_download

        await handle_completed_download.kiq(job_id, mapped_path, expected_files)
        return {"processed": True, "action": "import_queued", "path": mapped_path}

    elif job_status == "failed":
        error_msg = payload.get("error", "Download failed")
        old_status = download.status
        download.status = DownloadStatus.FAILED
        download.error_reason = error_msg
        await db.commit()
        record_download_transition(old_status, download.status, downloader_name)

        logger.warning("%s webhook: job %s failed: %s", downloader_name, job_id, error_msg)

        # Try alternative link for the same release before blacklisting
        alt_link = await service.try_alternative_link(download, error_msg)
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
        await service.blacklist_download(download, error_msg)
        media_item_guid = await service.get_media_item_guid_for_download(download)
        user_guid = str(download.user_guid) if download.user_guid else None

        if media_item_guid:
            from pyrate.worker import auto_download_media_item

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
    """Webhook for the Spotify downloader (spotify-downloader).

    spotdl uses a different payload format:
      {"event": "job_completed"/"job_failed", "job_id": "...", "name": "...", "destination": "...", "error": "..."}
    Normalize to the common format before passing to the handler.
    """
    _verify_webhook_secret(x_webhook_secret, "spotdl")

    from pyrate.downloaders.spotdl import Spotdl

    # Normalize spotdl payload to common format
    event = payload.get("event", "")
    if event == "job_completed":
        payload["status"] = "completed"
    elif event == "job_failed":
        payload["status"] = "failed"

    if "job_id" in payload and "id" not in payload:
        payload["id"] = str(payload["job_id"])

    return await _handle_downloader_webhook(payload, db, "spotdl", Spotdl._map_path)


@router.post("/torrent", status_code=200)
async def torrent_webhook(
    payload: dict,
    db: DatabaseSession,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """Webhook for the torrent downloader (torrent-downloader)."""
    _verify_webhook_secret(x_webhook_secret, "torrent")

    from pyrate.downloaders.torrent_downloader import TorrentDownloader

    return await _handle_downloader_webhook(
        payload, db, "torrent", TorrentDownloader._map_path
    )


@router.post("/usenet", status_code=200)
async def usenet_webhook(
    payload: dict,
    db: DatabaseSession,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """Webhook for the Usenet downloader (usenet-downloader)."""
    _verify_webhook_secret(x_webhook_secret, "usenet")

    from pyrate.downloaders.usenet_downloader import UsenetDownloader

    return await _handle_downloader_webhook(
        payload, db, "usenet", UsenetDownloader._map_path
    )
