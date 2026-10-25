"""Base class for streamarr downloaders."""

from abc import ABC, abstractmethod
from typing import Any


class DownloaderBase(ABC):
    """Abstract base class for download clients."""

    @abstractmethod
    async def add_by_url(self, url: str, **kwargs) -> dict[str, Any]:
        """Add a download by URL. Returns dict with external ID."""
        pass

    @abstractmethod
    async def get_downloads(self) -> list[dict[str, Any]]:
        """Get all downloads with standardized status."""
        pass

    @abstractmethod
    async def remove(self, download_id: str | list[str]) -> Any:
        """Remove download(s)."""
        pass

    @abstractmethod
    async def pause_download(self, download_id: str) -> Any:
        """Pause a download."""
        pass

    @abstractmethod
    async def resume_job(self, download_id: str) -> Any:
        """Resume a paused download."""
        pass

    @abstractmethod
    async def pause_queue(self) -> Any:
        """Pause all downloads."""
        pass

    @abstractmethod
    async def resume_queue(self) -> Any:
        """Resume all downloads."""
        pass

    async def get_control(self) -> dict[str, Any] | None:
        """Queue control state (``paused``, ``speed_limit_kbps``).

        Optional: clients that cannot report it return ``None`` and the UI
        simply shows no toggle for that downloader.
        """
        return None

    async def set_speedlimit(self, limit_kbps: int | None) -> Any:
        """Cap the queue's download rate. ``None`` removes the cap."""
        raise NotImplementedError

    async def close(self) -> None:  # noqa: B027 - intentional no-op default
        """Clean up resources."""
        pass
