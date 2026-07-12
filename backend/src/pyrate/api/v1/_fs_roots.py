"""Filesystem confinement for the superuser file-browsing/backup endpoints.

The admin directory-browser and media-manifest copy endpoints resolve
caller-supplied paths and read/stat/copy them. They are superuser-gated, but
without an allowlist a single stolen/tricked admin request can read any file on
the host (``/etc/shadow`` …). Confine every such operation to the configured
media/download/temp roots.

``is_within_allowed`` also accepts *ancestors* of an allowed root so the picker
UI can still navigate the tree down toward a configured root (e.g. list ``/`` or
``/library`` on the way to ``/library/movies``); it never accepts sibling
branches such as ``/etc``, so file *contents* outside the media roots stay
unreadable.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status

from pyrate.services.settings import SettingsService

# (setting key, default) pairs mirroring get_environment_paths — the directories
# pyrate is actually configured to manage.
_ROOT_SETTING_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("downloads.path", "/downloads"),
    ("transcoding.temp_path", "/temp"),
    ("plugin.movies.library_path", "/library/movies"),
    ("plugin.shows.library_path", "/library/shows"),
    ("plugin.music.library_path", "/library/music"),
    ("plugin.books.library_path", "/library/books"),
    ("plugin.games.library_path", "/library/games"),
)


async def get_allowed_roots(settings_service: SettingsService) -> list[Path]:
    """Return the resolved set of directories admins may browse/operate within."""
    roots: list[Path] = []
    for key, default in _ROOT_SETTING_DEFAULTS:
        value = await settings_service.get(key, default)
        if value:
            roots.append(Path(value).expanduser().resolve())
    font = await settings_service.get("subtitles.fallback_font_path")
    if font:
        roots.append(Path(font).expanduser().resolve().parent)

    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def is_within_allowed(target: Path, roots: list[Path]) -> bool:
    """True if ``target`` is under, equal to, or an ancestor of an allowed root."""
    for root in roots:
        if (
            target == root
            or target.is_relative_to(root)
            or root.is_relative_to(target)
        ):
            return True
    return False


def is_under_allowed(target: Path, roots: list[Path]) -> bool:
    """True only if ``target`` is equal to or under an allowed root.

    Stricter than ``is_within_allowed`` (no ancestor exception) — used for file
    reads/copies where an ancestor directory must not qualify.
    """
    for root in roots:
        if target == root or target.is_relative_to(root):
            return True
    return False


def assert_within_allowed(target: Path, roots: list[Path]) -> None:
    if not is_within_allowed(target, roots):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Path is outside the configured media/storage roots",
        )
