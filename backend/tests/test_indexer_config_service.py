"""Tests for IndexerService (indexer configuration CRUD)."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.indexer import Indexer
from pyrate.schemas.indexer import IndexerCreate, IndexerUpdate
from pyrate.services.indexer_config import IndexerService


@pytest_asyncio.fixture
async def indexer_service(db_session: AsyncSession) -> IndexerService:
    """Create an IndexerService instance."""
    return IndexerService(db_session)


@pytest_asyncio.fixture
async def sample_indexer(indexer_service: IndexerService) -> Indexer:
    """Create a sample indexer for testing."""
    data = IndexerCreate(
        label="NZBgeek",
        host="https://api.nzbgeek.info",
        api_key="test-api-key-123",
        ssl=True,
        verify_ssl=True,
        type="newznab",
    )
    created = await indexer_service.create(data)
    db_indexer = await indexer_service.get_model_by_id(created.guid)
    assert db_indexer is not None
    return db_indexer


class TestIndexerCRUD:
    """Tests for basic CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_indexer(self, indexer_service: IndexerService):
        """Test creating a new indexer."""
        data = IndexerCreate(
            label="NZBgeek",
            host="https://api.nzbgeek.info",
            api_key="test-api-key-123",
            ssl=True,
            verify_ssl=True,
            type="newznab",
        )
        result = await indexer_service.create(data)

        assert result is not None
        assert result.guid is not None
        assert result.label == "NZBgeek"
        assert result.host == "https://api.nzbgeek.info"
        assert result.api_key_configured is True
        assert result.ssl is True
        assert result.verify_ssl is True
        assert result.type == "newznab"
        db_indexer = await indexer_service.get_model_by_id(result.guid)
        assert db_indexer is not None
        assert db_indexer.api_key == "test-api-key-123"

    @pytest.mark.asyncio
    async def test_create_indexer_no_ssl(self, indexer_service: IndexerService):
        """Test creating an indexer without SSL."""
        data = IndexerCreate(
            label="Local Indexer",
            host="http://localhost:5060",
            api_key="local-key",
            ssl=False,
            verify_ssl=False,
            type="newznab",
        )
        result = await indexer_service.create(data)

        assert result.ssl is False
        assert result.verify_ssl is False

    @pytest.mark.asyncio
    async def test_get_all_indexers(self, indexer_service: IndexerService):
        """Test getting all indexers."""
        # Create multiple indexers
        for i in range(3):
            data = IndexerCreate(
                label=f"Indexer {i}",
                host=f"https://indexer{i}.example.com",
                api_key=f"key-{i}",
                ssl=True,
                verify_ssl=True,
                type="newznab",
            )
            await indexer_service.create(data)

        result = await indexer_service.get_all()
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_get_all_empty(self, indexer_service: IndexerService):
        """Test getting all indexers when none exist."""
        result = await indexer_service.get_all()
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_by_id(
        self, indexer_service: IndexerService, sample_indexer: Indexer
    ):
        """Test getting an indexer by its GUID."""
        result = await indexer_service.get_by_id(sample_indexer.guid)

        assert result is not None
        assert result.guid == sample_indexer.guid
        assert result.label == "NZBgeek"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, indexer_service: IndexerService):
        """Test getting an indexer by a non-existent GUID."""
        result = await indexer_service.get_by_id(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_update_indexer(
        self, indexer_service: IndexerService, sample_indexer: Indexer
    ):
        """Test updating an indexer."""
        update_data = IndexerUpdate(
            label="Updated NZBgeek",
            host="https://new-api.nzbgeek.info",
            api_key="new-api-key-456",
            ssl=False,
            verify_ssl=False,
            type="torznab",
        )
        result = await indexer_service.update(sample_indexer, update_data)

        assert result.label == "Updated NZBgeek"
        assert result.host == "https://new-api.nzbgeek.info"
        assert result.api_key_configured is True
        assert result.ssl is False
        assert result.type == "torznab"
        db_indexer = await indexer_service.get_model_by_id(sample_indexer.guid)
        assert db_indexer is not None
        assert db_indexer.api_key == "new-api-key-456"

    @pytest.mark.asyncio
    async def test_update_indexer_partial(
        self, indexer_service: IndexerService, sample_indexer: Indexer
    ):
        """Test partial update of an indexer (only changing api_key)."""
        update_data = IndexerUpdate(
            label=sample_indexer.label,
            host=sample_indexer.host,
            api_key="new-key-only",
            ssl=sample_indexer.ssl,
            verify_ssl=sample_indexer.verify_ssl,
            type=sample_indexer.type,
        )
        result = await indexer_service.update(sample_indexer, update_data)

        assert result.api_key_configured is True
        assert result.label == "NZBgeek"  # unchanged
        assert result.host == "https://api.nzbgeek.info"  # unchanged
        db_indexer = await indexer_service.get_model_by_id(sample_indexer.guid)
        assert db_indexer is not None
        assert db_indexer.api_key == "new-key-only"

    @pytest.mark.asyncio
    async def test_delete_indexer(
        self, indexer_service: IndexerService, sample_indexer: Indexer
    ):
        """Test deleting an indexer."""
        indexer_guid = sample_indexer.guid
        await indexer_service.delete(sample_indexer)

        # Verify it's gone
        result = await indexer_service.get_by_id(indexer_guid)
        assert result is None

    @pytest.mark.asyncio
    async def test_create_multiple_types(self, indexer_service: IndexerService):
        """Test creating indexers of different types."""
        newznab = IndexerCreate(
            label="Usenet Indexer",
            host="https://usenet.example.com",
            api_key="usenet-key",
            ssl=True,
            verify_ssl=True,
            type="newznab",
        )
        torznab = IndexerCreate(
            label="Torrent Indexer",
            host="https://torrent.example.com",
            api_key="torrent-key",
            ssl=True,
            verify_ssl=True,
            type="torznab",
        )

        r1 = await indexer_service.create(newznab)
        r2 = await indexer_service.create(torznab)

        assert r1.type == "newznab"
        assert r2.type == "torznab"

        all_indexers = await indexer_service.get_all()
        assert len(all_indexers) == 2
