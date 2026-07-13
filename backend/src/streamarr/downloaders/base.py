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

    async def close(self) -> None:
        """Clean up resources."""
        pass
