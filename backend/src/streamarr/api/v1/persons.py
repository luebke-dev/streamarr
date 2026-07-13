"""API endpoints for persons (actors, directors, crew)."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from streamarr.api.dependencies import CurrentUser, DatabaseSession
from streamarr.models.person import Person
from streamarr.schemas.person import MediaCastWithMedia, PersonExternalLinkRead, PersonRead
from streamarr.services.person import PersonService
from streamarr.services.settings import get_tmdb_api_key

logger = logging.getLogger(__name__)

router = APIRouter()

# Re-import threshold: skip if metadata was imported less than 7 days ago
REIMPORT_THRESHOLD = timedelta(days=7)


def _person_external_links(person: Person) -> list[PersonExternalLinkRead]:
    links: list[PersonExternalLinkRead] = []
    if person.tmdb_id:
        provider_id = str(person.tmdb_id)
        links.append(
            PersonExternalLinkRead(
                provider="tmdb",
                provider_id=provider_id,
                display_name="TMDB",
                url=f"https://www.themoviedb.org/person/{quote(provider_id, safe='')}",
            )
        )
    if person.homepage:
        links.append(
            PersonExternalLinkRead(
                provider="homepage",
                provider_id=None,
                display_name="Homepage",
                url=person.homepage,
            )
        )
    return links


def _person_to_read(person: Person) -> PersonRead:
    data = PersonRead.model_validate(person)
    data.external_links = _person_external_links(person)
    return data


async def _trigger_filmography_import(person_guid: uuid.UUID) -> None:
    """Background task to import a person's filmography."""
    from streamarr.database import sessionmanager

    try:
        async with sessionmanager.session() as db:
            service = PersonService(db)
            person = await service.get_by_id(person_guid)
            if not person or not person.tmdb_id:
                return

            tmdb_api_key = await get_tmdb_api_key(db)
            if not tmdb_api_key:
                logger.warning("Cannot import filmography: TMDB API key not configured")
                return

            stats = await service.import_person_filmography(person, tmdb_api_key)
            logger.info(
                "Background filmography import for %s: %s", person.name, stats
            )

            # Publish WebSocket event for live UI updates
            try:
                from streamarr.services.redis_event import get_redis_event_service

                redis_service = get_redis_event_service()
                await redis_service.publish(
                    channel=f"person:{person_guid}",
                    event="person_credits_updated",
                    data={"person_guid": str(person_guid), "stats": stats},
                )
            except Exception as e:
                logger.debug("Failed to publish person_credits_updated event: %s", e)
    except Exception:
        logger.exception("Background filmography import failed for person %s", person_guid)


@router.get("", response_model=list[PersonRead])
async def search_persons(
    db: DatabaseSession,
    current_user: CurrentUser,
    q: str = Query("", description="Search query for person name"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
):
    """Search for persons by name."""
    service = PersonService(db)

    if q:
        persons = await service.search(q, limit=limit)
    else:
        persons = []

    return [_person_to_read(p) for p in persons]


@router.get("/{person_guid}", response_model=PersonRead)
async def get_person(
    db: DatabaseSession,
    current_user: CurrentUser,
    person_guid: uuid.UUID,
    background_tasks: BackgroundTasks,
):
    """Get a specific person by GUID. Auto-triggers filmography import if not yet imported."""
    service = PersonService(db)
    person = await service.get_by_id(person_guid)

    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    # Auto-trigger filmography import if not yet done or stale
    if person.tmdb_id and (
        not person.metadata_imported
        or (
            person.metadata_imported_at
            and datetime.now(UTC)
            - (person.metadata_imported_at.replace(tzinfo=UTC)
               if person.metadata_imported_at.tzinfo is None
               else person.metadata_imported_at)
            > REIMPORT_THRESHOLD
        )
    ):
        background_tasks.add_task(_trigger_filmography_import, person.guid)

    return _person_to_read(person)


@router.get("/{person_guid}/credits", response_model=list[MediaCastWithMedia])
async def get_person_credits(
    db: DatabaseSession,
    current_user: CurrentUser,
    person_guid: uuid.UUID,
):
    """Get all media credits for a person, including media item details."""
    service = PersonService(db)
    person = await service.get_by_id(person_guid)

    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    return await service.get_person_credits(person_guid)


@router.post("/{person_guid}/import-filmography")
async def import_person_filmography(
    db: DatabaseSession,
    current_user: CurrentUser,
    person_guid: uuid.UUID,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Force re-import even if recently imported"),
):
    """Trigger a filmography import for a person. Imports all their movies/shows."""
    service = PersonService(db)
    person = await service.get_by_id(person_guid)

    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    if not person.tmdb_id:
        raise HTTPException(status_code=400, detail="Person has no TMDB ID")

    # Check if recently imported (unless force=True)
    if not force and person.metadata_imported and person.metadata_imported_at:
        if datetime.now(UTC) - person.metadata_imported_at < REIMPORT_THRESHOLD:
            return {
                "status": "already_imported",
                "message": f"Filmography was imported {person.metadata_imported_at.isoformat()}. Use force=true to re-import.",
            }

    background_tasks.add_task(_trigger_filmography_import, person.guid)

    return {
        "status": "queued",
        "message": f"Filmography import for {person.name} has been queued.",
    }
