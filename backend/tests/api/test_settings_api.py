"""Tests for the Settings API endpoints (/api/settings/*)."""

import pytest
from httpx import AsyncClient

from streamarr.models.user import User

from .conftest import auth_headers


# ============================================================================
# LIBRARIES SETTINGS
# ============================================================================


class TestLibrariesSettings:
    async def test_get_libraries_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/libraries")
        assert resp.status_code == 401

    async def test_get_libraries_as_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/libraries", headers=user_headers)
        assert resp.status_code == 200

    async def test_get_libraries_as_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/libraries", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "movies_enabled" in data
        assert "shows_enabled" in data

    async def test_update_libraries_unauthenticated(self, client: AsyncClient):
        resp = await client.put(
            "/api/settings/libraries", json={"movies_enabled": True}
        )
        assert resp.status_code == 401

    async def test_update_libraries_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.put(
            "/api/settings/libraries",
            headers=user_headers,
            json={"movies_enabled": True},
        )
        assert resp.status_code == 403

    async def test_update_libraries_as_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/libraries",
            headers=admin_headers,
            json={"movies_enabled": True, "shows_enabled": True},
        )
        assert resp.status_code == 200

    async def test_update_and_verify_libraries(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        await client.put(
            "/api/settings/libraries",
            headers=admin_headers,
            json={
                "movies": False,
                "shows": True,
                "music": False,
                "books": True,
                "games": False,
            },
        )
        resp = await client.get("/api/settings/libraries", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["movies_enabled"] is False
        assert data["shows_enabled"] is True
        assert data["books_enabled"] is True
        assert data["games_enabled"] is False


# ============================================================================
# MOVIE SETTINGS
# ============================================================================


class TestMovieSettings:
    async def test_get_movies_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/movies")
        assert resp.status_code == 401

    async def test_get_movies_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/movies", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_movies_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/movies", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "library_path" in data
        assert "enable_library" in data

    async def test_update_movies_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/movies",
            headers=admin_headers,
            json={"library_path": "/media/movies"},
        )
        assert resp.status_code == 200

    async def test_update_movies_enable_library(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/movies",
            headers=admin_headers,
            json={"enable_library": True, "library_path": "/data/movies"},
        )
        assert resp.status_code == 200

    async def test_update_movies_on_demand(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/movies",
            headers=admin_headers,
            json={"enable_on_demand_downloads": True},
        )
        assert resp.status_code == 200


# ============================================================================
# SHOW SETTINGS
# ============================================================================


class TestShowSettings:
    async def test_get_shows_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/shows")
        assert resp.status_code == 401

    async def test_get_shows_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/shows", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_shows_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/shows", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "hide_season_zero" in data

    async def test_update_shows_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/shows",
            headers=admin_headers,
            json={"hide_season_zero": False, "library_path": "/media/shows"},
        )
        assert resp.status_code == 200

    async def test_update_shows_prefetch(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/shows",
            headers=admin_headers,
            json={"enable_prefetch_downloads": True},
        )
        assert resp.status_code == 200


# ============================================================================
# MUSIC SETTINGS
# ============================================================================


class TestMusicSettings:
    async def test_get_music_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/music")
        assert resp.status_code == 401

    async def test_get_music_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/music", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_music_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/music", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "library_path" in data
        assert "enable_library" in data

    async def test_update_music_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/music",
            headers=admin_headers,
            json={"library_path": "/media/music", "enable_library": True},
        )
        assert resp.status_code == 200


# ============================================================================
# BOOKS SETTINGS
# ============================================================================


class TestBooksSettings:
    async def test_get_books_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/books")
        assert resp.status_code == 401

    async def test_get_books_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/books", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_books_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/books", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "library_path" in data
        assert "enable_library" in data

    async def test_update_books_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/books",
            headers=admin_headers,
            json={"library_path": "/media/books", "enable_library": True},
        )
        assert resp.status_code == 200


# ============================================================================
# GAMES SETTINGS
# ============================================================================


class TestGamesSettings:
    async def test_get_games_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/games")
        assert resp.status_code == 401

    async def test_get_games_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/games", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_games_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/games", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "library_path" in data
        assert "enable_library" in data

    async def test_update_games_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/games",
            headers=admin_headers,
            json={"library_path": "/media/games", "enable_library": False},
        )
        assert resp.status_code == 200


# ============================================================================
# SUBSCRIPTION SETTINGS
# ============================================================================


