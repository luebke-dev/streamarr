"""Tests for the GenreService."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.genre import Genre
from streamarr.schemas.genre import GenreCreate, GenreUpdate
from streamarr.services.genre import GenreService


class TestGenreCRUD:
    """Test basic CRUD operations for genres."""

    @pytest.mark.asyncio
    async def test_create_genre(self, db_session: AsyncSession):
        """Test creating a genre."""
        service = GenreService(db_session)

        genre_data = GenreCreate(id=28, name="Action")
        genre = await service.create(genre_data)

        assert genre is not None
        assert genre.id == 28
        assert genre.name == "Action"

    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session: AsyncSession):
        """Test getting a genre by ID."""
        service = GenreService(db_session)
        genre_data = GenreCreate(id=12, name="Adventure")
        await service.create(genre_data)

        genre = await service.get_by_id(12)

        assert genre is not None
        assert genre.name == "Adventure"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session: AsyncSession):
        """Test getting a non-existent genre."""
        service = GenreService(db_session)

        genre = await service.get_by_id(99999)

        assert genre is None

    @pytest.mark.asyncio
    async def test_get_by_name(self, db_session: AsyncSession):
        """Test getting a genre by name."""
        service = GenreService(db_session)
        genre_data = GenreCreate(id=35, name="Comedy")
        await service.create(genre_data)

        genre = await service.get_by_name("Comedy")

        assert genre is not None
        assert genre.id == 35

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(self, db_session: AsyncSession):
        """Test getting a non-existent genre by name."""
        service = GenreService(db_session)

        genre = await service.get_by_name("Nonexistent")

        assert genre is None

    @pytest.mark.asyncio
    async def test_get_all(self, db_session: AsyncSession):
        """Test getting all genres, ordered by name."""
        service = GenreService(db_session)

        await service.create(GenreCreate(id=28, name="Action"))
        await service.create(GenreCreate(id=35, name="Comedy"))
        await service.create(GenreCreate(id=18, name="Drama"))

        genres = await service.get_all()

        assert len(genres) == 3
        # Should be ordered by name
        assert genres[0].name == "Action"
        assert genres[1].name == "Comedy"
        assert genres[2].name == "Drama"

    @pytest.mark.asyncio
    async def test_get_all_empty(self, db_session: AsyncSession):
        """Test getting all genres when none exist."""
        service = GenreService(db_session)

        genres = await service.get_all()

        assert len(genres) == 0

    @pytest.mark.asyncio
    async def test_update_genre(self, db_session: AsyncSession):
        """Test updating a genre."""
        service = GenreService(db_session)
        genre_data = GenreCreate(id=28, name="Action")
        genre = await service.create(genre_data)

        updated = await service.update(genre, GenreUpdate(name="Action & Adventure"))

        assert updated.name == "Action & Adventure"
        assert updated.id == 28

    @pytest.mark.asyncio
    async def test_update_genre_partial(self, db_session: AsyncSession):
        """Test partial update (no fields set)."""
        service = GenreService(db_session)
        genre_data = GenreCreate(id=28, name="Action")
        genre = await service.create(genre_data)

        updated = await service.update(genre, GenreUpdate())

        assert updated.name == "Action"

    @pytest.mark.asyncio
    async def test_delete_genre(self, db_session: AsyncSession):
        """Test deleting a genre."""
        service = GenreService(db_session)
        genre_data = GenreCreate(id=28, name="Action")
        genre = await service.create(genre_data)

        await service.delete(genre)

        deleted = await service.get_by_id(28)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_create_multiple_genres(self, db_session: AsyncSession):
        """Test creating multiple genres."""
        service = GenreService(db_session)
        genre_names = [
            (28, "Action"),
            (12, "Adventure"),
            (16, "Animation"),
            (35, "Comedy"),
            (80, "Crime"),
            (99, "Documentary"),
            (18, "Drama"),
            (14, "Fantasy"),
            (27, "Horror"),
            (10749, "Romance"),
        ]

        for genre_id, name in genre_names:
            await service.create(GenreCreate(id=genre_id, name=name))

        genres = await service.get_all()
        assert len(genres) == 10
