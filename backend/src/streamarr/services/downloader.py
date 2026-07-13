"""
Downloader Service

This service handles all downloader-related operations (SABnzbd, Deluge, etc.)
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.downloaders.deluge import Deluge
from streamarr.downloaders.sabnzbd import Sabnzbd
from streamarr.downloaders.spotdl import Spotdl
from streamarr.downloaders.torrent_downloader import TorrentDownloader
from streamarr.downloaders.usenet_downloader import UsenetDownloader
from streamarr.models.downloader import Downloader
from streamarr.schemas.downloader import DownloaderCreate, DownloaderRead, DownloaderUpdate
from streamarr.utils.http import call_with_resilience, host_key

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DownloaderService:
    """Service for managing download clients"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _to_read(db_downloader: Downloader) -> DownloaderRead:
        return DownloaderRead(
            guid=db_downloader.guid,
            created_at=db_downloader.created_at,
            updated_at=db_downloader.updated_at,
            host=db_downloader.host,
            ssl=db_downloader.ssl,
            verify_ssl=db_downloader.verify_ssl,
            type=db_downloader.type,
            label=db_downloader.label,
            api_key_configured=bool(db_downloader.api_key),
        )

    async def get_all(self) -> list[DownloaderRead]:
        """Get all configured downloaders (with api_key redacted)."""
        result = await self.db.execute(select(Downloader))
        rows = result.scalars().all()
        logger.debug("Retrieved %d downloaders", len(rows))
        return [self._to_read(d) for d in rows]

    async def get_model_by_id(self, downloader_id: str | uuid.UUID) -> Downloader | None:
        """Return the raw SA row including api_key for internal use."""
        if isinstance(downloader_id, str):
            downloader_id = uuid.UUID(downloader_id)
        result = await self.db.execute(
            select(Downloader).where(Downloader.guid == downloader_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, downloader_id: str | uuid.UUID) -> DownloaderRead | None:
        """Get a downloader by its GUID (redacted)."""
        db_downloader = await self.get_model_by_id(downloader_id)
        return self._to_read(db_downloader) if db_downloader else None

    async def create(self, downloader: DownloaderCreate) -> DownloaderRead:
        """Create a new downloader"""
        db_downloader = Downloader(**downloader.model_dump())
        self.db.add(db_downloader)
        await self.db.commit()
        await self.db.refresh(db_downloader)
        logger.info("Created downloader: guid=%s type=%s", db_downloader.guid, db_downloader.type)
        return self._to_read(db_downloader)

    async def update(
        self, db_downloader: Downloader, downloader_in: DownloaderUpdate
    ) -> DownloaderRead:
        """Update an existing downloader. Empty ``api_key`` keeps the existing secret."""
        downloader_data = downloader_in.model_dump(
            exclude={"api_key"}, exclude_unset=True
        )
        for key, value in downloader_data.items():
            setattr(db_downloader, key, value)
        if downloader_in.api_key:
            db_downloader.api_key = downloader_in.api_key
        self.db.add(db_downloader)
        await self.db.commit()
        await self.db.refresh(db_downloader)
        logger.info("Updated downloader: guid=%s fields=%s", db_downloader.guid, list(downloader_data.keys()))
        return self._to_read(db_downloader)

    @staticmethod
    def get_client(downloader: Downloader) -> Sabnzbd | Deluge | Spotdl | TorrentDownloader:
        """
        Factory method to create the appropriate downloader client.

        Args:
            downloader: Downloader model instance

        Returns:
            Instance of the appropriate downloader client (Sabnzbd, Deluge, or Spotdl)

        Raises:
            ValueError: If downloader type is not supported
        """
        downloader_type = downloader.type.lower()
        logger.debug("Creating client for downloader guid=%s type=%s", downloader.guid, downloader_type)

        if downloader_type == "deluge":
            return Deluge(
                base_url=downloader.host,
                api_key=downloader.api_key,
                verify_ssl=downloader.verify_ssl,
            )
        elif downloader_type == "sabnzbd":
            return Sabnzbd(
                base_url=downloader.host,
                api_key=downloader.api_key,
                verify_ssl=downloader.verify_ssl,
            )
        elif downloader_type == "spotdl":
            return Spotdl(
                base_url=downloader.host,
                verify_ssl=downloader.verify_ssl,
            )
        elif downloader_type == "torrent_downloader":
            return TorrentDownloader(
                base_url=downloader.host,
                verify_ssl=downloader.verify_ssl,
            )
        elif downloader_type == "usenet_downloader":
            return UsenetDownloader(
                base_url=downloader.host,
                verify_ssl=downloader.verify_ssl,
            )
        else:
            # For backward compatibility, default to SABnzbd but log a warning
            logger.warning(
                f"Unknown downloader type '{downloader.type}' for downloader {downloader.guid}. "
                f"Supported types are 'sabnzbd', 'deluge', 'spotdl', and 'torrent_downloader'. Defaulting to SABnzbd for backward compatibility."
            )
            return Sabnzbd(
                base_url=downloader.host,
                api_key=downloader.api_key,
                verify_ssl=downloader.verify_ssl,
            )

    @staticmethod
    def _breaker_key(downloader: Downloader) -> str:
        """Per-host circuit-breaker key for a downloader's client host."""
        return f"downloader:{host_key(downloader.host)}"

    async def client_request(
        self,
        downloader: Downloader,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        """Run a downloader-client call through the shared resilience wrapper.

        ``operation`` is a zero-arg callable returning an awaitable, e.g.
        ``lambda: client.get_downloads()``. Transient transport failures are
        retried with exponential backoff, and a repeatedly-unreachable
        downloader trips a per-host circuit breaker so we fail fast (with
        :class:`~streamarr.utils.http.CircuitOpenError`) instead of hammering a
        host that is down. Successful calls behave exactly as before.
        """
        return await call_with_resilience(
            operation, breaker_key=self._breaker_key(downloader)
        )

    async def health_check(self, downloader: Downloader) -> bool:
        """Best-effort reachability probe for a downloader.

        Issues a lightweight status request through :meth:`client_request`, so
        a downloader that is briefly unreachable is retried before being
        reported unhealthy. Returns ``True`` if the downloader answered,
        ``False`` otherwise.
        """
        client = self.get_client(downloader)
        try:
            await self.client_request(downloader, client.get_downloads)
            return True
        except Exception:
            logger.info(
                "Downloader health check failed guid=%s host=%s",
                downloader.guid,
                downloader.host,
                exc_info=True,
            )
            return False
        finally:
            try:
                await client.close()
            except Exception:
                logger.debug(
                    "Failed to close downloader client guid=%s", downloader.guid,
                    exc_info=True,
                )

    async def delete(self, downloader: Downloader) -> None:
        """Delete a downloader"""
        logger.info("Deleting downloader: guid=%s type=%s", downloader.guid, downloader.type)
        await self.db.delete(downloader)
        await self.db.commit()
