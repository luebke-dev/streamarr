"""Person service for managing actors, directors, and crew members."""

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.person import MediaCast, Person
from pyrate.schemas.person import MediaCastWithMedia, MediaItemBrief

logger = logging.getLogger(__name__)


class PersonService:
    """Service for person and cast management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== Person CRUD ====================

    async def get_by_id(self, guid: uuid.UUID) -> Person | None:
        """Get a person by GUID."""
        result = await self.db.execute(select(Person).where(Person.guid == guid))
        return result.scalars().first()

    async def get_by_tmdb_id(self, tmdb_id: int) -> Person | None:
        """Get a person by TMDB ID."""
        result = await self.db.execute(select(Person).where(Person.tmdb_id == tmdb_id))
        return result.scalars().first()

    async def get_or_create(
        self,
        tmdb_id: int,
        name: str,
        profile_path: str | None = None,
        known_for_department: str | None = None,
    ) -> Person:
        """Get an existing person by TMDB ID or create a new one.

        Handles concurrent inserts gracefully (race condition between workers).
        """
        person = await self.get_by_tmdb_id(tmdb_id)
        if person:
            # Update profile_path if it changed
            if profile_path and person.profile_path != profile_path:
                person.profile_path = profile_path
                await self.db.flush()
            return person

        person = Person(
            guid=uuid.uuid4(),
            tmdb_id=tmdb_id,
            name=name,
            profile_path=profile_path,
            known_for_department=known_for_department,
        )
        try:
            self.db.add(person)
            await self.db.flush()
        except IntegrityError:
            # Another worker inserted the same person concurrently
            await self.db.rollback()
            person = await self.get_by_tmdb_id(tmdb_id)
            if not person:
                raise
            logger.debug("Person tmdb_id=%s created by concurrent worker, reusing", tmdb_id)
        return person

    async def search(self, query: str, limit: int = 20) -> list[Person]:
        """Search for persons by name."""
        result = await self.db.execute(
            select(Person)
            .where(Person.name.ilike(f"%{query}%"))
            .order_by(Person.name)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_person_details(
        self,
        person: Person,
        details: dict[str, Any],
    ) -> Person:
        """Update person with detailed metadata from TMDB."""
        if details.get("biography"):
            person.biography = details["biography"]
        if details.get("profile_path"):
            person.profile_path = details["profile_path"]
        if details.get("known_for_department"):
            person.known_for_department = details["known_for_department"]
        if details.get("place_of_birth"):
            person.place_of_birth = details["place_of_birth"]
        if details.get("homepage"):
            person.homepage = details["homepage"]

        # Parse dates
        for field in ("birthday", "deathday"):
            date_str = details.get(field)
            if date_str:
                try:
                    setattr(person, field, date.fromisoformat(date_str))
                except (ValueError, TypeError):
                    logger.debug("Skipping invalid date string %r for person field %s", date_str, field)

        person.metadata_imported = True
        person.metadata_imported_at = datetime.now(UTC)
        await self.db.flush()
        return person

    # ==================== Cast Management ====================

    async def add_cast(
        self,
        media_item_guid: uuid.UUID,
        person_guid: uuid.UUID,
        character: str | None = None,
        department: str | None = None,
        job: str | None = None,
        cast_order: int | None = None,
    ) -> MediaCast:
        """Add a cast entry linking a person to a media item."""
        cast_entry = MediaCast(
            guid=uuid.uuid4(),
            media_item_guid=media_item_guid,
            person_guid=person_guid,
            character=character,
            department=department,
            job=job,
            cast_order=cast_order,
        )
        self.db.add(cast_entry)
        await self.db.flush()
        return cast_entry

    async def get_cast_for_media(
        self, media_item_guid: uuid.UUID, limit: int = 50
    ) -> list[MediaCast]:
        """Get all cast entries for a media item, ordered by cast_order."""
        result = await self.db.execute(
            select(MediaCast)
            .options(selectinload(MediaCast.person))
            .where(MediaCast.media_item_guid == media_item_guid)
            .order_by(MediaCast.cast_order.asc().nullslast())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_media_for_person(self, person_guid: uuid.UUID) -> list[MediaCast]:
        """Get all media items a person has been cast in, with media_item eager-loaded."""
        result = await self.db.execute(
            select(MediaCast)
            .options(selectinload(MediaCast.media_item))
            .where(MediaCast.person_guid == person_guid)
            .order_by(MediaCast.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_person_credits(
        self, person_guid: uuid.UUID
    ) -> list[MediaCastWithMedia]:
        """Get all media credits for a person, mapped to response schemas."""
        cast_entries = await self.get_media_for_person(person_guid)

        results = []
        for c in cast_entries:
            media_item_brief = None
            if c.media_item:
                media_type_value = (
                    c.media_item.media_type.value
                    if hasattr(c.media_item.media_type, "value")
                    else str(c.media_item.media_type)
                )
                media_item_brief = MediaItemBrief(
                    guid=c.media_item.guid,
                    title=c.media_item.title,
                    media_type=media_type_value,
                    poster_path=c.media_item.poster_path,
                    backdrop_path=c.media_item.backdrop_path,
                    release_date=c.media_item.release_date,
                )

            results.append(
                MediaCastWithMedia(
                    guid=c.guid,
                    media_item_guid=c.media_item_guid,
                    person_guid=c.person_guid,
                    character=c.character,
                    department=c.department,
                    job=c.job,
                    cast_order=c.cast_order,
                    created_at=c.created_at,
                    media_item=media_item_brief,
                )
            )

        return results

    async def import_cast_from_tmdb(
        self,
        media_item_guid: uuid.UUID,
        credits_data: dict[str, Any],
        max_cast: int = 25,
        max_crew: int = 10,
    ) -> list[MediaCast]:
        """
        Import cast and crew from TMDB credits data.

        Args:
            media_item_guid: The media item to add cast to
            credits_data: TMDB credits response (with 'cast' and 'crew' keys)
            max_cast: Maximum number of cast members to import
            max_crew: Maximum number of crew members to import (directors, writers)

        Returns:
            List of created MediaCast entries
        """
        cast_entries = []

        # Import cast (actors)
        cast_list = credits_data.get("cast", [])
        for i, cast_member in enumerate(cast_list[:max_cast]):
            tmdb_person_id = cast_member.get("id")
            if not tmdb_person_id:
                continue

            person = await self.get_or_create(
                tmdb_id=tmdb_person_id,
                name=cast_member.get("name", "Unknown"),
                profile_path=cast_member.get("profile_path"),
                known_for_department=cast_member.get("known_for_department"),
            )

            # For TV shows with aggregate_credits, character might be in 'roles'
            character = cast_member.get("character")
            if not character and cast_member.get("roles"):
                roles = cast_member["roles"]
                if roles:
                    character = roles[0].get("character")

            cast_entry = await self.add_cast(
                media_item_guid=media_item_guid,
                person_guid=person.guid,
                character=character,
                department="Acting",
                job="Actor",
                cast_order=cast_member.get("order", i),
            )
            cast_entries.append(cast_entry)

        # Import key crew (directors, writers, producers)
        important_jobs = {
            "Director",
            "Writer",
            "Screenplay",
            "Producer",
            "Executive Producer",
        }
        crew_list = credits_data.get("crew", [])
        crew_added = 0

        for crew_member in crew_list:
            if crew_added >= max_crew:
                break

            job = crew_member.get("job")

            # For TV aggregate_credits, job might be in 'jobs' array
            if not job and crew_member.get("jobs"):
                jobs = crew_member["jobs"]
                if jobs:
                    job = jobs[0].get("job")

            if job not in important_jobs:
                continue

            tmdb_person_id = crew_member.get("id")
            if not tmdb_person_id:
                continue

            person = await self.get_or_create(
                tmdb_id=tmdb_person_id,
                name=crew_member.get("name", "Unknown"),
                profile_path=crew_member.get("profile_path"),
                known_for_department=crew_member.get("known_for_department"),
            )

            cast_entry = await self.add_cast(
                media_item_guid=media_item_guid,
                person_guid=person.guid,
                department=crew_member.get("department"),
                job=job,
                cast_order=1000 + crew_added,  # Crew after cast
            )
            cast_entries.append(cast_entry)
            crew_added += 1

        logger.info(
            f"Imported {len(cast_entries)} cast/crew entries for media item {media_item_guid}"
        )
        return cast_entries

    # ==================== Filmography Import ====================

    async def import_person_filmography(
        self,
        person: Person,
        tmdb_api_key: str,
        max_credits: int = 50,
    ) -> dict[str, int]:
        """
        Import a person's full filmography from TMDB.

        Fetches person details (biography, etc.) and their combined credits,
        then dispatches background import tasks for each movie/show not yet
        in the database.

        Returns:
            Dict with counts: {"details_updated", "movies_queued", "shows_queued", "already_exists"}
        """
        from pyrate.metadata.tmdb import TMDB
        from pyrate.models.media import MediaExternalId

        if not person.tmdb_id:
            logger.warning("Cannot import filmography for person without tmdb_id: %s", person.guid)
            return {"details_updated": 0, "movies_queued": 0, "shows_queued": 0, "already_exists": 0}

        tmdb = TMDB(api_key=tmdb_api_key)
        stats = {"details_updated": 0, "movies_queued": 0, "shows_queued": 0, "already_exists": 0}

        try:
            # Step 1: Fetch and update person details
            details = await tmdb.get_person_details(str(person.tmdb_id))
            if details:
                await self.update_person_details(person, details)
                stats["details_updated"] = 1
                logger.info("Updated details for person %s (%s)", person.name, person.tmdb_id)

            # Step 2: Fetch combined credits
            credits = await tmdb.get_person_combined_credits(str(person.tmdb_id))
            if not credits:
                logger.warning("No credits found for person %s", person.name)
                await self.db.commit()
                return stats

            # Combine cast and crew credits, deduplicate by TMDB ID
            all_credits = []
            seen_tmdb_ids = set()

            for entry in credits.get("cast", []) + credits.get("crew", []):
                tmdb_id = entry.get("id")
                media_type = entry.get("media_type")
                if not tmdb_id or not media_type or tmdb_id in seen_tmdb_ids:
                    continue
                seen_tmdb_ids.add(tmdb_id)
                all_credits.append(entry)

            # Sort by popularity/vote_count to get most notable credits first
            all_credits.sort(key=lambda x: x.get("vote_count", 0), reverse=True)
            all_credits = all_credits[:max_credits]

            # Step 3: Check which credits already exist in DB
            existing_tmdb_ids_result = await self.db.execute(
                select(MediaExternalId.external_id)
                .where(MediaExternalId.provider == "tmdb")
                .where(
                    MediaExternalId.external_id.in_(
                        [str(c["id"]) for c in all_credits]
                    )
                )
            )
            existing_tmdb_ids = {row[0] for row in existing_tmdb_ids_result.all()}

            # Step 4: Check which library types are enabled
            from pyrate.services.library import LibraryService
            library_service = LibraryService(self.db)
            movies_library = await library_service.get_library_by_type("MOVIES")
            shows_library = await library_service.get_library_by_type("SHOWS")

            # Step 5: Dispatch import tasks for new credits
            from pyrate.worker import import_movie, import_show

            for entry in all_credits:
                tmdb_id = entry["id"]
                media_type = entry.get("media_type")

                if str(tmdb_id) in existing_tmdb_ids:
                    stats["already_exists"] += 1
                    continue

                if media_type == "movie" and movies_library:
                    await import_movie.kiq(tmdb_id)
                    stats["movies_queued"] += 1
                elif media_type == "tv" and shows_library:
                    await import_show.kiq(tmdb_id)
                    stats["shows_queued"] += 1

            await self.db.commit()

            logger.info(
                "Filmography import for %s: %d movies queued, %d shows queued, %d already exist",
                person.name,
                stats["movies_queued"],
                stats["shows_queued"],
                stats["already_exists"],
            )
            return stats

        except Exception:
            logger.exception("Failed to import filmography for person %s", person.name)
            raise
        finally:
            await tmdb.close()
