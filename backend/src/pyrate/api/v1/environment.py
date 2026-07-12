"""Admin environment and filesystem inspection endpoints."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from pyrate.api.dependencies import CurrentSuperuser, DatabaseSession
from pyrate.api.v1._fs_roots import assert_within_allowed, get_allowed_roots
from pyrate.config import settings
from pyrate.services.settings import SettingsService

router = APIRouter()


class EnvironmentPathInfo(BaseModel):
    key: str
    path: str
    exists: bool
    is_dir: bool
    is_file: bool
    readable: bool
    writable: bool


class DirectoryEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    is_file: bool
    size_bytes: int | None = None


class DirectoryListing(BaseModel):
    path: str
    entries: list[DirectoryEntry]


class FileSystemEntryInfo(BaseModel):
    name: str
    path: str
    type: str


class PathValidationRequest(BaseModel):
    path: str
    is_file: bool | None = None
    validate_writable: bool = False


class DefaultDirectoryInfo(BaseModel):
    path: str = "/"


def _path_info(key: str, path_value: str | None) -> EnvironmentPathInfo:
    path = Path(path_value or "").expanduser()
    exists = path.exists()
    return EnvironmentPathInfo(
        key=key,
        path=str(path),
        exists=exists,
        is_dir=path.is_dir() if exists else False,
        is_file=path.is_file() if exists else False,
        readable=os.access(path, os.R_OK) if exists else False,
        writable=os.access(path, os.W_OK) if exists else False,
    )


def _entry_info(path: Path) -> FileSystemEntryInfo:
    return FileSystemEntryInfo(
        name=path.name or str(path),
        path=str(path),
        type="Directory" if path.is_dir() else "File",
    )


@router.get("/paths", response_model=list[EnvironmentPathInfo])
async def get_environment_paths(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    """Return configured runtime/storage paths without exposing secrets."""
    settings_service = SettingsService(db)
    configured = {
        "cwd": str(Path.cwd()),
        "app_url": settings.app_url or "",
        "downloads": await settings_service.get("downloads.path", "/downloads"),
        "transcoding_temp": await settings_service.get("transcoding.temp_path", "/temp"),
        "movies_library": await settings_service.get(
            "plugin.movies.library_path", "/library/movies"
        ),
        "shows_library": await settings_service.get(
            "plugin.shows.library_path", "/library/shows"
        ),
        "music_library": await settings_service.get(
            "plugin.music.library_path", "/library/music"
        ),
        "books_library": await settings_service.get(
            "plugin.books.library_path", "/library/books"
        ),
        "games_library": await settings_service.get(
            "plugin.games.library_path", "/library/games"
        ),
        "subtitle_fallback_font": await settings_service.get(
            "subtitles.fallback_font_path"
        ),
    }
    return [
        _path_info(key, value)
        for key, value in configured.items()
        if value
    ]


@router.get("/directory", response_model=DirectoryListing)
async def list_environment_directory(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    path: str = Query(..., min_length=1),
    include_hidden: bool = Query(False),
):
    """List entries in a server directory (admin only)."""
    target = Path(path).expanduser().resolve()
    assert_within_allowed(target, await get_allowed_roots(SettingsService(db)))
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    entries: list[DirectoryEntry] = []
    try:
        children = sorted(target.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.lower()))
    except OSError as exc:
        raise HTTPException(status_code=403, detail=f"Directory is not readable: {exc}") from exc

    for child in children:
        if not include_hidden and child.name.startswith("."):
            continue
        try:
            stat = child.stat()
        except OSError:
            stat = None
        entries.append(
            DirectoryEntry(
                name=child.name,
                path=str(child),
                is_dir=child.is_dir(),
                is_file=child.is_file(),
                size_bytes=stat.st_size if stat and child.is_file() else None,
            )
        )

    return DirectoryListing(path=str(target), entries=entries)


@router.get("/directory-contents", response_model=list[FileSystemEntryInfo])
async def get_directory_contents(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    path: str = Query(..., min_length=1),
    include_files: bool = Query(False),
    include_directories: bool = Query(False),
):
    """Return directory contents with explicit file/directory filtering."""
    target = Path(path).expanduser().resolve()
    assert_within_allowed(target, await get_allowed_roots(SettingsService(db)))
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    try:
        children = sorted(target.iterdir(), key=lambda entry: str(entry).lower())
    except OSError as exc:
        raise HTTPException(status_code=403, detail=f"Directory is not readable: {exc}") from exc

    return [
        _entry_info(child)
        for child in children
        if (child.is_dir() and include_directories) or (child.is_file() and include_files)
    ]


@router.post("/validate-path", status_code=status.HTTP_204_NO_CONTENT)
async def validate_path(
    request: PathValidationRequest,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    """Validate that a file or directory exists and optionally is writable."""
    target = Path(request.path).expanduser().resolve()
    assert_within_allowed(target, await get_allowed_roots(SettingsService(db)))
    if request.is_file is True and not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if request.is_file is False and not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    if request.is_file is None and not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    if request.validate_writable:
        directory = target if target.is_dir() else target.parent
        probe = directory / f".pyrate-write-test-{id(request)}"
        try:
            probe.write_text("", encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=403, detail=f"Path is not writable: {exc}") from exc
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/drives", response_model=list[FileSystemEntryInfo])
async def get_drives(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    """Return the configured media/storage roots the server may browse."""
    roots = await get_allowed_roots(SettingsService(db))
    return [_entry_info(root) for root in roots if root.exists()]


@router.get("/parent-path", response_model=str | None)
async def get_parent_path(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    path: str = Query(..., min_length=1),
):
    """Return the parent path for a supplied path (confined to media roots)."""
    allowed_roots = await get_allowed_roots(SettingsService(db))
    resolved = Path(path).expanduser().resolve()
    assert_within_allowed(resolved, allowed_roots)
    parent = Path(path).expanduser().parent
    if str(parent) == str(Path(path).expanduser()):
        return None
    # Never hand back a parent outside the allowed roots (e.g. climbing above
    # the shallowest configured root).
    assert_within_allowed(parent.resolve(), allowed_roots)
    return str(parent)


@router.get("/default-directory", response_model=DefaultDirectoryInfo)
async def get_default_directory_browser(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    roots = await get_allowed_roots(SettingsService(db))
    if roots:
        return DefaultDirectoryInfo(path=str(roots[0]))
    return DefaultDirectoryInfo()
