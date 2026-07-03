"""Translation service for multi-language metadata."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.media_translation import MediaItemTranslation

logger = logging.getLogger(__name__)


class TranslationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_translation(
        self, media_item_guid: uuid.UUID, language: str
    ) -> MediaItemTranslation | None:
        """Get translation for a specific language."""
        result = await self.db.execute(
            select(MediaItemTranslation).where(
                MediaItemTranslation.media_item_guid == media_item_guid,
                MediaItemTranslation.language == language,
            )
        )
        return result.scalar_one_or_none()

    async def get_translated_fields(
        self, media_item, user_language: str
    ) -> dict:
        """
        Get title/description/tagline in the user's preferred language.

        Fallback chain:
        1. Exact language match (e.g. "de")
        2. First available translation
        3. MediaItem original fields
        """
        # Normalize language (e.g. "de-DE" → "de")
        lang = user_language.split("-")[0].lower() if user_language else "en"

        # Try exact match
        translation = await self.get_translation(media_item.guid, lang)
        if translation:
            return {
                "title": translation.title or media_item.title,
                "description": translation.description or media_item.description,
                "tagline": translation.tagline or media_item.tagline,
            }

        # Try first available
        result = await self.db.execute(
            select(MediaItemTranslation)
            .where(MediaItemTranslation.media_item_guid == media_item.guid)
            .limit(1)
        )
        fallback = result.scalar_one_or_none()
        if fallback:
            return {
                "title": fallback.title or media_item.title,
                "description": fallback.description or media_item.description,
                "tagline": fallback.tagline or media_item.tagline,
            }

        # Original fields
        return {
            "title": media_item.title,
            "description": media_item.description,
            "tagline": media_item.tagline,
        }

    async def set_translation(
        self,
        media_item_guid: uuid.UUID,
        language: str,
        title: str | None = None,
        description: str | None = None,
        tagline: str | None = None,
    ) -> MediaItemTranslation:
        """Create or update a translation for a media item."""
        existing = await self.get_translation(media_item_guid, language)

        if existing:
            if title is not None:
                existing.title = title
            if description is not None:
                existing.description = description
            if tagline is not None:
                existing.tagline = tagline
            existing.updated_at = datetime.now(UTC)
            await self.db.commit()
            await self.db.refresh(existing)
            logger.debug("Updated translation media=%s lang=%s", media_item_guid, language)
            return existing

        translation = MediaItemTranslation(
            media_item_guid=media_item_guid,
            language=language,
            title=title,
            description=description,
            tagline=tagline,
        )
        self.db.add(translation)
        await self.db.commit()
        await self.db.refresh(translation)
        logger.debug("Created translation media=%s lang=%s", media_item_guid, language)
        return translation

    async def set_translations_from_provider(
        self,
        media_item_guid: uuid.UUID,
        translations: dict[str, dict],
    ) -> int:
        """
        Bulk-upsert translations from a metadata provider response in a single statement,
        backed by ``uq_media_translation_item_language``.
        """
        if not translations:
            return 0

        now = datetime.now(UTC)
        rows = []
        seen: set[str] = set()
        for language, fields in translations.items():
            lang = language.split("-")[0].lower()
            if lang in seen:
                continue
            seen.add(lang)
            rows.append({
                "media_item_guid": media_item_guid,
                "language": lang,
                "title": fields.get("title"),
                "description": fields.get("description") or fields.get("overview"),
                "tagline": fields.get("tagline"),
                "updated_at": now,
            })

        if not rows:
            return 0

        stmt = pg_insert(MediaItemTranslation).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_media_translation_item_language",
            set_={
                "title": stmt.excluded.title,
                "description": stmt.excluded.description,
                "tagline": stmt.excluded.tagline,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await self.db.execute(stmt)
        await self.db.commit()

        logger.debug(
            "Stored %d translations from provider for media=%s", len(rows), media_item_guid,
        )
        return len(rows)

    async def apply_translations(
        self, items: list, user_language: str
    ) -> list:
        """
        Apply translations to a list of Pydantic models (MediaItemSummary etc).
        Modifies title/description/tagline in place based on user language.
        """
        if not items:
            return items

        lang = user_language.split("-")[0].lower() if user_language else "en"

        guids = [item.guid for item in items]
        result = await self.db.execute(
            select(MediaItemTranslation).where(
                MediaItemTranslation.media_item_guid.in_(guids),
                MediaItemTranslation.language == lang,
            )
        )
        translations_map = {t.media_item_guid: t for t in result.scalars().all()}

        for item in items:
            t = translations_map.get(item.guid)
            if t:
                if t.title:
                    item.title = t.title
                if hasattr(item, "description") and t.description:
                    item.description = t.description
                if hasattr(item, "tagline") and t.tagline:
                    item.tagline = t.tagline

        return items
