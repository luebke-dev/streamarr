"""Tests for the DownloaderService."""

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.downloader import Downloader
from streamarr.downloaders.deluge import Deluge
from streamarr.downloaders.sabnzbd import Sabnzbd
from streamarr.downloaders.spotdl import Spotdl
from streamarr.schemas.downloader import DownloaderCreate, DownloaderUpdate
from streamarr.services.downloader import DownloaderService
from streamarr.utils.http import reset_circuit_breakers


class TestDownloaderCRUD:
    """Test basic CRUD operations for downloaders."""

    @pytest.mark.asyncio
    async def test_create_downloader(self, db_session: AsyncSession):
        """Test creating a downloader."""
        service = DownloaderService(db_session)

        downloader_data = DownloaderCreate(
            label="My SABnzbd",
            host="http://localhost:8080",
            api_key="test-api-key-123",
            type="sabnzbd",
            ssl=False,
            verify_ssl=True,
        )
        downloader = await service.create(downloader_data)

        assert downloader is not None
        assert downloader.label == "My SABnzbd"
        assert downloader.host == "http://localhost:8080"
        assert downloader.api_key_configured is True
        assert downloader.type == "sabnzbd"
        assert downloader.ssl is False
        assert downloader.verify_ssl is True
        raw_downloader = await service.get_model_by_id(downloader.guid)
        assert raw_downloader is not None
        assert raw_downloader.api_key == "test-api-key-123"

    @pytest.mark.asyncio
    async def test_create_deluge_downloader(self, db_session: AsyncSession):
        """Test creating a Deluge downloader."""
        service = DownloaderService(db_session)

        downloader_data = DownloaderCreate(
            label="My Deluge",
            host="http://localhost:8112",
            api_key="deluge-key",
            type="deluge",
        )
        downloader = await service.create(downloader_data)

        assert downloader.type == "deluge"
        assert downloader.label == "My Deluge"

    @pytest.mark.asyncio
    async def test_get_all(self, db_session: AsyncSession):
        """Test getting all downloaders."""
        service = DownloaderService(db_session)

        await service.create(
            DownloaderCreate(
                label="SABnzbd",
                host="http://sab:8080",
                api_key="key1",
                type="sabnzbd",
            )
        )
        await service.create(
            DownloaderCreate(
                label="Deluge",
                host="http://deluge:8112",
                api_key="key2",
                type="deluge",
            )
        )

        downloaders = await service.get_all()

        assert len(list(downloaders)) == 2

    @pytest.mark.asyncio
    async def test_get_all_empty(self, db_session: AsyncSession):
        """Test getting all downloaders when none exist."""
        service = DownloaderService(db_session)

        downloaders = await service.get_all()

        assert len(list(downloaders)) == 0

    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session: AsyncSession):
        """Test getting a downloader by ID."""
        service = DownloaderService(db_session)
        created = await service.create(
            DownloaderCreate(
                label="Test",
                host="http://test:8080",
                api_key="key",
                type="sabnzbd",
            )
        )

        result = await service.get_by_id(created.guid)

        assert result is not None
        assert result.label == "Test"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session: AsyncSession):
        """Test getting a non-existent downloader."""
        service = DownloaderService(db_session)

        result = await service.get_by_id(uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_update_downloader(self, db_session: AsyncSession):
        """Test updating a downloader."""
        service = DownloaderService(db_session)
        created = await service.create(
            DownloaderCreate(
                label="Original",
                host="http://old:8080",
                api_key="old-key",
                type="sabnzbd",
            )
        )

        raw_downloader = await service.get_model_by_id(created.guid)
        assert raw_downloader is not None

        updated = await service.update(
            raw_downloader,
            DownloaderUpdate(
                label="Updated",
                host="http://new:8080",
                api_key="new-key",
                type="sabnzbd",
            ),
        )

        assert updated.label == "Updated"
        assert updated.host == "http://new:8080"
        assert updated.api_key_configured is True
        persisted = await service.get_model_by_id(created.guid)
        assert persisted is not None
        assert persisted.api_key == "new-key"

    @pytest.mark.asyncio
    async def test_delete_downloader(self, db_session: AsyncSession):
        """Test deleting a downloader."""
        service = DownloaderService(db_session)
        created = await service.create(
            DownloaderCreate(
                label="Delete Me",
                host="http://delete:8080",
                api_key="key",
                type="sabnzbd",
            )
        )

        raw_downloader = await service.get_model_by_id(created.guid)
        assert raw_downloader is not None

        await service.delete(raw_downloader)

        result = await service.get_by_id(created.guid)
        assert result is None


class TestDownloaderClientFactory:
    """Test the get_client static method."""

    def test_get_sabnzbd_client(self):
        """Test creating a SABnzbd client."""
        downloader = Downloader(
            label="SABnzbd",
            host="http://sab:8080",
            api_key="sab-key",
            type="sabnzbd",
        )

        client = DownloaderService.get_client(downloader)

        assert isinstance(client, Sabnzbd)

    def test_get_deluge_client(self):
        """Test creating a Deluge client."""
        downloader = Downloader(
            label="Deluge",
            host="http://deluge:8112",
            api_key="deluge-key",
            type="deluge",
        )

        client = DownloaderService.get_client(downloader)

        assert isinstance(client, Deluge)

    def test_get_client_case_insensitive(self):
        """Test that client type matching is case-insensitive."""
        downloader = Downloader(
            label="SABnzbd",
            host="http://sab:8080",
            api_key="key",
            type="SABnzbd",
        )

        client = DownloaderService.get_client(downloader)

        assert isinstance(client, Sabnzbd)

    def test_get_spotdl_client(self):
        """Test creating a spotdl client."""
        downloader = Downloader(
            label="spotdl",
            host="http://spotdl:3000",
            api_key="",
            type="spotdl",
        )

        client = DownloaderService.get_client(downloader)

        assert isinstance(client, Spotdl)
        assert client.base_url == "http://spotdl:3000"

    def test_get_client_unknown_type_defaults_to_sabnzbd(self):
        """Test that unknown types default to SABnzbd."""
        downloader = Downloader(
            label="Unknown",
            host="http://unknown:8080",
            api_key="key",
            type="transmission",
        )

        client = DownloaderService.get_client(downloader)

        assert isinstance(client, Sabnzbd)


class TestDownloaderResilience:
    """Health/client requests go through the retry + circuit-breaker wrapper."""

    def setup_method(self):
        reset_circuit_breakers()

    def teardown_method(self):
        reset_circuit_breakers()

    @pytest.mark.asyncio
    async def test_health_check_retries_transient_then_ok(
        self, db_session: AsyncSession, monkeypatch
    ):
        service = DownloaderService(db_session)
        downloader = Downloader(
            label="SAB", host="http://sab:8080", api_key="k", type="sabnzbd"
        )

        calls = {"n": 0}

        async def flaky_get_downloads():
            calls["n"] += 1
            if calls["n"] < 2:
                raise httpx.ConnectError("temporarily down")
            return []

        client = AsyncMock()
        client.get_downloads = flaky_get_downloads
        client.close = AsyncMock()
        monkeypatch.setattr(service, "get_client", lambda d: client)

        # Backoff would sleep; neutralise it for the test.
        monkeypatch.setattr(
            "streamarr.utils.http._backoff_delay", lambda *a, **k: 0.0
        )

        healthy = await service.health_check(downloader)
        assert healthy is True
        assert calls["n"] == 2
        client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_reports_unhealthy_when_down(
        self, db_session: AsyncSession, monkeypatch
    ):
        service = DownloaderService(db_session)
        downloader = Downloader(
            label="SAB", host="http://dead:8080", api_key="k", type="sabnzbd"
        )

        client = AsyncMock()
        client.get_downloads = AsyncMock(side_effect=httpx.ConnectError("down"))
        client.close = AsyncMock()
        monkeypatch.setattr(service, "get_client", lambda d: client)
        monkeypatch.setattr(
            "streamarr.utils.http._backoff_delay", lambda *a, **k: 0.0
        )

        healthy = await service.health_check(downloader)
        assert healthy is False
        client.close.assert_awaited_once()
