"""Tests for downloads API endpoints (/api/downloads/*)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.downloader import Downloader
from streamarr.models.downloads import Download
from streamarr.models.media import MediaItem, MediaRelease, MediaReleaseLink, MediaType
from streamarr.models.user import User

from .conftest import auth_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _create_downloader(db_session: AsyncSession) -> Downloader:
    """Create a minimal downloader to satisfy foreign key constraints."""
    dl = Downloader(
        guid=uuid.uuid4(),
        host="http://localhost:8080",
        api_key="test-key",
        type="sabnzbd",
        label="Test DL",
        ssl=False,
        verify_ssl=True,
    )
    db_session.add(dl)
    await db_session.commit()
    await db_session.refresh(dl)
    return dl


async def _create_download(db_session: AsyncSession, downloader_id: uuid.UUID, **kwargs) -> Download:
    dl = Download(
        guid=kwargs.get("guid", uuid.uuid4()),
        title=kwargs.get("title", "Test.Movie.2024.1080p.WEB-DL"),
        type=kwargs.get("type", "nzb"),
        status=kwargs.get("status", "downloading"),
        progress=kwargs.get("progress", 50.0),
        downloader_id=downloader_id,
        user_guid=kwargs.get("user_guid"),
        media_release_link_guid=kwargs.get("media_release_link_guid"),
    )
    db_session.add(dl)
    await db_session.commit()
    await db_session.refresh(dl)
    return dl


async def _create_movie_with_release_link(db_session: AsyncSession) -> tuple[MediaItem, MediaReleaseLink]:
    """Create a movie → release → link chain."""
    movie = MediaItem(title="Test Movie", media_type=MediaType.MOVIES)
    db_session.add(movie)
    await db_session.flush()

    release = MediaRelease(
        media_item_guid=movie.guid,
        title="Test.Movie.2024.1080p.WEB-DL",
        size=1_000_000,
    )
    db_session.add(release)
    await db_session.flush()

    link = MediaReleaseLink(
        media_release_guid=release.guid,
        link="https://example.com/nzb/12345",
        link_type="nzb",
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)
    await db_session.refresh(movie)
    return movie, link


async def _create_episode_with_release_link(
    db_session: AsyncSession,
) -> tuple[MediaItem, MediaItem, MediaItem, MediaReleaseLink]:
    """Create show → season → episode → release → link chain."""
    show = MediaItem(title="Breaking Bad", media_type=MediaType.SHOWS)
    db_session.add(show)
    await db_session.flush()

    season = MediaItem(
        title="Season 1",
        media_type=MediaType.SHOWS,
        parent_guid=show.guid,
        sequence_number=1,
    )
    db_session.add(season)
    await db_session.flush()

    episode = MediaItem(
        title="Pilot",
        media_type=MediaType.SHOWS,
        parent_guid=season.guid,
        sequence_number=1,
    )
    db_session.add(episode)
    await db_session.flush()

    release = MediaRelease(
        media_item_guid=episode.guid,
        title="Breaking.Bad.S01E01.720p",
        size=500_000,
    )
    db_session.add(release)
    await db_session.flush()

    link = MediaReleaseLink(
        media_release_guid=release.guid,
        link="https://example.com/nzb/11111",
        link_type="nzb",
    )
    db_session.add(link)
    await db_session.commit()
    for obj in (show, season, episode, link):
        await db_session.refresh(obj)
    return show, season, episode, link


# ---------------------------------------------------------------------------
# GET /api/downloads
# ---------------------------------------------------------------------------
class TestListDownloads:
    async def test_list_empty(self, client: AsyncClient, admin_headers):
        resp = await client.get("/api/downloads", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_downloads(self, client: AsyncClient, db_session, admin_headers):
        downloader = await _create_downloader(db_session)
        await _create_download(db_session, downloader.guid, title="Movie.A.2024")
        await _create_download(db_session, downloader.guid, title="Movie.B.2024")

        resp = await client.get("/api/downloads", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_list_downloads_has_expected_fields(self, client: AsyncClient, db_session, admin_headers):
        downloader = await _create_downloader(db_session)
        await _create_download(db_session, downloader.guid, title="Test.Movie", status="completed", progress=100.0)

        resp = await client.get("/api/downloads", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        item = data[0]
        assert "guid" in item
        assert "title" in item
        assert "display_title" in item
        assert "type" in item
        assert "status" in item

    async def test_list_downloads_regular_user_forbidden(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/downloads", headers=user_headers)
        assert resp.status_code == 403

    async def test_list_downloads_filter_by_user_guid(
        self, client: AsyncClient, db_session, test_user, test_superuser, admin_headers
    ):
        """Filter downloads by user_guid query parameter."""
        downloader = await _create_downloader(db_session)
        await _create_download(
            db_session, downloader.guid, title="UserDL", user_guid=test_user.guid
        )
        await _create_download(
            db_session, downloader.guid, title="AdminDL", user_guid=test_superuser.guid
        )

        resp = await client.get(
            f"/api/downloads?user_guid={test_user.guid}", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        # Only user's downloads should appear
        assert all(d["user_guid"] == str(test_user.guid) for d in data)

    async def test_list_downloads_with_movie_release_link(
        self, client: AsyncClient, db_session, admin_headers
    ):
        """Downloads linked to a movie show the movie title as display_title."""
        downloader = await _create_downloader(db_session)
        movie, link = await _create_movie_with_release_link(db_session)
        await _create_download(
            db_session,
            downloader.guid,
            title="Test.Movie.2024.1080p.WEB-DL",
            media_release_link_guid=link.guid,
        )

        resp = await client.get("/api/downloads", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["media_item_guid"] == str(movie.guid)
        assert data[0]["media_title"] == "Test Movie"
        assert data[0]["display_title"] == "Test Movie"

    async def test_list_downloads_with_episode_release_link(
        self, client: AsyncClient, db_session, admin_headers
    ):
        """Downloads linked to an episode show formatted S01E01 display_title."""
        downloader = await _create_downloader(db_session)
        show, season, episode, link = await _create_episode_with_release_link(db_session)
        await _create_download(
            db_session,
            downloader.guid,
            title="Breaking.Bad.S01E01.720p",
            media_release_link_guid=link.guid,
        )

        resp = await client.get("/api/downloads", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        assert item["show_title"] == "Breaking Bad"
        assert item["season_number"] == 1
        assert item["episode_number"] == 1
        assert "S01E01" in item["display_title"]

    async def test_list_downloads_with_started_by_user(
        self, client: AsyncClient, db_session, test_user, admin_headers
    ):
        """Downloads with user_guid show started_by_name."""
        downloader = await _create_downloader(db_session)
        await _create_download(
            db_session,
            downloader.guid,
            title="UserStarted",
            user_guid=test_user.guid,
        )

        resp = await client.get("/api/downloads", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["started_by_name"] is not None

    async def test_list_downloads_navigation_exception_handled(
        self, client: AsyncClient, admin_headers, test_superuser
    ):
        """If release-link navigation raises any exception the original title is kept."""
        from datetime import datetime as dt
        from unittest.mock import AsyncMock, MagicMock

        from streamarr.database import get_db_session
        from streamarr.web import app

        # Create a media_release_link whose guid conversion raises → triggers except block
        class _BrokenGuid:
            def __str__(self):
                raise RuntimeError("cannot serialize guid")

        mock_link = MagicMock()
        mock_link.release.media_item.guid = _BrokenGuid()

        mock_dl = MagicMock()
        mock_dl.media_release_link = mock_link
        mock_dl.title = "Fallback.Title"
        mock_dl.type = "nzb"
        mock_dl.status = "done"
        mock_dl.progress = 100.0
        mock_dl.speed_bps = 0
        mock_dl.error_reason = None
        mock_dl.downloader = None
        mock_dl.user_guid = None
        mock_dl.started_by = None
        mock_dl.created_at = dt.now()
        mock_dl.guid = uuid.uuid4()

        async def _fake_db():
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_dl]
            mock_session.execute = AsyncMock(return_value=mock_result)
            yield mock_session

        original = app.dependency_overrides.get(get_db_session)
        app.dependency_overrides[get_db_session] = _fake_db
        try:
            resp = await client.get("/api/downloads", headers=admin_headers)
        finally:
            if original is not None:
                app.dependency_overrides[get_db_session] = original
            else:
                app.dependency_overrides.pop(get_db_session, None)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Fallback.Title"
        assert data[0]["display_title"] == "Fallback.Title"


# ---------------------------------------------------------------------------
# DELETE /api/downloads/{download_id}
# ---------------------------------------------------------------------------
class TestDeleteDownload:
    async def test_delete_download(self, client: AsyncClient, db_session, admin_headers):
        downloader = await _create_downloader(db_session)
        dl = await _create_download(db_session, downloader.guid)

        resp = await client.delete(f"/api/downloads/{dl.guid}", headers=admin_headers)
        assert resp.status_code == 200
        assert "deleted" in resp.json()["detail"].lower() or "detail" in resp.json()

    async def test_delete_download_not_found(self, client: AsyncClient, admin_headers):
        fake = uuid.uuid4()
        resp = await client.delete(f"/api/downloads/{fake}", headers=admin_headers)
        assert resp.status_code == 404

    async def test_delete_download_regular_user_forbidden(self, client: AsyncClient, db_session, user_headers):
        downloader = await _create_downloader(db_session)
        dl = await _create_download(db_session, downloader.guid)

        resp = await client.delete(f"/api/downloads/{dl.guid}", headers=user_headers)
        assert resp.status_code == 403
