"""Service for importing book metadata from Open Library.

Creates Author → Book hierarchy with deduplication.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import (
    AvailabilityStatus,
    MediaExternalId,
    MediaItem,
    MediaType,
)
from streamarr.services.media import MediaService

logger = logging.getLogger(__name__)


class BookImportService:
    """Imports books from Open Library with Author hierarchy."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.media_service = MediaService(db)

    async def import_book(self, openlibrary_id: str) -> dict | None:
        """Import a book by Open Library work ID.

        Creates the Author entity if needed, then the Book as a child.
        Returns dict with book info or None if skipped.
        """
        # Check if already imported
        existing = await self.media_service.get_by_external_id(
            provider="openlibrary",
            external_id=openlibrary_id,
            media_type=MediaType.BOOKS,
        )
        if existing:
            logger.info("Book %s already exists as '%s'", openlibrary_id, existing.title)
            return None

        from streamarr.metadata.openlibrary import OpenLibrary

        ol = OpenLibrary()
        try:
            details = await ol.get_details(openlibrary_id)
            if not details or not details.get("title"):
                logger.warning("No details found for book %s", openlibrary_id)
                return None

            # Import author(s)
            authors = details.get("authors", [])
            primary_author = None

            for author_data in authors:
                author_key = author_data.get("key")
                author_name = author_data.get("name")
                if not author_key or not author_name:
                    continue

                author_item = await self._get_or_create_author(
                    author_key, author_name, author_data.get("photo_url"),
                )
                if author_item and primary_author is None:
                    primary_author = author_item

            # Import book as child of primary author
            book_item = await self.media_service.create_media_item(
                media_type=MediaType.BOOKS,
                title=details.get("title"),
                description=details.get("description"),
                poster_path=details.get("cover_url"),
                availability_status=AvailabilityStatus.DOWNLOADABLE,
                parent_guid=primary_author.guid if primary_author else None,
            )

            # Parse release date
            release_date = self._parse_date(details.get("first_publish_date"))
            if release_date:
                book_item.release_date = release_date
                self.db.add(book_item)

            # Add external ID
            await self.media_service.add_external_id(
                media_item_guid=book_item.guid,
                provider="openlibrary",
                external_id=openlibrary_id,
            )

            # Set genres from subjects
            subjects = details.get("subjects", [])
            if subjects:
                await self.media_service.set_genres(book_item.guid, subjects[:10])

            await self.db.commit()

            logger.info(
                "Imported book: %s by %s (parent=%s)",
                book_item.title,
                primary_author.title if primary_author else "Unknown",
                primary_author.guid if primary_author else None,
            )

            return {
                "title": book_item.title,
                "guid": str(book_item.guid),
                "author": primary_author.title if primary_author else None,
            }

        finally:
            await ol.close()

    async def _get_or_create_author(
        self, author_key: str, author_name: str, photo_url: str | None = None,
    ) -> MediaItem | None:
        """Get existing author or create new one."""
        # Check if author already exists
        existing = await self.media_service.get_by_external_id(
            provider="openlibrary_author",
            external_id=author_key,
            media_type=MediaType.AUTHORS,
        )
        if existing:
            return existing

        author_item = await self.media_service.create_media_item(
            media_type=MediaType.AUTHORS,
            title=author_name,
            poster_path=photo_url,
            availability_status=AvailabilityStatus.DOWNLOADABLE,
        )

        await self.media_service.add_external_id(
            media_item_guid=author_item.guid,
            provider="openlibrary_author",
            external_id=author_key,
        )

        logger.info("Created author: %s (%s)", author_name, author_key)
        return author_item

    @staticmethod
    def _parse_date(date_str: str | None):
        """Parse Open Library date strings (various formats)."""
        if not date_str:
            return None
        from datetime import datetime
        for fmt in ("%Y", "%B %d, %Y", "%Y-%m-%d", "%d %B %Y", "%B %Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        return None
