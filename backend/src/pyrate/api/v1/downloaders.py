import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import select

from pyrate.api.dependencies import CurrentSuperuser, DatabaseSession
from pyrate.models.downloader import Downloader
from pyrate.schemas.downloader import DownloaderCreate, DownloaderRead, DownloaderUpdate
from pyrate.services.downloader import DownloaderService
from pyrate.api.utils import get_user_locale

router = APIRouter()

class DownloaderTypeInfo(BaseModel):
    """Information about an available downloader plugin type."""

    domain: str
    name: str
    description: str
    config_schema: dict


KNOWN_DOWNLOADER_TYPES = [
    DownloaderTypeInfo(
        domain="sabnzbd",
        name="SABnzbd",
        description="SABnzbd Usenet downloader",
        config_schema={},
    ),
    DownloaderTypeInfo(
        domain="deluge",
        name="Deluge",
        description="Deluge BitTorrent client",
        config_schema={},
    ),
    DownloaderTypeInfo(
        domain="spotdl",
        name="SpotDL",
        description="Spotify music downloader",
        config_schema={},
    ),
]


@router.get("/types", response_model=list[DownloaderTypeInfo])
async def list_downloader_types(
    request: Request,
    current_user: CurrentSuperuser,
):
    """
    List available downloader types.

    Returns:
        List of available downloader types with their configuration schemas
    """
    return KNOWN_DOWNLOADER_TYPES


@router.get("", response_model=list[DownloaderRead])
async def list_downloaders(db: DatabaseSession, current_user: CurrentSuperuser):
    return await DownloaderService(db).get_all()


@router.get("/{downloader_id}", response_model=DownloaderRead)
async def get_downloader(
    downloader_id: uuid.UUID, db: DatabaseSession, current_user: CurrentSuperuser
):
    result = await DownloaderService(db).get_by_id(downloader_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Downloader not found")
    return result


@router.put("/{downloader_id}", response_model=DownloaderRead)
async def update_downloader(
    downloader_id: uuid.UUID,
    downloader_in: DownloaderUpdate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    service = DownloaderService(db)
    db_downloader = await service.get_model_by_id(downloader_id)
    if db_downloader is None:
        raise HTTPException(status_code=404, detail="Downloader not found")
    return await service.update(db_downloader, downloader_in)


@router.post("", response_model=DownloaderRead)
async def create_downloader(
    downloader_in: DownloaderCreate, db: DatabaseSession, current_user: CurrentSuperuser
):
    return await DownloaderService(db).create(downloader_in)


@router.delete("/{downloader_id}", status_code=204)
async def delete_downloader(
    downloader_id: uuid.UUID, db: DatabaseSession, current_user: CurrentSuperuser
):
    service = DownloaderService(db)
    db_downloader = await service.get_model_by_id(downloader_id)
    if db_downloader is None:
        raise HTTPException(status_code=404, detail="Downloader not found")
    await service.delete(db_downloader)
