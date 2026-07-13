"""Page Layout service for managing configurable page layouts and sections."""

import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from streamarr.models.library import Library
from streamarr.models.page_layout import PageLayout, PageSection


def _to_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return uuid.UUID(value) if isinstance(value, str) else value


class PageLayoutService:
    """Service for managing page layouts and their sections."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- Layout CRUD ----

    async def get_layout_by_guid(self, layout_guid: str | uuid.UUID) -> PageLayout | None:
        result = await self.db.execute(
            select(PageLayout)
            .options(selectinload(PageLayout.sections))
            .where(PageLayout.guid == _to_uuid(layout_guid))
        )
        return result.scalar_one_or_none()

    async def get_layout_by_slug(self, slug: str) -> PageLayout | None:
        result = await self.db.execute(
            select(PageLayout)
            .options(selectinload(PageLayout.sections))
            .where(PageLayout.slug == slug, PageLayout.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_layout_for_library(self, library_guid: str | uuid.UUID) -> PageLayout | None:
        """Get layout for a specific library, falling back to the 'home' layout."""
        lib_uuid = _to_uuid(library_guid)
        result = await self.db.execute(
            select(PageLayout)
            .options(selectinload(PageLayout.sections))
            .where(
                PageLayout.library_guid == lib_uuid,
                PageLayout.is_active.is_(True),
            )
        )
        layout = result.scalar_one_or_none()
        if layout:
            return layout
        # Fallback to home layout
        return await self.get_layout_by_slug("home")

    async def get_layout_for_media_type(self, media_type: str) -> PageLayout | None:
        """Get layout for a media type by looking up the library, falling back to 'home'."""
        # Find the library with this type
        lib_result = await self.db.execute(
            select(Library.guid).where(Library.type == media_type).limit(1)
        )
        lib_guid = lib_result.scalar_one_or_none()
        if lib_guid:
            return await self.get_layout_for_library(lib_guid)
        # No library found for this type — fall back to home
        return await self.get_layout_by_slug("home")

    async def get_all_layouts(
        self,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[PageLayout], int]:
        count_result = await self.db.execute(select(func.count(PageLayout.guid)))
        total = count_result.scalar_one()

        result = await self.db.execute(
            select(PageLayout)
            .options(selectinload(PageLayout.sections))
            .order_by(PageLayout.name)
            .offset(skip)
            .limit(limit)
        )
        layouts = list(result.scalars().all())
        return layouts, total

    async def create_layout(
        self,
        name: str,
        slug: str,
        library_guid: uuid.UUID | None = None,
        is_active: bool = True,
        sections: list[dict] | None = None,
    ) -> PageLayout:
        # Check for an existing layout with this slug up-front so the API
        # returns a meaningful 409 instead of a SQL-level UniqueViolationError
        # (which surfaces as a confusing 500 in the admin UI).
        existing = await self.get_layout_by_slug(slug)
        if existing is not None:
            logger.info(
                "Refusing to create page layout: slug=%s already in use by %s",
                slug, existing.guid,
            )
            raise ValueError(f"slug_taken:{existing.guid}")

        layout = PageLayout(
            name=name,
            slug=slug,
            library_guid=library_guid,
            is_active=is_active,
        )
        self.db.add(layout)
        await self.db.flush()

        if sections:
            for idx, section_data in enumerate(sections):
                section = PageSection(
                    layout_guid=layout.guid,
                    section_type=section_data["section_type"],
                    order_index=section_data.get("order_index", idx),
                    title=section_data.get("title"),
                    config=section_data.get("config", {}),
                    is_enabled=section_data.get("is_enabled", True),
                )
                self.db.add(section)

        await self.db.commit()
        await self.db.refresh(layout)
        logger.info("Created page layout name=%s slug=%s id=%s", name, slug, layout.guid)
        return layout

    async def update_layout(
        self,
        layout_guid: str | uuid.UUID,
        **kwargs,
    ) -> PageLayout | None:
        layout = await self.get_layout_by_guid(layout_guid)
        if not layout:
            logger.warning("Layout not found for update: %s", layout_guid)
            return None

        for key, value in kwargs.items():
            if value is not None and hasattr(layout, key):
                setattr(layout, key, value)

        await self.db.commit()
        await self.db.refresh(layout)
        logger.info("Updated page layout id=%s fields=%s", layout_guid, list(kwargs.keys()))
        return layout

    async def delete_layout(self, layout_guid: str | uuid.UUID) -> bool:
        layout = await self.get_layout_by_guid(layout_guid)
        if not layout:
            logger.warning("Layout not found for deletion: %s", layout_guid)
            return False
        await self.db.delete(layout)
        await self.db.commit()
        logger.info("Deleted page layout id=%s", layout_guid)
        return True

    # ---- Section CRUD ----

    async def get_section_by_guid(self, section_guid: str | uuid.UUID) -> PageSection | None:
        result = await self.db.execute(
            select(PageSection).where(PageSection.guid == _to_uuid(section_guid))
        )
        return result.scalar_one_or_none()

    async def add_section(
        self,
        layout_guid: str | uuid.UUID,
        section_type: str,
        order_index: int | None = None,
        title: str | None = None,
        config: dict | None = None,
        is_enabled: bool = True,
    ) -> PageSection:
        layout_uuid = _to_uuid(layout_guid)

        if order_index is None:
            # Auto-assign next order index
            result = await self.db.execute(
                select(func.coalesce(func.max(PageSection.order_index), -1))
                .where(PageSection.layout_guid == layout_uuid)
            )
            order_index = result.scalar_one() + 1

        section = PageSection(
            layout_guid=layout_uuid,
            section_type=section_type,
            order_index=order_index,
            title=title,
            config=config or {},
            is_enabled=is_enabled,
        )
        self.db.add(section)
        await self.db.commit()
        await self.db.refresh(section)
        logger.info("Added section type=%s to layout id=%s", section_type, layout_guid)
        return section

    async def update_section(
        self,
        section_guid: str | uuid.UUID,
        **kwargs,
    ) -> PageSection | None:
        section = await self.get_section_by_guid(section_guid)
        if not section:
            logger.warning("Section not found for update: %s", section_guid)
            return None

        for key, value in kwargs.items():
            if value is not None and hasattr(section, key):
                setattr(section, key, value)

        await self.db.commit()
        await self.db.refresh(section)
        logger.info("Updated section id=%s fields=%s", section_guid, list(kwargs.keys()))
        return section

    async def delete_section(self, section_guid: str | uuid.UUID) -> bool:
        section = await self.get_section_by_guid(section_guid)
        if not section:
            logger.warning("Section not found for deletion: %s", section_guid)
            return False
        await self.db.delete(section)
        await self.db.commit()
        logger.info("Deleted section id=%s", section_guid)
        return True

    async def reorder_sections(
        self,
        layout_guid: str | uuid.UUID,
        section_order: list[uuid.UUID],
    ) -> PageLayout | None:
        """Reorder sections by updating their order_index based on position in the list."""
        layout = await self.get_layout_by_guid(layout_guid)
        if not layout:
            logger.warning("Layout not found for reorder: %s", layout_guid)
            return None

        # Use explicit UPDATE statements to avoid identity map issues
        for idx, s_guid in enumerate(section_order):
            await self.db.execute(
                update(PageSection)
                .where(PageSection.guid == s_guid)
                .values(order_index=idx)
            )

        await self.db.commit()
        self.db.expire_all()
        return await self.get_layout_by_guid(layout_guid)
