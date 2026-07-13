"""Downloader clients for Streamarr."""

from streamarr.downloaders.base import DownloaderBase
from streamarr.downloaders.deluge import Deluge
from streamarr.downloaders.sabnzbd import Sabnzbd
from streamarr.downloaders.spotdl import Spotdl
from streamarr.downloaders.torrent_downloader import TorrentDownloader
from streamarr.downloaders.usenet_downloader import UsenetDownloader

__all__ = [
    "DownloaderBase",
    "Deluge",
    "Sabnzbd",
    "Spotdl",
    "TorrentDownloader",
    "UsenetDownloader",
]
