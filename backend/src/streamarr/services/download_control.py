"""Queue-level control for the configured downloaders.

The per-download actions (pause/resume one item) live in ``DownloadService``.
This module is the operator-facing counterpart: pause *everything*, resume
everything, cap the rate, and report what the queues are doing right now — the
data behind the downloads page.

Pausing works on the downloader, not by rewriting ``download.status``: the
status column is refreshed from the client anyway, and inventing a "paused"
state would fight the partial unique index that keeps one active row per
release link.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.downloader import Downloader
from streamarr.models.downloads import Download
from streamarr.services.downloader import DownloaderService

logger = logging.getLogger(__name__)

# Row statuses that still have work ahead of them.
_ACTIVE_STATUSES = ("queued", "pending", "Downloading", "downloading", "paused")


class DownloadControlService:
    """Aggregate queue control across every configured downloader."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _clients(self) -> list[tuple[Downloader, Any]]:
        rows = (await self.db.execute(select(Downloader))).scalars().all()
        clients: list[tuple[Downloader, Any]] = []
        for downloader in rows:
            try:
                clients.append(
                    (downloader, DownloaderService.get_client(downloader))
                )
            except Exception as exc:  # noqa: BLE001 - one broken client must not hide the rest
                logger.warning(
                    "Queue control: cannot build client for %s: %s",
                    downloader.label,
                    exc,
                )
        return clients

    async def _status_counts(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(Download.status, func.count())
                .where(Download.status.in_(_ACTIVE_STATUSES))
                .group_by(Download.status)
            )
        ).all()
        counts = {str(status): n for status, n in rows}
        downloading = counts.get("Downloading", 0) + counts.get("downloading", 0)
        paused = counts.get("paused", 0)
        queued = counts.get("queued", 0) + counts.get("pending", 0) + paused
        return {"queued": queued, "downloading": downloading, "paused": paused}

    async def overview(self) -> dict[str, Any]:
        """Queue state plus live job figures, ready for the UI."""
        counts = await self._status_counts()
        downloaders: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        speed_total = 0

        for downloader, client in await self._clients():
            entry: dict[str, Any] = {
                "label": downloader.label,
                "type": downloader.type,
                "paused": None,
                "speed_limit_kbps": None,
                "reachable": False,
                "error": None,
            }
            try:
                control = await client.get_control()
                entry["reachable"] = True
                if control:
                    entry["paused"] = control.get("paused")
                    entry["speed_limit_kbps"] = control.get("speed_limit_kbps")
            except Exception as exc:  # noqa: BLE001 - report, don't fail the page
                entry["error"] = str(exc)[:200]
                logger.debug(
                    "Queue control: %s unreachable: %s", downloader.label, exc
                )

            try:
                for job in await client.get_downloads():
                    status = str(job.get("status") or "").lower()
                    speed = int(job.get("speed_bps") or 0)
                    if status == "downloading":
                        speed_total += speed
                    jobs.append(
                        {
                            "id": str(job.get("id") or job.get("guid") or ""),
                            "name": job.get("name") or job.get("title") or "",
                            "status": status,
                            "progress": float(job.get("progress") or 0),
                            "speed_bps": speed,
                            "downloaded_bytes": int(
                                job.get("downloaded_bytes") or 0
                            ),
                            "total_bytes": int(job.get("total_bytes") or 0),
                            "downloader": downloader.label,
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                entry["error"] = str(exc)[:200]
                logger.debug(
                    "Queue control: list failed for %s: %s", downloader.label, exc
                )

            downloaders.append(entry)
            await _close(client)

        controllable = [d for d in downloaders if d["paused"] is not None]
        active = [j for j in jobs if j["status"] in ("downloading", "queued", "paused")]
        active.sort(key=lambda j: (j["status"] != "downloading", -j["speed_bps"]))
        return {
            "counts": counts,
            "speed_bps": speed_total,
            "paused": all(d["paused"] for d in controllable) if controllable else None,
            "downloaders": downloaders,
            "jobs": active,
        }

    async def pause_all(self) -> dict[str, Any]:
        return await self._apply("pause")

    async def resume_all(self) -> dict[str, Any]:
        return await self._apply("resume")

    async def _apply(self, action: str) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for downloader, client in await self._clients():
            entry: dict[str, Any] = {"label": downloader.label, "ok": False}
            try:
                if action == "pause":
                    await client.pause_queue()
                else:
                    await client.resume_queue()
                entry["ok"] = True
            except Exception as exc:  # noqa: BLE001
                entry["error"] = str(exc)[:200]
                logger.warning(
                    "Queue %s failed for %s: %s", action, downloader.label, exc
                )
            results.append(entry)
            await _close(client)
        return {"action": action, "downloaders": results}

    async def set_speed_limit(self, kbps: int | None) -> dict[str, Any]:
        limit = None if not kbps or kbps <= 0 else int(kbps)
        results: list[dict[str, Any]] = []
        for downloader, client in await self._clients():
            entry: dict[str, Any] = {"label": downloader.label, "ok": False}
            try:
                if limit is None:
                    await client.set_speedlimit(None)
                else:
                    await client.set_speedlimit(limit)
                entry["ok"] = True
            except NotImplementedError:
                entry["error"] = "downloader does not support a rate cap"
            except Exception as exc:  # noqa: BLE001
                entry["error"] = str(exc)[:200]
                logger.warning("Speed limit failed for %s: %s", downloader.label, exc)
            results.append(entry)
            await _close(client)
        return {"speed_limit_kbps": limit, "downloaders": results}


async def _close(client: Any) -> None:
    try:
        await client.close()
    except Exception:  # noqa: BLE001 - best effort
        pass
