"""Tests for the LibraryService."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.library import Library
from streamarr.models.media import (
    AvailabilityStatus,
    MediaExternalId,
    MediaItem,
    MediaRelease,
    MediaType,
)
from streamarr.models.user import User
from streamarr.services.library import LibraryService


class MockPlugin:
    """Mock plugin for testing."""

    def __init__(self, library_type="MOVIES"):
        self.library_type = library_type

    async def get_default_path(self):
        return f"/library/{self.library_type.lower()}"

    async def validate_path(self, path):
        return True

    async def initialize_library(self, path):
        pass

    async def get_library_stats(self, path):
        return {
            "total_items": 42,
            "total_size": 1024000,
        }

    async def scan_library(self, path):
        return [
            {"path": f"{path}/movie1.mp4", "size": 1000},
            {"path": f"{path}/movie2.mp4", "size": 2000},
        ]

    async def match_media(self, file_info):
        return {
            "title": "Test Movie",
            "external_id": "12345",
            "provider": "tmdb",
        }


class TestLibraryCRUD:
    """Test basic CRUD operations for libraries."""

    @pytest.mark.asyncio
    async def test_create_library(self, db_session: AsyncSession):
        """Test creating a library."""
        service = LibraryService(db_session)

        # Mock the plugin
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="My Movies",
                type="MOVIES",
                plugin_id="movies",
                path="/data/movies",
                enabled=True,
                description="Collection of movies",
            )

        assert library.name == "My Movies"
        assert library.type == "MOVIES"
        assert library.plugin_id == "movies"
        assert library.path == "/data/movies"
        assert library.enabled is True
        assert library.description == "Collection of movies"
        assert library.guid is not None

    @pytest.mark.asyncio
    async def test_create_library_with_default_path(self, db_session: AsyncSession):
        """Test creating a library with default path."""
        service = LibraryService(db_session)

        with patch.object(service, "get_plugin", return_value=MockPlugin("SHOWS")):
            library = await service.create_library(
                name="My Shows",
                type="SHOWS",
                plugin_id="shows",
                path=None,  # Use default path
                enabled=True,
            )

        assert library.path == "/library/shows"

    @pytest.mark.asyncio
    async def test_create_library_invalid_type(self, db_session: AsyncSession):
        """Test creating a library with invalid type."""
        service = LibraryService(db_session)

        with patch.object(service, "get_plugin", return_value=None):
            with pytest.raises(ValueError, match="No plugin found for library type"):
                await service.create_library(
                    name="Invalid",
                    type="INVALID_TYPE",
                    plugin_id="invalid",
                    path="/data/invalid",
                )

    @pytest.mark.asyncio
    async def test_create_library_invalid_path(self, db_session: AsyncSession):
        """Test creating a library with invalid path."""
        service = LibraryService(db_session)

        mock_plugin = MockPlugin()
        mock_plugin.validate_path = AsyncMock(return_value=False)

        with patch.object(service, "get_plugin", return_value=mock_plugin):
            with pytest.raises(ValueError, match="Invalid library path"):
                await service.create_library(
                    name="Invalid Path",
                    type="MOVIES",
                    plugin_id="movies",
                    path="/invalid/path",
                )

    @pytest.mark.asyncio
    async def test_get_library(self, db_session: AsyncSession):
        """Test retrieving a library by GUID."""
        service = LibraryService(db_session)

        # Create library
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            created = await service.create_library(
                name="Test Library",
                type="MOVIES",
                plugin_id="movies",
                path="/data/test",
            )

        # Retrieve it
        retrieved = await service.get_library(created.guid)

        assert retrieved is not None
        assert retrieved.guid == created.guid
        assert retrieved.name == "Test Library"

    @pytest.mark.asyncio
    async def test_get_library_not_found(self, db_session: AsyncSession):
        """Test retrieving a non-existent library."""
        service = LibraryService(db_session)

        retrieved = await service.get_library(uuid.uuid4())

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_library_by_type(self, db_session: AsyncSession):
        """Test retrieving a library by type."""
        service = LibraryService(db_session)

        # Create multiple libraries
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            await service.create_library(
                name="Movies 1",
                type="MOVIES",
                plugin_id="movies",
                path="/data/movies1",
            )
            await service.create_library(
                name="Movies 2",
                type="MOVIES",
                plugin_id="movies",
                path="/data/movies2",
            )

        with patch.object(service, "get_plugin", return_value=MockPlugin("SHOWS")):
            await service.create_library(
                name="Shows 1",
                type="SHOWS",
                plugin_id="shows",
                path="/data/shows",
            )

        # Get first library by type
        movies_lib = await service.get_library_by_type("MOVIES")
        assert movies_lib is not None
        assert movies_lib.type == "MOVIES"
        assert movies_lib.name == "Movies 1"  # First created

        shows_lib = await service.get_library_by_type("SHOWS")
        assert shows_lib is not None
        assert shows_lib.type == "SHOWS"

    @pytest.mark.asyncio
    async def test_list_libraries(self, db_session: AsyncSession):
        """Test listing all libraries."""
        service = LibraryService(db_session)

        # Create libraries
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            await service.create_library(
                name="Movies",
                type="MOVIES",
                plugin_id="movies",
                path="/data/movies",
                enabled=True,
            )

        with patch.object(service, "get_plugin", return_value=MockPlugin("SHOWS")):
            await service.create_library(
                name="Shows",
                type="SHOWS",
                plugin_id="shows",
                path="/data/shows",
                enabled=False,
            )

        # List all
        all_libs = await service.list_libraries(enabled_only=False)
        assert len(all_libs) == 2

        # List enabled only
        enabled_libs = await service.list_libraries(enabled_only=True)
        assert len(enabled_libs) == 1
        assert enabled_libs[0].name == "Movies"

    @pytest.mark.asyncio
    async def test_update_library(self, db_session: AsyncSession):
        """Test updating a library."""
        service = LibraryService(db_session)

        # Create library
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            created = await service.create_library(
                name="Original Name",
                type="MOVIES",
                plugin_id="movies",
                path="/data/original",
                enabled=True,
            )

        # Update it
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            updated = await service.update_library(
                created.guid,
                name="Updated Name",
                path="/data/updated",
                enabled=False,
                description="New description",
            )

        assert updated is not None
        assert updated.name == "Updated Name"
        assert updated.path == "/data/updated"
        assert updated.enabled is False
        assert updated.description == "New description"

    @pytest.mark.asyncio
    async def test_update_library_not_found(self, db_session: AsyncSession):
        """Test updating a non-existent library."""
        service = LibraryService(db_session)

        updated = await service.update_library(
            uuid.uuid4(),
            name="New Name",
        )

        assert updated is None

    @pytest.mark.asyncio
    async def test_update_library_invalid_path(self, db_session: AsyncSession):
        """Test updating library with invalid path."""
        service = LibraryService(db_session)

        # Create library
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            created = await service.create_library(
                name="Test",
                type="MOVIES",
                plugin_id="movies",
                path="/data/test",
            )

        # Try to update with invalid path
        mock_plugin = MockPlugin()
        mock_plugin.validate_path = AsyncMock(return_value=False)

        with patch.object(service, "get_plugin", return_value=mock_plugin):
            with pytest.raises(ValueError, match="Invalid library path"):
                await service.update_library(
                    created.guid,
                    path="/invalid/path",
                )

    @pytest.mark.asyncio
    async def test_delete_library(self, db_session: AsyncSession):
        """Test deleting a library."""
        service = LibraryService(db_session)

        # Create library
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            created = await service.create_library(
                name="To Delete",
                type="MOVIES",
                plugin_id="movies",
                path="/data/delete",
            )

        # Delete it
        result = await service.delete_library(created.guid)
        assert result is True

        # Verify it's gone
        retrieved = await service.get_library(created.guid)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_library_not_found(self, db_session: AsyncSession):
        """Test deleting a non-existent library."""
        service = LibraryService(db_session)

        result = await service.delete_library(uuid.uuid4())
        assert result is False


class TestLibraryStats:
    """Test library statistics functionality."""

    @pytest.mark.asyncio
    async def test_get_library_stats(self, db_session: AsyncSession):
        """Test getting library statistics."""
        service = LibraryService(db_session)

        # Create library
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="Stats Test",
                type="MOVIES",
                plugin_id="movies",
                path="/data/stats",
            )

        # Get stats
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            stats = await service.get_library_stats(library.guid)

        assert stats is not None
        assert stats["library_name"] == "Stats Test"
        assert stats["library_type"] == "MOVIES"
        assert stats["enabled"] is True
        assert stats["total_items"] == 42
        assert stats["total_size"] == 1024000

    @pytest.mark.asyncio
    async def test_get_library_stats_not_found(self, db_session: AsyncSession):
        """Test getting stats for non-existent library."""
        service = LibraryService(db_session)

        stats = await service.get_library_stats(uuid.uuid4())
        assert stats is None


class TestMediaItemOperations:
    """Test media item CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_media_item_with_library(self, db_session: AsyncSession):
        """Test creating a media item with library."""
        service = LibraryService(db_session)

        # Create library first
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="Test Library",
                type="MOVIES",
                plugin_id="movies",
                path="/data/movies",
            )

        # Create media item
        media_item = await service.create_media_item(
            title="Test Movie",
            library_guid=library.guid,
            original_title="Test Movie Original",
            description="A test movie",
        )

        assert media_item.title == "Test Movie"
        assert media_item.media_type == MediaType.MOVIES
        assert media_item.original_title == "Test Movie Original"
        assert media_item.description == "A test movie"

    @pytest.mark.asyncio
    async def test_create_media_item_with_type(self, db_session: AsyncSession):
        """Test creating a media item with explicit type."""
        service = LibraryService(db_session)

        media_item = await service.create_media_item(
            title="Test Show",
            media_type=MediaType.SHOWS,
            description="A test show",
        )

        assert media_item.title == "Test Show"
        assert media_item.media_type == MediaType.SHOWS

    @pytest.mark.asyncio
    async def test_create_media_item_no_type_or_library(
        self, db_session: AsyncSession
    ):
        """Test creating media item without type or library fails."""
        service = LibraryService(db_session)

        with pytest.raises(
            ValueError, match="media_type must be provided"
        ):
            await service.create_media_item(title="Test")

    @pytest.mark.asyncio
    async def test_get_media_item(self, db_session: AsyncSession):
        """Test retrieving a media item."""
        service = LibraryService(db_session)

        created = await service.create_media_item(
            title="Test Item",
            media_type=MediaType.MOVIES,
        )

        retrieved = await service.get_media_item(created.guid)

        assert retrieved is not None
        assert retrieved.guid == created.guid
        assert retrieved.title == "Test Item"

    @pytest.mark.asyncio
    async def test_get_media_item_not_found(self, db_session: AsyncSession):
        """Test retrieving non-existent media item."""
        service = LibraryService(db_session)

        retrieved = await service.get_media_item(uuid.uuid4())
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_list_media_items(self, db_session: AsyncSession):
        """Test listing media items with filtering."""
        service = LibraryService(db_session)

        # Create library
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="Test Library",
                type="MOVIES",
                plugin_id="movies",
                path="/data/movies",
            )

        # Create items
        await service.create_media_item(
            title="Movie 1",
            media_type=MediaType.MOVIES,
        )
        await service.create_media_item(
            title="Movie 2",
            media_type=MediaType.MOVIES,
        )
        await service.create_media_item(
            title="Show 1",
            media_type=MediaType.SHOWS,
        )

        # List all items
        all_items = await service.list_media_items()
        assert len(all_items) == 3

        # List by type
        movie_items = await service.list_media_items(media_type=MediaType.MOVIES)
        assert len(movie_items) == 2

        show_items = await service.list_media_items(media_type=MediaType.SHOWS)
        assert len(show_items) == 1

    @pytest.mark.asyncio
    async def test_list_media_items_pagination(self, db_session: AsyncSession):
        """Test pagination of media items."""
        service = LibraryService(db_session)

        # Create items
        for i in range(5):
            await service.create_media_item(
                title=f"Movie {i}",
                media_type=MediaType.MOVIES,
            )

        # Get first page
        page1 = await service.list_media_items(limit=2, offset=0)
        assert len(page1) == 2

        # Get second page
        page2 = await service.list_media_items(limit=2, offset=2)
        assert len(page2) == 2

        # Ensure different items
        page1_guids = {str(item.guid) for item in page1}
        page2_guids = {str(item.guid) for item in page2}
        assert page1_guids.isdisjoint(page2_guids)

    @pytest.mark.asyncio
    async def test_count_media_items(self, db_session: AsyncSession):
        """Test counting media items."""
        service = LibraryService(db_session)

        # Create library
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="Test Library",
                type="MOVIES",
                plugin_id="movies",
                path="/data/movies",
            )

        # Create items
        await service.create_media_item(title="Movie 1", media_type=MediaType.MOVIES)
        await service.create_media_item(title="Movie 2", media_type=MediaType.MOVIES)
        await service.create_media_item(title="Show 1", media_type=MediaType.SHOWS)

        # Count all
        total = await service.count_media_items()
        assert total == 3

        # Count by type
        movie_count = await service.count_media_items(media_type=MediaType.MOVIES)
        assert movie_count == 2

        show_count = await service.count_media_items(media_type=MediaType.SHOWS)
        assert show_count == 1

    @pytest.mark.asyncio
    async def test_search_media_items(self, db_session: AsyncSession):
        """Test searching media items by title."""
        service = LibraryService(db_session)

        # Create items
        await service.create_media_item(
            title="The Matrix",
            media_type=MediaType.MOVIES,
        )
        await service.create_media_item(
            title="The Matrix Reloaded",
            media_type=MediaType.MOVIES,
        )
        await service.create_media_item(
            title="Inception",
            media_type=MediaType.MOVIES,
        )

        # Search
        results = await service.search_media_items("Matrix")
        assert len(results) == 2

        results = await service.search_media_items("Inception")
        assert len(results) == 1

        results = await service.search_media_items("Nonexistent")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_update_media_item(self, db_session: AsyncSession):
        """Test updating media item."""
        service = LibraryService(db_session)

        created = await service.create_media_item(
            title="Original Title",
            media_type=MediaType.MOVIES,
        )

        updated = await service.update_media_item(
            created.guid,
            title="Updated Title",
            description="New description",
        )

        assert updated is not None
        assert updated.title == "Updated Title"
        assert updated.description == "New description"

    @pytest.mark.asyncio
    async def test_update_media_item_not_found(self, db_session: AsyncSession):
        """Test updating non-existent media item."""
        service = LibraryService(db_session)

        updated = await service.update_media_item(
            uuid.uuid4(),
            title="New Title",
        )

        assert updated is None

    @pytest.mark.asyncio
    async def test_delete_media_item(self, db_session: AsyncSession):
        """Test deleting media item."""
        service = LibraryService(db_session)

        created = await service.create_media_item(
            title="To Delete",
            media_type=MediaType.MOVIES,
        )

        result = await service.delete_media_item(created.guid)
        assert result is True

        retrieved = await service.get_media_item(created.guid)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_media_item_not_found(self, db_session: AsyncSession):
        """Test deleting non-existent media item."""
        service = LibraryService(db_session)

        result = await service.delete_media_item(uuid.uuid4())
        assert result is False


