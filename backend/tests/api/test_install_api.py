"""Tests for the install API endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from pyrate.auth.jwt_handler import jwt_handler
from pyrate.models import User
from pyrate.models.library import Library
from pyrate.services.settings import SettingsService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# GET /api/install/status
# ---------------------------------------------------------------------------
class TestGetInstallationStatus:
    async def test_status_not_installed(self, client: AsyncClient):
        """Returns installed=False and has_users=False when no users exist."""
        resp = await client.get("/api/install/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["installed"] is False
        assert data["has_users"] is False
        assert data["site_name"] is None

    async def test_status_installed(self, client: AsyncClient, db_session):
        """Returns installed=True and has_users=True when at least one user exists."""
        user = User(
            guid=uuid.uuid4(),
            email="installed@example.com",
            first_name="Admin",
            last_name="User",
            is_active=True,
            is_superuser=True,
            hashed_password="hashed",
        )
        db_session.add(user)
        await db_session.commit()

        resp = await client.get("/api/install/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["installed"] is True
        assert data["has_users"] is True


class TestInstallWizardStatus:
    async def test_wizard_status_before_setup(self, client: AsyncClient):
        resp = await client.get("/api/install/wizard")

        assert resp.status_code == 200
        data = resp.json()
        assert data["installed"] is False
        assert data["current_step"] == "admin_user"
        steps = {step["id"]: step for step in data["steps"]}
        assert steps["admin_user"]["complete"] is False
        assert steps["libraries"]["complete"] is False

    async def test_wizard_status_reports_configured_steps(
        self, client: AsyncClient, db_session
    ):
        user = User(
            guid=uuid.uuid4(),
            email="installed@example.com",
            first_name="Admin",
            last_name="User",
            is_active=True,
            is_superuser=True,
            hashed_password="hashed",
        )
        library = Library(
            guid=uuid.uuid4(),
            name="Movies",
            type="MOVIES",
            plugin_id="movies",
            path="/data/movies",
            enabled=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(user)
        db_session.add(library)
        await db_session.commit()

        resp = await client.get("/api/install/wizard")

        assert resp.status_code == 200
        data = resp.json()
        steps = {step["id"]: step for step in data["steps"]}
        assert data["installed"] is True
        assert steps["admin_user"]["complete"] is True
        assert steps["libraries"]["complete"] is True
        assert steps["libraries"]["details"]["library_count"] == 1


class TestInstallWizardRoutes:
    async def test_wizard_configuration_before_setup_is_public(
        self, client: AsyncClient
    ):
        resp = await client.get("/api/install/wizard/configuration")

        assert resp.status_code == 200
        data = resp.json()
        assert data["server_name"] == "pyrate.media"
        assert data["ui_culture"] == "de-DE"

    async def test_wizard_configuration_updates_existing_settings(
        self, client: AsyncClient, db_session
    ):
        payload = {
            "server_name": "New Server",
            "ui_culture": "en-US",
            "metadata_country_code": "US",
            "preferred_metadata_language": "en",
        }

        resp = await client.post("/api/install/wizard/configuration", json=payload)

        assert resp.status_code == 204
        service = SettingsService(db_session)
        assert await service.get("system.site_name") == "New Server"
        assert await service.get("system.locale") == "en-US"
        assert await service.get("metadata.country_code") == "US"
        assert await service.get("metadata.preferred_language") == "en"

    async def test_wizard_routes_require_admin_after_setup(
        self, client: AsyncClient, test_superuser: User, test_user: User, user_headers
    ):
        unauthenticated = await client.get("/api/install/wizard/configuration")
        forbidden = await client.get(
            "/api/install/wizard/configuration", headers=user_headers
        )

        assert unauthenticated.status_code == 401
        assert forbidden.status_code == 403

    async def test_wizard_configuration_allows_admin_after_setup(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get(
            "/api/install/wizard/configuration", headers=admin_headers
        )

        assert resp.status_code == 200
        assert resp.json()["server_name"] == "pyrate.media"

    async def test_wizard_remote_access_updates_existing_network_setting(
        self, client: AsyncClient, test_superuser: User, admin_headers, db_session
    ):
        resp = await client.post(
            "/api/install/wizard/remote-access",
            json={"enable_remote_access": False},
            headers=admin_headers,
        )

        assert resp.status_code == 204
        assert await SettingsService(db_session).get("network.remote_access_enabled") is False

    async def test_wizard_user_reads_first_user(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/install/wizard/user", headers=admin_headers)

        assert resp.status_code == 200
        assert resp.json()["name"] == test_superuser.first_name
        assert resp.json()["password"] is None

    async def test_wizard_user_update_changes_first_user(
        self, client: AsyncClient, test_superuser: User, admin_headers, db_session
    ):
        resp = await client.post(
            "/api/install/wizard/user",
            json={"name": "Captain", "password": "NewPassword123!"},
            headers=admin_headers,
        )

        assert resp.status_code == 204
        await db_session.refresh(test_superuser)
        assert test_superuser.first_name == "Captain"
        assert test_superuser.preferred_username == "Captain"
        assert jwt_handler.verify_password(
            "NewPassword123!", test_superuser.hashed_password
        )

    async def test_wizard_user_update_requires_password(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/install/wizard/user",
            json={"name": "Captain", "password": ""},
            headers=admin_headers,
        )

        assert resp.status_code == 400

    async def test_wizard_complete_marks_wizard_completed(
        self, client: AsyncClient, test_superuser: User, admin_headers, db_session
    ):
        resp = await client.post("/api/install/wizard/complete", headers=admin_headers)

        assert resp.status_code == 204
        assert await SettingsService(db_session).get(
            "system.install_wizard_completed"
        ) is True


# ---------------------------------------------------------------------------
# POST /api/install/setup
# ---------------------------------------------------------------------------
class TestInitialSetup:
    _VALID_PAYLOAD = {
        "email": "admin@example.com",
        "password": "Admin123!",
        "first_name": "Admin",
        "last_name": "User",
        "site_name": "My Media Server",
        "locale": "en-US",
    }

    async def test_setup_success(self, client: AsyncClient):
        """Creates the first admin user and returns success response."""
        resp = await client.post("/api/install/setup", json=self._VALID_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["user_email"] == "admin@example.com"
        assert data["site_name"] == "My Media Server"

    async def test_setup_success_default_site_name(self, client: AsyncClient):
        """When site_name is omitted, defaults to 'pyrate.media'."""
        payload = {
            "email": "admin@example.com",
            "password": "Admin123!",
            "first_name": "Admin",
            "last_name": "User",
        }
        resp = await client.post("/api/install/setup", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["site_name"] == "pyrate.media"

    async def test_setup_already_installed(
        self, client: AsyncClient, db_session
    ):
        """Returns 403 when a user already exists (system already set up)."""
        user = User(
            guid=uuid.uuid4(),
            email="existing@example.com",
            first_name="Existing",
            last_name="Admin",
            is_active=True,
            is_superuser=True,
            hashed_password="hashed",
        )
        db_session.add(user)
        await db_session.commit()

        resp = await client.post("/api/install/setup", json=self._VALID_PAYLOAD)
        assert resp.status_code == 403

    async def test_setup_password_too_short(self, client: AsyncClient):
        """Returns 422 when the password is shorter than 8 characters."""
        payload = {**self._VALID_PAYLOAD, "password": "Ab1"}
        resp = await client.post("/api/install/setup", json=payload)
        assert resp.status_code == 422

    async def test_setup_password_no_uppercase(self, client: AsyncClient):
        """Returns 422 when the password has no uppercase letter."""
        payload = {**self._VALID_PAYLOAD, "password": "admin123!"}
        resp = await client.post("/api/install/setup", json=payload)
        assert resp.status_code == 422

    async def test_setup_password_no_lowercase(self, client: AsyncClient):
        """Returns 422 when the password has no lowercase letter."""
        payload = {**self._VALID_PAYLOAD, "password": "ADMIN123!"}
        resp = await client.post("/api/install/setup", json=payload)
        assert resp.status_code == 422

    async def test_setup_password_no_digit(self, client: AsyncClient):
        """Returns 422 when the password has no digit."""
        payload = {**self._VALID_PAYLOAD, "password": "AdminPass!"}
        resp = await client.post("/api/install/setup", json=payload)
        assert resp.status_code == 422

    async def test_setup_invalid_email(self, client: AsyncClient):
        """Returns 422 when the email is not a valid address."""
        payload = {**self._VALID_PAYLOAD, "email": "not-an-email"}
        resp = await client.post("/api/install/setup", json=payload)
        assert resp.status_code == 422

    async def test_setup_email_already_in_use(self, client: AsyncClient):
        """Returns 400 when the email is already taken (mocked duplicate check)."""
        from pyrate.database import get_db_session
        from pyrate.web import app

        mock_db = AsyncMock()

        # First execute: count query → 0 users
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        # Second execute: email-in-use query → existing user found
        email_result = MagicMock()
        email_result.scalar_one_or_none.return_value = MagicMock()

        mock_db.execute = AsyncMock(side_effect=[count_result, email_result])

        async def _mock_db():
            yield mock_db

        original = app.dependency_overrides.get(get_db_session)
        app.dependency_overrides[get_db_session] = _mock_db
        try:
            resp = await client.post("/api/install/setup", json=self._VALID_PAYLOAD)
            assert resp.status_code == 400
        finally:
            if original is not None:
                app.dependency_overrides[get_db_session] = original
            else:
                app.dependency_overrides.pop(get_db_session, None)

    async def test_setup_db_exception_returns_500(self, client: AsyncClient):
        """Returns 500 when an unexpected exception occurs during DB operations."""
        from pyrate.api.v1.install import jwt_handler

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                jwt_handler,
                "get_password_hash",
                lambda v: (_ for _ in ()).throw(Exception("DB failure")),
            )
            resp = await client.post("/api/install/setup", json=self._VALID_PAYLOAD)
        assert resp.status_code == 500
