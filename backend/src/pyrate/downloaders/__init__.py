"""Downloader clients for pyrate.media."""

from pyrate.downloaders.base import DownloaderBase
from pyrate.downloaders.deluge import Deluge
from pyrate.downloaders.sabnzbd import Sabnzbd
from pyrate.downloaders.spotdl import Spotdl
from pyrate.downloaders.torrent_downloader import TorrentDownloader
from pyrate.downloaders.usenet_downloader import UsenetDownloader

__all__ = [
    "DownloaderBase",
    "Deluge",
    "Sabnzbd",
    "Spotdl",
    "TorrentDownloader",
    "UsenetDownloader",
]
