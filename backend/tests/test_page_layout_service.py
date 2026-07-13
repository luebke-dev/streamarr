"""Tests for the PageLayoutService."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.page_layout import PageLayout, PageSection, SectionType
from streamarr.services.page_layout import PageLayoutService


class TestPageLayoutCRUD:
    """Test basic CRUD operations for page layouts."""

    @pytest.mark.asyncio
    async def test_create_layout(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        layout = await service.create_layout(
            name="Home",
            slug="home",
            is_active=True,
        )

        assert layout.name == "Home"
        assert layout.slug == "home"
        assert layout.is_active is True
        assert layout.library_guid is None
        assert layout.guid is not None

    @pytest.mark.asyncio
    async def test_create_layout_with_sections(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        layout = await service.create_layout(
            name="Movies Layout",
            slug="movies",
            sections=[
                {"section_type": SectionType.HERO_CAROUSEL, "order_index": 0},
                {"section_type": SectionType.CONTINUE_WATCHING, "order_index": 1},
                {
                    "section_type": SectionType.ALL_GENRES,
                    "order_index": 2,
                    "config": {"max_items_per_genre": 10},
                },
            ],
        )

        assert layout.name == "Movies Layout"
        sections = sorted(layout.sections, key=lambda s: s.order_index)
        assert len(sections) == 3
        assert sections[0].section_type == SectionType.HERO_CAROUSEL
        assert sections[1].section_type == SectionType.CONTINUE_WATCHING
        assert sections[2].section_type == SectionType.ALL_GENRES
        assert sections[2].config == {"max_items_per_genre": 10}

    @pytest.mark.asyncio
    async def test_get_layout_by_guid(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        layout = await service.create_layout(name="Test", slug="test-get")
        fetched = await service.get_layout_by_guid(layout.guid)

        assert fetched is not None
        assert fetched.guid == layout.guid
        assert fetched.name == "Test"

    @pytest.mark.asyncio
    async def test_get_layout_by_slug(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        await service.create_layout(name="Home", slug="home-slug-test", is_active=True)
        fetched = await service.get_layout_by_slug("home-slug-test")

        assert fetched is not None
        assert fetched.slug == "home-slug-test"

    @pytest.mark.asyncio
    async def test_get_layout_by_slug_inactive_returns_none(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        await service.create_layout(name="Inactive", slug="inactive-test", is_active=False)
        fetched = await service.get_layout_by_slug("inactive-test")

        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_layout_by_slug_not_found(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        fetched = await service.get_layout_by_slug("nonexistent")
        assert fetched is None

    @pytest.mark.asyncio
    async def test_update_layout(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        layout = await service.create_layout(name="Old Name", slug="update-test")
        updated = await service.update_layout(layout.guid, name="New Name", is_active=False)

        assert updated is not None
        assert updated.name == "New Name"
        assert updated.is_active is False

    @pytest.mark.asyncio
    async def test_update_layout_not_found(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        result = await service.update_layout(uuid.uuid4(), name="Whatever")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_layout(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        layout = await service.create_layout(name="To Delete", slug="delete-test")
        deleted = await service.delete_layout(layout.guid)
        assert deleted is True

        fetched = await service.get_layout_by_guid(layout.guid)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_layout_not_found(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        deleted = await service.delete_layout(uuid.uuid4())
        assert deleted is False

    @pytest.mark.asyncio
    async def test_get_all_layouts(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        await service.create_layout(name="Layout A", slug="all-a")
        await service.create_layout(name="Layout B", slug="all-b")

        layouts, total = await service.get_all_layouts()
        assert total >= 2
        names = {l.name for l in layouts}
        assert "Layout A" in names
        assert "Layout B" in names

    @pytest.mark.asyncio
    async def test_get_layout_for_library_fallback(self, db_session: AsyncSession):
        """When no library-specific layout exists, falls back to 'home'."""
        service = PageLayoutService(db_session)
        await service.create_layout(name="Home", slug="home", is_active=True)
        result = await service.get_layout_for_library(uuid.uuid4())

        assert result is not None
        assert result.slug == "home"


class TestPageSectionCRUD:
    """Test section CRUD operations."""

    @pytest.mark.asyncio
    async def test_add_section(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        layout = await service.create_layout(name="SectionTest", slug="section-test")

        section = await service.add_section(
            layout_guid=layout.guid,
            section_type=SectionType.HERO_CAROUSEL,
            title="My Hero",
            config={"list_guid": str(uuid.uuid4())},
        )

        assert section.guid is not None
        assert section.section_type == SectionType.HERO_CAROUSEL
        assert section.title == "My Hero"
        assert section.order_index == 0
        assert section.is_enabled is True

    @pytest.mark.asyncio
    async def test_add_section_auto_order(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        layout = await service.create_layout(name="AutoOrder", slug="auto-order")

        s1 = await service.add_section(layout.guid, SectionType.HERO_CAROUSEL)
        s2 = await service.add_section(layout.guid, SectionType.CONTINUE_WATCHING)
        s3 = await service.add_section(layout.guid, SectionType.FAVORITES)

        assert s1.order_index == 0
        assert s2.order_index == 1
        assert s3.order_index == 2

    @pytest.mark.asyncio
    async def test_update_section(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        layout = await service.create_layout(name="UpdateSec", slug="update-sec")
        section = await service.add_section(layout.guid, SectionType.GENRE, title="Action")

        updated = await service.update_section(section.guid, title="Comedy", is_enabled=False)
        assert updated is not None
        assert updated.title == "Comedy"
        assert updated.is_enabled is False

    @pytest.mark.asyncio
    async def test_update_section_not_found(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        result = await service.update_section(uuid.uuid4(), title="Nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_section(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        layout = await service.create_layout(name="DelSec", slug="del-sec")
        section = await service.add_section(layout.guid, SectionType.FAVORITES)

        deleted = await service.delete_section(section.guid)
        assert deleted is True

        fetched = await service.get_section_by_guid(section.guid)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_section_not_found(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        deleted = await service.delete_section(uuid.uuid4())
        assert deleted is False

    @pytest.mark.asyncio
    async def test_reorder_sections(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        layout = await service.create_layout(name="Reorder", slug="reorder")

        s1 = await service.add_section(layout.guid, SectionType.HERO_CAROUSEL)
        s2 = await service.add_section(layout.guid, SectionType.CONTINUE_WATCHING)
        s3 = await service.add_section(layout.guid, SectionType.FAVORITES)

        s1_guid, s2_guid, s3_guid = s1.guid, s2.guid, s3.guid

        # Reverse the order
        reordered = await service.reorder_sections(
            layout.guid,
            [s3_guid, s2_guid, s1_guid],
        )

        assert reordered is not None
        section_map = {s.guid: s for s in reordered.sections}
        assert section_map[s3_guid].order_index == 0
        assert section_map[s2_guid].order_index == 1
        assert section_map[s1_guid].order_index == 2

    @pytest.mark.asyncio
    async def test_reorder_sections_not_found(self, db_session: AsyncSession):
        service = PageLayoutService(db_session)
        result = await service.reorder_sections(uuid.uuid4(), [])
        assert result is None

    @pytest.mark.asyncio
    async def test_section_config_jsonb(self, db_session: AsyncSession):
        """Test that JSONB config is stored and retrieved correctly."""
        service = PageLayoutService(db_session)
        layout = await service.create_layout(name="JsonTest", slug="json-test")

        config = {
            "filters": {
                "media_type": "MOVIES",
                "genre_id": 28,
                "year_from": 2020,
                "sort_by": "rating",
                "sort_order": "desc",
            },
            "max_items": 20,
        }

        section = await service.add_section(
            layout.guid,
            SectionType.DYNAMIC_SEARCH,
            title="Recent Top Movies",
            config=config,
        )

        fetched = await service.get_section_by_guid(section.guid)
        assert fetched is not None
        assert fetched.config["filters"]["media_type"] == "MOVIES"
        assert fetched.config["filters"]["genre_id"] == 28
        assert fetched.config["max_items"] == 20