class TestMediaItemRelationships:
    """Test media item parent-child relationships."""

    @pytest.mark.asyncio
    async def test_get_children(self, db_session: AsyncSession):
        """Test getting child media items."""
        service = LibraryService(db_session)

        # Create parent (show)
        parent = await service.create_media_item(
            title="Test Show",
            media_type=MediaType.SHOWS,
        )

        # Create children (seasons)
        await service.create_media_item(
            title="Season 1",
            media_type=MediaType.SHOWS,
            parent_guid=parent.guid,
            sequence_number=1,
        )
        await service.create_media_item(
            title="Season 2",
            media_type=MediaType.SHOWS,
            parent_guid=parent.guid,
            sequence_number=2,
        )

        # Get children
        children = await service.get_children(parent.guid)

        assert len(children) == 2
        assert children[0].title == "Season 1"
        assert children[1].title == "Season 2"


class TestExternalIds:
    """Test external ID operations."""

    @pytest.mark.asyncio
    async def test_add_external_id(self, db_session: AsyncSession):
        """Test adding external ID."""
        service = LibraryService(db_session)

        media_item = await service.create_media_item(
            title="Test Movie",
            media_type=MediaType.MOVIES,
        )

        ext_id = await service.add_external_id(
            media_item.guid,
            provider="tmdb",
            external_id="12345",
        )

        assert ext_id.media_item_guid == media_item.guid
        assert ext_id.provider == "tmdb"
        assert ext_id.external_id == "12345"

    @pytest.mark.asyncio
    async def test_get_by_external_id(self, db_session: AsyncSession):
        """Test getting media item by external ID."""
        service = LibraryService(db_session)

        media_item = await service.create_media_item(
            title="Test Movie",
            media_type=MediaType.MOVIES,
        )

        await service.add_external_id(
            media_item.guid,
            provider="tmdb",
            external_id="12345",
        )

        # Retrieve by external ID
        retrieved = await service.get_by_external_id(
            provider="tmdb",
            external_id="12345",
        )

        assert retrieved is not None
        assert retrieved.guid == media_item.guid

    @pytest.mark.asyncio
    async def test_get_by_external_id_with_type_filter(
        self, db_session: AsyncSession
    ):
        """Test getting media item by external ID with type filter."""
        service = LibraryService(db_session)

        movie = await service.create_media_item(
            title="Test Movie",
            media_type=MediaType.MOVIES,
        )

        await service.add_external_id(
            movie.guid,
            provider="tmdb",
            external_id="12345",
        )

        # Should find with correct type
        retrieved = await service.get_by_external_id(
            provider="tmdb",
            external_id="12345",
            media_type=MediaType.MOVIES,
        )
        assert retrieved is not None

        # Should not find with wrong type
        retrieved = await service.get_by_external_id(
            provider="tmdb",
            external_id="12345",
            media_type=MediaType.SHOWS,
        )
        assert retrieved is None


