"""Tests for the MediaService."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.library import Library
from pyrate.models.media import (
    AvailabilityStatus,
    MediaExternalId,
    MediaFile,
    MediaItem,
    MediaRelease,
    MediaType,
)
from pyrate.services.media import MediaService


@pytest.fixture
async def test_library(db_session: AsyncSession) -> Library:
    """Create a test library."""
    now = datetime.now(UTC)
    library = Library(
        guid=uuid.uuid4(),
        name="Test Movie Library",
        type="MOVIES",
        plugin_id="test_library_plugin",
        path="/data/movies",
        created_at=now,
        updated_at=now,
    )
    db_session.add(library)
    await db_session.commit()
    await db_session.refresh(library)
    return library


class TestMediaServiceCreate:
    """Test media item creation operations."""

    @pytest.mark.asyncio
    async def test_create_media_item_basic(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test creating a basic media item."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        assert media_item.guid is not None
        assert media_item.media_type == MediaType.MOVIES
        assert media_item.title == "Test Movie"
        assert media_item.parent_guid is None
        assert media_item.availability_status == AvailabilityStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_create_media_item_with_metadata(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test creating a media item with full metadata."""
        service = MediaService(db_session)
        release_date = datetime(2024, 1, 15)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Awesome Movie",
            original_title="Le Film Génial",
            description="A great movie about testing",
            tagline="Test or die trying",
            library_guid=test_library.guid,
            release_date=release_date,
            poster_path="/posters/awesome-movie.jpg",
            backdrop_path="/backdrops/awesome-movie.jpg",
            availability_status=AvailabilityStatus.AVAILABLE,
        )

        assert media_item.title == "Awesome Movie"
        assert media_item.original_title == "Le Film Génial"
        assert media_item.description == "A great movie about testing"
        assert media_item.tagline == "Test or die trying"
        assert media_item.release_date == release_date
        assert media_item.poster_path == "/posters/awesome-movie.jpg"
        assert media_item.backdrop_path == "/backdrops/awesome-movie.jpg"
        assert media_item.availability_status == AvailabilityStatus.AVAILABLE

    @pytest.mark.asyncio
    async def test_create_hierarchical_media(self, db_session: AsyncSession):
        """Test creating hierarchical media (show -> season -> episode)."""
        service = MediaService(db_session)

        # Create show
        show = await service.create_media_item(
            media_type=MediaType.SHOWS,
            title="Test Show",
        )

        # Create season
        season = await service.create_media_item(
            media_type=MediaType.SHOWS,
            title="Season 1",
            parent_guid=show.guid,
            sequence_number=1,
        )

        # Create episode
        episode = await service.create_media_item(
            media_type=MediaType.SHOWS,
            title="Pilot",
            parent_guid=season.guid,
            sequence_number=1,
        )

        assert season.parent_guid == show.guid
        assert season.sequence_number == 1
        assert episode.parent_guid == season.guid
        assert episode.sequence_number == 1

    @pytest.mark.asyncio
    async def test_create_media_file(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test creating a media file."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        media_file = await service.create_media_file(
            media_item_guid=media_item.guid,
            file_path="/data/movies/test-movie.mkv",
            file_size=1024 * 1024 * 1024,  # 1GB
            duration=7200,  # 2 hours
            width=1920,
            height=1080,
        )

        assert media_file.guid is not None
        assert media_file.media_item_guid == media_item.guid
        assert media_file.file_path == "/data/movies/test-movie.mkv"
        assert media_file.file_size == 1024 * 1024 * 1024
        assert media_file.duration == 7200
        assert media_file.width == 1920
        assert media_file.height == 1080

    @pytest.mark.asyncio
    async def test_create_media_release(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test creating a media release."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        release = await service.create_media_release(
            media_item_guid=media_item.guid,
            title="Test.Movie.2024.1080p.BluRay",
            quality="1080p",
            size=5 * 1024 * 1024 * 1024,  # 5GB
        )

        assert release.guid is not None
        assert release.media_item_guid == media_item.guid
        assert release.title == "Test.Movie.2024.1080p.BluRay"
        assert release.quality == "1080p"

    @pytest.mark.asyncio
    async def test_add_external_id(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test adding external IDs."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        # Add TMDB ID
        tmdb_id = await service.add_external_id(
            media_item_guid=media_item.guid,
            provider="tmdb",
            external_id="12345",
        )

        # Add IMDb ID
        imdb_id = await service.add_external_id(
            media_item_guid=media_item.guid,
            provider="imdb",
            external_id="tt1234567",
        )

        assert tmdb_id.provider == "tmdb"
        assert tmdb_id.external_id == "12345"
        assert imdb_id.provider == "imdb"
        assert imdb_id.external_id == "tt1234567"


class TestMediaServiceRead:
    """Test media item read operations."""

    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session: AsyncSession, test_library: Library):
        """Test getting media item by ID."""
        service = MediaService(db_session)

        created = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        retrieved = await service.get_by_id(created.guid)

        assert retrieved is not None
        assert retrieved.guid == created.guid
        assert retrieved.title == "Test Movie"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session: AsyncSession):
        """Test getting non-existent media item."""
        service = MediaService(db_session)

        result = await service.get_by_id(uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_id_with_files(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test getting media item with files loaded."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        await service.create_media_file(
            media_item_guid=media_item.guid,
            file_path="/data/movies/test1.mkv",
        )
        await service.create_media_file(
            media_item_guid=media_item.guid,
            file_path="/data/movies/test2.mkv",
        )

        retrieved = await service.get_by_id(media_item.guid, load_files=True)

        assert retrieved is not None
        assert len(retrieved.files) == 2

    @pytest.mark.asyncio
    async def test_get_by_id_with_releases(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test getting media item with releases loaded."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        await service.create_media_release(
            media_item_guid=media_item.guid,
            title="Release 1",
        )
        await service.create_media_release(
            media_item_guid=media_item.guid,
            title="Release 2",
        )

        retrieved = await service.get_by_id(media_item.guid, load_releases=True)

        assert retrieved is not None
        assert len(retrieved.releases) == 2

    @pytest.mark.asyncio
    async def test_get_by_id_with_external_ids(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test getting media item with external IDs loaded."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        await service.add_external_id(
            media_item_guid=media_item.guid,
            provider="tmdb",
            external_id="12345",
        )
        await service.add_external_id(
            media_item_guid=media_item.guid,
            provider="imdb",
            external_id="tt1234567",
        )

        retrieved = await service.get_by_id(media_item.guid, load_external_ids=True)

        assert retrieved is not None
        assert len(retrieved.external_ids) == 2

    @pytest.mark.asyncio
    async def test_get_by_external_id(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test getting media item by external ID."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        await service.add_external_id(
            media_item_guid=media_item.guid,
            provider="tmdb",
            external_id="12345",
        )

        retrieved = await service.get_by_external_id(
            provider="tmdb",
            external_id="12345",
        )

        assert retrieved is not None
        assert retrieved.guid == media_item.guid

    @pytest.mark.asyncio
    async def test_get_by_external_id_with_type_filter(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test getting media item by external ID with type filter."""
        service = MediaService(db_session)

        movie = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        await service.add_external_id(
            media_item_guid=movie.guid,
            provider="tmdb",
            external_id="12345",
        )

        # Should find with correct type
        found = await service.get_by_external_id(
            provider="tmdb",
            external_id="12345",
            media_type=MediaType.MOVIES,
        )
        assert found is not None

        # Should not find with wrong type
        not_found = await service.get_by_external_id(
            provider="tmdb",
            external_id="12345",
            media_type=MediaType.GAMES,
        )
        assert not_found is None

    @pytest.mark.asyncio
    async def test_list_by_type(self, db_session: AsyncSession, test_library: Library):
        """Test listing media items by type."""
        service = MediaService(db_session)

        # Create movies
        await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Movie 1",
            library_guid=test_library.guid,
        )
        await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Movie 2",
            library_guid=test_library.guid,
        )

        # Create a game (should not be in movies list)
        await service.create_media_item(
            media_type=MediaType.GAMES,
            title="Game 1",
        )

        movies = await service.list_by_type(MediaType.MOVIES)

        assert len(movies) == 2
        assert all(m.media_type == MediaType.MOVIES for m in movies)

    @pytest.mark.asyncio
    async def test_list_by_type_returns_all_of_type(
        self, db_session: AsyncSession
    ):
        """Test listing media items by type returns all items of that type."""
        service = MediaService(db_session)

        await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Movie 1",
        )
        await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Movie 2",
        )

        movies = await service.list_by_type(MediaType.MOVIES)

        assert len(movies) == 2

    @pytest.mark.asyncio
    async def test_list_by_type_with_pagination(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test listing media items with pagination."""
        service = MediaService(db_session)

        # Create 5 movies
        for i in range(5):
            await service.create_media_item(
                media_type=MediaType.MOVIES,
                title=f"Movie {i}",
                library_guid=test_library.guid,
            )

        # Get first page
        page1 = await service.list_by_type(
            MediaType.MOVIES,
            limit=2,
            offset=0,
        )

        # Get second page
        page2 = await service.list_by_type(
            MediaType.MOVIES,
            limit=2,
            offset=2,
        )

        assert len(page1) == 2
        assert len(page2) == 2
        # Ensure different items
        page1_guids = {m.guid for m in page1}
        page2_guids = {m.guid for m in page2}
        assert page1_guids.isdisjoint(page2_guids)

    @pytest.mark.asyncio
    async def test_search(self, db_session: AsyncSession, test_library: Library):
        """Test searching media items."""
        service = MediaService(db_session)

        await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="The Amazing Spider-Man",
            library_guid=test_library.guid,
        )
        await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Spider-Man: Homecoming",
            library_guid=test_library.guid,
        )
        await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Batman Begins",
            library_guid=test_library.guid,
        )

        results = await service.search("spider")

        assert len(results) == 2
        assert all("spider" in m.title.lower() for m in results)

    @pytest.mark.asyncio
    async def test_search_with_type_filter(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test searching with media type filter."""
        service = MediaService(db_session)

        await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Spider-Man",
            library_guid=test_library.guid,
        )
        await service.create_media_item(
            media_type=MediaType.GAMES,
            title="Spider-Man PS4",
        )

        movie_results = await service.search("spider", media_type=MediaType.MOVIES)
        game_results = await service.search("spider", media_type=MediaType.GAMES)

        assert len(movie_results) == 1
        assert movie_results[0].media_type == MediaType.MOVIES
        assert len(game_results) == 1
        assert game_results[0].media_type == MediaType.GAMES

    @pytest.mark.asyncio
    async def test_get_children(self, db_session: AsyncSession):
        """Test getting child media items."""
        service = MediaService(db_session)

        # Create show with episodes
        show = await service.create_media_item(
            media_type=MediaType.SHOWS,
            title="Test Show",
        )

        season = await service.create_media_item(
            media_type=MediaType.SHOWS,
            title="Season 1",
            parent_guid=show.guid,
            sequence_number=1,
        )

        episode1 = await service.create_media_item(
            media_type=MediaType.SHOWS,
            title="Episode 1",
            parent_guid=season.guid,
            sequence_number=1,
        )
        episode2 = await service.create_media_item(
            media_type=MediaType.SHOWS,
            title="Episode 2",
            parent_guid=season.guid,
            sequence_number=2,
        )

        children = await service.get_children(season.guid)

        assert len(children) == 2
        assert children[0].sequence_number == 1
        assert children[1].sequence_number == 2

    @pytest.mark.asyncio
    async def test_count_by_type(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test counting media items by type."""
        service = MediaService(db_session)

        # Create 3 movies
        for i in range(3):
            await service.create_media_item(
                media_type=MediaType.MOVIES,
                title=f"Movie {i}",
                library_guid=test_library.guid,
            )

        # Create 2 games
        for i in range(2):
            await service.create_media_item(
                media_type=MediaType.GAMES,
                title=f"Game {i}",
            )

        movie_count = await service.count_by_type(MediaType.MOVIES)
        game_count = await service.count_by_type(MediaType.GAMES)

        assert movie_count == 3
        assert game_count == 2


class TestMediaServiceUpdate:
    """Test media item update operations."""

    @pytest.mark.asyncio
    async def test_update_media_item(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test updating media item fields."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Original Title",
            library_guid=test_library.guid,
        )

        updated = await service.update(
            media_item.guid,
            title="Updated Title",
            description="New description",
        )

        assert updated is not None
        assert updated.title == "Updated Title"
        assert updated.description == "New description"

    @pytest.mark.asyncio
    async def test_update_nonexistent_item(self, db_session: AsyncSession):
        """Test updating non-existent media item."""
        service = MediaService(db_session)

        result = await service.update(
            uuid.uuid4(),
            title="Updated Title",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_update_availability_status(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test updating availability status."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        updated = await service.update_availability_status(
            media_item.guid,
            AvailabilityStatus.AVAILABLE,
        )

        assert updated is not None
        assert updated.availability_status == AvailabilityStatus.AVAILABLE

    @pytest.mark.asyncio
    async def test_mark_metadata_updated(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test marking metadata as updated."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        assert media_item.last_metadata_updated_at is None

        updated = await service.mark_metadata_updated(media_item.guid)

        assert updated is not None
        assert updated.last_metadata_updated_at is not None

    @pytest.mark.asyncio
    async def test_mark_searched(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test marking media as searched."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        assert media_item.last_searched_at is None

        updated = await service.mark_searched(media_item.guid)

        assert updated is not None
        assert updated.last_searched_at is not None


class TestMediaServiceDelete:
    """Test media item delete operations."""

    @pytest.mark.asyncio
    async def test_delete_media_item(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test deleting a media item."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        success = await service.delete(media_item.guid)

        assert success is True

        # Verify deletion
        retrieved = await service.get_by_id(media_item.guid)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_item(self, db_session: AsyncSession):
        """Test deleting non-existent media item."""
        service = MediaService(db_session)

        success = await service.delete(uuid.uuid4())

        assert success is False

    @pytest.mark.asyncio
    async def test_delete_cascades_to_files(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test that deleting media item cascades to files."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        media_file = await service.create_media_file(
            media_item_guid=media_item.guid,
            file_path="/data/test.mkv",
        )

        await service.delete(media_item.guid)

        # Verify file is also deleted using SQLAlchemy 2.0 API
        from sqlalchemy import select
        result = await db_session.execute(
            select(MediaFile).where(MediaFile.guid == media_file.guid)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_file(self, db_session: AsyncSession, test_library: Library):
        """Test deleting a media file."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        media_file = await service.create_media_file(
            media_item_guid=media_item.guid,
            file_path="/data/test.mkv",
        )

        success = await service.delete_file(media_file.guid)

        assert success is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self, db_session: AsyncSession):
        """Test deleting non-existent file."""
        service = MediaService(db_session)

        success = await service.delete_file(uuid.uuid4())

        assert success is False

    @pytest.mark.asyncio
    async def test_delete_release(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test deleting a media release."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        release = await service.create_media_release(
            media_item_guid=media_item.guid,
            title="Test.Release",
        )

        success = await service.delete_release(release.guid)

        assert success is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_release(self, db_session: AsyncSession):
        """Test deleting non-existent release."""
        service = MediaService(db_session)

        success = await service.delete_release(uuid.uuid4())

        assert success is False


class TestMediaServiceHelpers:
    """Test helper methods."""

    @pytest.mark.asyncio
    async def test_get_top_level_items(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test getting top-level items only."""
        service = MediaService(db_session)

        # Create show with season
        show = await service.create_media_item(
            media_type=MediaType.SHOWS,
            title="Test Show",
            library_guid=test_library.guid,
        )

        season = await service.create_media_item(
            media_type=MediaType.SHOWS,
            title="Season 1",
            parent_guid=show.guid,
            library_guid=test_library.guid,
        )

        # Get top-level items
        top_level = await service.get_top_level_items(MediaType.SHOWS)

        assert len(top_level) == 1
        assert top_level[0].guid == show.guid

    @pytest.mark.asyncio
    async def test_get_with_files(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test getting media with files loaded."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        await service.create_media_file(
            media_item_guid=media_item.guid,
            file_path="/data/test.mkv",
        )

        result = await service.get_with_files(media_item.guid)

        assert result is not None
        assert len(result.files) == 1

    @pytest.mark.asyncio
    async def test_get_with_releases(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test getting media with releases loaded."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        await service.create_media_release(
            media_item_guid=media_item.guid,
            title="Test.Release",
        )

        result = await service.get_with_releases(media_item.guid)

        assert result is not None
        assert len(result.releases) == 1

    @pytest.mark.asyncio
    async def test_has_files_true(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test checking if media has files - true case."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        await service.create_media_file(
            media_item_guid=media_item.guid,
            file_path="/data/test.mkv",
        )

        has_files = await service.has_files(media_item.guid)

        assert has_files is True

    @pytest.mark.asyncio
    async def test_has_files_false(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test checking if media has files - false case."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        has_files = await service.has_files(media_item.guid)

        assert has_files is False

    @pytest.mark.asyncio
    async def test_has_releases_true(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test checking if media has releases - true case."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        await service.create_media_release(
            media_item_guid=media_item.guid,
            title="Test.Release",
        )

        has_releases = await service.has_releases(media_item.guid)

        assert has_releases is True

    @pytest.mark.asyncio
    async def test_has_releases_false(
        self, db_session: AsyncSession, test_library: Library
    ):
        """Test checking if media has releases - false case."""
        service = MediaService(db_session)

        media_item = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
            library_guid=test_library.guid,
        )

        has_releases = await service.has_releases(media_item.guid)

        assert has_releases is False


class TestMediaServiceMultipleMediaTypes:
    """Test operations across multiple media types."""

    @pytest.mark.asyncio
    async def test_multiple_media_types(self, db_session: AsyncSession):
        """Test working with multiple media types simultaneously."""
        service = MediaService(db_session)

        # Create different media types
        movie = await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Test Movie",
        )
        game = await service.create_media_item(
            media_type=MediaType.GAMES,
            title="Test Game",
        )
        show = await service.create_media_item(
            media_type=MediaType.SHOWS,
            title="Test Show",
        )

        # Verify each type count
        movie_count = await service.count_by_type(MediaType.MOVIES)
        game_count = await service.count_by_type(MediaType.GAMES)
        show_count = await service.count_by_type(MediaType.SHOWS)

        assert movie_count == 1
        assert game_count == 1
        assert show_count == 1

    @pytest.mark.asyncio
    async def test_search_across_types(self, db_session: AsyncSession):
        """Test searching across different media types."""
        service = MediaService(db_session)

        await service.create_media_item(
            media_type=MediaType.MOVIES,
            title="Marvel Movie",
        )
        await service.create_media_item(
            media_type=MediaType.GAMES,
            title="Marvel Game",
        )

        # Search without type filter - should find both
        results = await service.search("marvel")

        assert len(results) == 2
        types = {r.media_type for r in results}
        assert MediaType.MOVIES in types
        assert MediaType.GAMES in types
