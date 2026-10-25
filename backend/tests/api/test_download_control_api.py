"""Tests for the queue-level download control (/api/downloads/overview, /control/*)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.downloader import Downloader
from streamarr.services.downloader import DownloaderService


class StubClient:
    """Minimal downloader client that records the queue calls."""

    def __init__(self, *, paused: bool = False, limit: int | None = None):
        self.paused = paused
        self.limit = limit
        self.calls: list[str] = []
        self.closed = False
        self.jobs = [
            {
                "id": "job-1",
                "name": "Some.Release.1080p",
                "status": "downloading",
                "progress": 42.5,
                "speed_bps": 3_000_000,
                "downloaded_bytes": 400_000_000,
                "total_bytes": 1_000_000_000,
            },
            {
                "id": "job-2",
                "name": "Other.Release.2160p",
                "status": "queued",
                "progress": 0,
                "speed_bps": 0,
                "downloaded_bytes": 0,
                "total_bytes": 2_000_000_000,
            },
        ]

    async def get_control(self):
        return {"paused": self.paused, "speed_limit_kbps": self.limit}

    async def get_downloads(self):
        return list(self.jobs)

    async def pause_queue(self):
        self.calls.append("pause")
        self.paused = True

    async def resume_queue(self):
        self.calls.append("resume")
        self.paused = False

    async def set_speedlimit(self, limit):
        self.calls.append(f"limit:{limit}")
        self.limit = limit

    async def close(self):
        self.closed = True


@pytest.fixture
async def stub_downloader(db_session: AsyncSession, monkeypatch):
    """One configured usenet downloader plus its stub client."""
    downloader = Downloader(
        guid=uuid.uuid4(),
        label="Streamarr Usenet",
        host="http://usenet:3000",
        api_key=None,
        type="usenet_downloader",
        ssl=False,
        verify_ssl=True,
    )
    db_session.add(downloader)
    await db_session.commit()

    stub = StubClient()
    # get_client is a staticmethod on the service.
    monkeypatch.setattr(
        DownloaderService, "get_client", staticmethod(lambda _downloader: stub)
    )
    return stub


class TestDownloadOverview:
    async def test_overview_reports_rate_and_jobs(
        self, client: AsyncClient, admin_headers, stub_downloader
    ):
        resp = await client.get("/api/downloads/overview", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()

        # Aggregate rate counts only the downloading job.
        assert data["speed_bps"] == 3_000_000
        assert data["paused"] is False
        assert len(data["jobs"]) == 2
        assert data["jobs"][0]["status"] == "downloading"
        assert data["jobs"][0]["speed_bps"] == 3_000_000
        assert data["downloaders"][0]["reachable"] is True
        assert data["downloaders"][0]["label"] == "Streamarr Usenet"
        # The stub client must be closed again, otherwise the HTTP session leaks.
        assert stub_downloader.closed is True

    async def test_overview_survives_an_unreachable_downloader(
        self, client: AsyncClient, admin_headers, db_session: AsyncSession, monkeypatch
    ):
        db_session.add(
            Downloader(
                guid=uuid.uuid4(),
                label="Broken",
                host="http://nowhere",
                api_key="x",
                type="sabnzbd",
                ssl=False,
                verify_ssl=True,
            )
        )
        await db_session.commit()

        class Broken:
            async def get_control(self):
                raise RuntimeError("connection refused")

            async def get_downloads(self):
                raise RuntimeError("connection refused")

            async def close(self):
                pass

        monkeypatch.setattr(
            DownloaderService, "get_client", staticmethod(lambda _d: Broken())
        )
        resp = await client.get("/api/downloads/overview", headers=admin_headers)

        assert resp.status_code == 200
        entry = resp.json()["downloaders"][0]
        assert entry["reachable"] is False
        assert "connection refused" in entry["error"]


class TestQueueControl:
    async def test_pause_and_resume_all(
        self, client: AsyncClient, admin_headers, stub_downloader
    ):
        resp = await client.post(
            "/api/downloads/control/pause", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["downloaders"][0]["ok"] is True
        assert stub_downloader.calls == ["pause"]
        assert stub_downloader.paused is True

        resp = await client.post(
            "/api/downloads/control/resume", headers=admin_headers
        )
        assert resp.status_code == 200
        assert stub_downloader.calls == ["pause", "resume"]
        assert stub_downloader.paused is False

    async def test_speed_limit_is_applied_and_cleared(
        self, client: AsyncClient, admin_headers, stub_downloader
    ):
        resp = await client.post(
            "/api/downloads/control/speedlimit",
            headers=admin_headers,
            json={"kbps": 5000},
        )
        assert resp.status_code == 200
        assert resp.json()["speed_limit_kbps"] == 5000
        assert stub_downloader.limit == 5000

        # 0 clears the cap instead of meaning "0 bytes per second".
        resp = await client.post(
            "/api/downloads/control/speedlimit",
            headers=admin_headers,
            json={"kbps": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["speed_limit_kbps"] is None
        assert stub_downloader.limit is None

    async def test_speed_limit_is_admin_only(self, client: AsyncClient, user_headers):
        resp = await client.post(
            "/api/downloads/control/speedlimit", headers=user_headers, json={"kbps": 1}
        )
        assert resp.status_code in (401, 403)
