"""Services package - exports all service classes for convenient imports."""

from pyrate.services.auth import AuthService

from pyrate.services.download import DownloadService
from pyrate.services.downloader import DownloaderService
from pyrate.services.indexer import IndexerService
from pyrate.services.list import ListService
from pyrate.services.media import MediaService
from pyrate.services.media_file import MediaFileService
from pyrate.services.notification import NotificationService
from pyrate.services.person import PersonService
from pyrate.services.settings import (
    SettingsService,
    get_igdb_credentials,
    get_locale,
    get_setting,
    get_tmdb_api_key,
)
from pyrate.services.spotify_import import SpotifyMusicImportService
from pyrate.services.storage_cleanup import StorageCleanupService
from pyrate.services.trending import TrendingService

__all__ = [
    "AuthService",
    "DownloadService",
    "DownloaderService",
    "IndexerService",
    "ListService",
    "NotificationService",
    "PersonService",
    "SettingsService",
    "SpotifyMusicImportService",
    "StorageCleanupService",
    "TrendingService",
    "MediaFileService",
    "MediaService",
    # Standalone helper functions
    "get_igdb_credentials",
    "get_locale",
    "get_setting",
    "get_tmdb_api_key",
]