class TestSubscriptionSettings:
    async def test_get_subscription_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/subscriptions")
        assert resp.status_code == 401

    async def test_get_subscription_as_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/subscriptions", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "subscriptions_enabled" in data

    async def test_get_subscription_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/subscriptions", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "subscriptions_enabled" in data

    async def test_update_subscription_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.put(
            "/api/settings/subscriptions",
            headers=user_headers,
            json={"subscriptions_enabled": True},
        )
        assert resp.status_code == 403

    async def test_update_subscription_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/subscriptions",
            headers=admin_headers,
            json={"subscriptions_enabled": True},
        )
        assert resp.status_code == 200

    async def test_update_and_verify_subscription(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        await client.put(
            "/api/settings/subscriptions",
            headers=admin_headers,
            json={"subscriptions_enabled": False},
        )
        resp = await client.get("/api/settings/subscriptions", headers=admin_headers)
        assert resp.json()["subscriptions_enabled"] is False


# ============================================================================
# INVITE SETTINGS
# ============================================================================


class TestInviteSettings:
    async def test_get_invite_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/invites")
        assert resp.status_code == 401

    async def test_get_invite_as_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/invites", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "invites_enabled" in data

    async def test_get_invite_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/invites", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "invites_enabled" in data

    async def test_update_invite_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.put(
            "/api/settings/invites",
            headers=user_headers,
            json={"invites_enabled": True},
        )
        assert resp.status_code == 403

    async def test_update_invite_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/invites",
            headers=admin_headers,
            json={"invites_enabled": True},
        )
        assert resp.status_code == 200

    async def test_update_and_verify_invite(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        await client.put(
            "/api/settings/invites",
            headers=admin_headers,
            json={"invites_enabled": False},
        )
        resp = await client.get("/api/settings/invites", headers=admin_headers)
        assert resp.json()["invites_enabled"] is False


# ============================================================================
# TRANSCODING SETTINGS
# ============================================================================


class TestTranscodingSettings:
    async def test_get_transcoding_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/transcoding")
        assert resp.status_code == 401

    async def test_get_transcoding_as_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/transcoding", headers=user_headers)
        assert resp.status_code == 200

    async def test_get_transcoding_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/transcoding", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "max_resolution" in data
        assert "hardware_acceleration" in data
        assert "allowed_video_codecs" in data

    async def test_update_transcoding_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.put(
            "/api/settings/transcoding",
            headers=user_headers,
            json={"enabled": True},
        )
        assert resp.status_code == 403

    async def test_update_transcoding_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/transcoding",
            headers=admin_headers,
            json={"enabled": True, "max_resolution": "1080p"},
        )
        assert resp.status_code == 200

    async def test_update_transcoding_codecs(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/transcoding",
            headers=admin_headers,
            json={
                "allowed_video_codecs": ["h264", "h265"],
                "allowed_audio_codecs": ["aac", "opus"],
            },
        )
        assert resp.status_code == 200


# ============================================================================
# SYSTEM SETTINGS
# ============================================================================


class TestSystemSettings:
    async def test_get_system_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/system")
        assert resp.status_code == 401

    async def test_get_system_as_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/system", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "site_name" in data
        assert "locale" in data

    async def test_update_system_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.put(
            "/api/settings/system",
            headers=user_headers,
            json={"site_name": "Test"},
        )
        assert resp.status_code == 403

    async def test_update_system_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/system",
            headers=admin_headers,
            json={"site_name": "My Media Server", "locale": "en-US"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["site_name"] == "My Media Server"
        assert data["locale"] == "en-US"

    async def test_update_and_verify_system(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        await client.put(
            "/api/settings/system",
            headers=admin_headers,
            json={"site_name": "Custom Name"},
        )
        resp = await client.get("/api/settings/system", headers=admin_headers)
        assert resp.json()["site_name"] == "Custom Name"


# ============================================================================
# NAMING SETTINGS
# ============================================================================


class TestShowNamingSettings:
    async def test_get_show_naming_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/naming/shows")
        assert resp.status_code == 401

    async def test_get_show_naming_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/naming/shows", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_show_naming_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/naming/shows", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "series_folder" in data
        assert "season_folder" in data
        assert "episode_file" in data
        assert "replace_illegal_characters" in data

    async def test_update_show_naming_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/naming/shows",
            headers=admin_headers,
            json={
                "series_folder": "{series_title} ({series_year})",
                "season_folder": "Season {season:02d}",
            },
        )
        assert resp.status_code == 200


class TestMovieNamingSettings:
    async def test_get_movie_naming_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/naming/movies")
        assert resp.status_code == 401

    async def test_get_movie_naming_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/naming/movies", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_movie_naming_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/naming/movies", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "folder" in data
        assert "file" in data
        assert "replace_illegal_characters" in data

    async def test_update_movie_naming_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/naming/movies",
            headers=admin_headers,
            json={
                "folder": "{title} ({year})",
                "file": "{title} [{quality}]",
            },
        )
        assert resp.status_code == 200


# ============================================================================
# STORAGE SETTINGS
# ============================================================================