class TestLibraryScanAndMatch:
    """Test library scanning and metadata matching."""

    @pytest.mark.asyncio
    async def test_scan_library_for_media(self, db_session: AsyncSession, tmp_path):
        """Test scanning library for media files."""
        service = LibraryService(db_session)

        # Create library
        library_path = tmp_path / "movies"
        library_path.mkdir()
        (library_path / "movie1.mp4").write_bytes(b"1")
        (library_path / "movie2.mp4").write_bytes(b"2")
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="Test Library",
                type="MOVIES",
                plugin_id="movies",
                path=str(library_path),
            )

        # Scan library
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            discovered = await service.scan_library_for_media(library.guid)

        assert len(discovered) == 2
        assert discovered[0]["path"] == f"{library_path}/movie1.mp4"
        assert discovered[1]["path"] == f"{library_path}/movie2.mp4"

    @pytest.mark.asyncio
    async def test_scan_library_not_found(self, db_session: AsyncSession):
        """Test scanning non-existent library."""
        service = LibraryService(db_session)

        with pytest.raises(ValueError, match="Library not found"):
            await service.scan_library_for_media(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_match_media_with_metadata(self, db_session: AsyncSession):
        """Test matching media file with metadata."""
        service = LibraryService(db_session)

        # Create library
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            library = await service.create_library(
                name="Test Library",
                type="MOVIES",
                plugin_id="movies",
                path="/data/movies",
            )

        # Match media
        with patch.object(service, "get_plugin", return_value=MockPlugin("MOVIES")):
            metadata = await service.match_media_with_metadata(
                library.guid,
                {"path": "/data/movies/movie.mp4"},
            )

        assert metadata is not None
        assert metadata["title"] == "Test Movie"
        assert metadata["external_id"] == "12345"


class TestMediaReleases:
    """Test media release operations."""

    @pytest.mark.asyncio
    async def test_create_media_release(self, db_session: AsyncSession):
        """Test creating a media release."""
        service = LibraryService(db_session)

        media_item = await service.create_media_item(
            title="Test Movie",
            media_type=MediaType.MOVIES,
        )

        release = await service.create_media_release(
            media_item.guid,
            title="Test Movie 1080p BluRay",
            quality="1080p",
            size=5000000,
        )

        assert release.media_item_guid == media_item.guid
        assert release.title == "Test Movie 1080p BluRay"
        assert release.quality == "1080p"
        assert release.size == 5000000


class TestAvailabilityStatus:
    """Test availability status operations."""

    @pytest.mark.asyncio
    async def test_update_availability_status(self, db_session: AsyncSession):
        """Test updating availability status."""
        service = LibraryService(db_session)

        media_item = await service.create_media_item(
            title="Test Movie",
            media_type=MediaType.MOVIES,
        )

        updated = await service.update_availability_status(
            media_item.guid,
            AvailabilityStatus.AVAILABLE,
        )

        assert updated is not None
        assert updated.availability_status == AvailabilityStatus.AVAILABLE
