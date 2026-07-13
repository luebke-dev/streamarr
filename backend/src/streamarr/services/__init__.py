"""Services package — lazy re-exports of the commonly-used service classes.

Names are resolved on first access (PEP 562 ``__getattr__``) instead of being
eagerly imported at package-import time. The previous eager imports pulled the
*entire* service layer in whenever any ``streamarr.services`` submodule was
imported — that fan-out is the root cause of the circular-import web the
codebase worked around with hundreds of function-body imports (importing a leaf
like ``streamarr.services.game_platforms`` would drag in ``download``, ``media``,
… and cycle). Lazy resolution keeps ``from streamarr.services import XService``
working without forcing that fan-out, so submodules can be imported in
isolation and inline-import workarounds can be unwound incrementally.
"""

import importlib
from typing import Any

# Exported name -> module that defines it.
_EXPORTS: dict[str, str] = {
    "AuthService": "streamarr.services.auth",
    "DownloadService": "streamarr.services.download",
    "DownloaderService": "streamarr.services.downloader",
    "IndexerService": "streamarr.services.indexer",
    "ListService": "streamarr.services.list",
    "MediaService": "streamarr.services.media",
    "MediaFileService": "streamarr.services.media_file",
    "NotificationService": "streamarr.services.notification",
    "PersonService": "streamarr.services.person",
    "SettingsService": "streamarr.services.settings",
    "SpotifyMusicImportService": "streamarr.services.spotify_import",
    "StorageCleanupService": "streamarr.services.storage_cleanup",
    "TrendingService": "streamarr.services.trending",
    # Standalone helper functions (all from settings).
    "get_igdb_credentials": "streamarr.services.settings",
    "get_locale": "streamarr.services.settings",
    "get_setting": "streamarr.services.settings",
    "get_tmdb_api_key": "streamarr.services.settings",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