class TestAutomationSettings:
    async def test_get_and_update_library_scan_interval(
        self, client: AsyncClient, admin_headers
    ):
        get_response = await client.get(
            "/api/settings/automation", headers=admin_headers
        )
        assert get_response.status_code == 200
        assert get_response.json()["library_scan_interval_hours"] == 12

        update_response = await client.put(
            "/api/settings/automation",
            headers=admin_headers,
            json={"library_scan_interval_hours": 6},
        )
        assert update_response.status_code == 200
        assert update_response.json()["library_scan_interval_hours"] == 6

    async def test_rejects_invalid_library_scan_interval(
        self, client: AsyncClient, admin_headers
    ):
        response = await client.put(
            "/api/settings/automation",
            headers=admin_headers,
            json={"library_scan_interval_hours": 0},
        )
        assert response.status_code == 422


class TestStorageSettings:
    async def test_get_storage_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/settings/storage")
        assert resp.status_code == 401

    async def test_get_storage_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/settings/storage", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_storage_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/settings/storage", headers=admin_headers)
        assert resp.status_code == 200

    async def test_update_storage_forbidden_for_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.put(
            "/api/settings/storage",
            headers=user_headers,
            json={"temp_max_age_hours": 4.0},
        )
        assert resp.status_code == 403

    async def test_update_storage_settings(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            "/api/settings/storage",
            headers=admin_headers,
            json={
                "temp_max_age_hours": 6.0,
                "download_record_max_age_days": 60,
                "cleanup_orphaned_files": True,
            },
        )
        assert resp.status_code == 200


# ============================================================================
# UNKNOWN LIBRARY TYPE
# ============================================================================


class TestUnknownLibraryType:
    async def test_get_unknown_library_type(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """GET /settings/{library_type} returns 404 for unknown type."""
        resp = await client.get(
            "/api/settings/nonexistent_library", headers=admin_headers
        )
        assert resp.status_code == 404
        assert "Unknown library type" in resp.json()["detail"]

    async def test_update_unknown_library_type(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """PUT /settings/{library_type} returns 404 for unknown type."""
        resp = await client.put(
            "/api/settings/nonexistent_library",
            headers=admin_headers,
            json={"some_setting": "value"},
        )
        assert resp.status_code == 404
        assert "Unknown library type" in resp.json()["detail"]


# ============================================================================
# NAMING SETTINGS - UNKNOWN LIBRARY TYPE
# ============================================================================


class TestNamingUnknownLibraryType:
    async def test_get_naming_unknown_library(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """GET /settings/naming/{library_type} returns 404 for unknown type."""
        resp = await client.get(
            "/api/settings/naming/nonexistent", headers=admin_headers
        )
        assert resp.status_code == 404
        assert "Unknown library type" in resp.json()["detail"]

    async def test_update_naming_unknown_library(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """PUT /settings/naming/{library_type} returns 404 for unknown type."""
        resp = await client.put(
            "/api/settings/naming/nonexistent",
            headers=admin_headers,
            json={"folder": "test"},
        )
        assert resp.status_code == 404
        assert "Unknown library type" in resp.json()["detail"]

    async def test_preview_naming_unknown_library(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """POST /settings/naming/{library_type}/preview returns 404 for unknown type."""
        resp = await client.post(
            "/api/settings/naming/nonexistent/preview",
            headers=admin_headers,
            json={"title": "Test"},
        )
        assert resp.status_code == 404
        assert "Unknown library type" in resp.json()["detail"]


# ============================================================================
# STORAGE OVERVIEW & CLEANUP
# ============================================================================


class TestStorageOverviewAndCleanup:
    async def test_get_storage_overview(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """GET /settings/storage/overview returns disk usage."""
        resp = await client.get(
            "/api/settings/storage/overview", headers=admin_headers
        )
        assert resp.status_code == 200

    async def test_get_storage_overview_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        """Regular user cannot get storage overview."""
        resp = await client.get(
            "/api/settings/storage/overview", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_trigger_cleanup(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """POST /settings/storage/cleanup triggers manual cleanup."""
        resp = await client.post(
            "/api/settings/storage/cleanup", headers=admin_headers
        )
        assert resp.status_code == 200

    async def test_trigger_cleanup_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        """Regular user cannot trigger cleanup."""
        resp = await client.post(
            "/api/settings/storage/cleanup", headers=user_headers
        )
        assert resp.status_code == 403


# ============================================================================
# NAMING PREVIEW
# ============================================================================


class TestNamingPreview:
    async def test_preview_movie_naming(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """POST /settings/naming/movies/preview returns preview."""
        resp = await client.post(
            "/api/settings/naming/movies/preview",
            headers=admin_headers,
            json={"title": "Test Movie", "year": 2024},
        )
        assert resp.status_code == 200

    async def test_preview_shows_naming(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """POST /settings/naming/shows/preview returns preview."""
        resp = await client.post(
            "/api/settings/naming/shows/preview",
            headers=admin_headers,
            json={"series_title": "Test Show", "season": 1, "episode": 1},
        )
        assert resp.status_code == 200
