"""Tests for infrastructure: database, websocket, plugin loader, download service, config."""

import importlib.util
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.auth.jwt_handler import jwt_handler
from streamarr.config import (
    AppSettings,
    ConnectionSettings,
    EmailConfig,
    InvitesConfig,
    LibraryConfig,
    MetadataConfig,
    OIDCConfig,
    PaymentConfig,
    TranscodingConfig,
)
from streamarr.database import DatabaseSessionManager
from streamarr.models.user import User

# ===================================================================

HAS_LEGACY_PLUGIN_LOADER = (
    importlib.util.find_spec("streamarr.plugins.loader") is not None
)


class TestDatabaseSessionManager:
    """Tests for DatabaseSessionManager."""

    @pytest.mark.asyncio
    async def test_init_sqlite(self):
        mgr = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")
        assert mgr._engine is not None
        assert mgr._sessionmaker is not None
        await mgr.close()

    @pytest.mark.asyncio
    async def test_close(self):
        mgr = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")
        await mgr.close()
        assert mgr._engine is None
        assert mgr._sessionmaker is None

    @pytest.mark.asyncio
    async def test_close_not_initialized(self):
        mgr = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")
        await mgr.close()
        with pytest.raises(Exception, match="not initialized"):
            await mgr.close()

    @pytest.mark.asyncio
    async def test_session_context_manager(self):
        mgr = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")
        async with mgr.session() as session:
            assert session is not None
        await mgr.close()

    @pytest.mark.asyncio
    async def test_session_not_initialized(self):
        mgr = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")
        await mgr.close()
        with pytest.raises(Exception, match="not initialized"):
            async with mgr.session():
                pass

    @pytest.mark.asyncio
    async def test_connect_context_manager(self):
        mgr = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")
        async with mgr.connect() as conn:
            assert conn is not None
        await mgr.close()

    @pytest.mark.asyncio
    async def test_connect_not_initialized(self):
        mgr = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")
        await mgr.close()
        with pytest.raises(Exception, match="not initialized"):
            async with mgr.connect():
                pass

    @pytest.mark.asyncio
    async def test_session_rollback_on_exception(self):
        mgr = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")
        with pytest.raises(ValueError):
            async with mgr.session() as session:
                raise ValueError("test error")
        await mgr.close()

    @pytest.mark.asyncio
    async def test_connect_rollback_on_exception(self):
        mgr = DatabaseSessionManager("sqlite+aiosqlite:///:memory:")
        with pytest.raises(ValueError):
            async with mgr.connect() as conn:
                raise ValueError("test error")
        await mgr.close()

    @pytest.mark.asyncio
    async def test_init_with_engine_kwargs(self):
        mgr = DatabaseSessionManager(
            "sqlite+aiosqlite:///:memory:", engine_kwargs={"echo": True}
        )
        assert mgr._engine is not None
        await mgr.close()

    @pytest.mark.asyncio
    async def test_init_postgres_url_sets_pool_settings(self):
        """PostgreSQL URLs should get pool settings (we just test construction)."""
        # We can't actually connect to PostgreSQL, but we can test the init logic
        # by checking that the engine is created (it won't fail until actual connect)
        mgr = DatabaseSessionManager(
            "postgresql+asyncpg://user:pass@localhost/db"
        )
        assert mgr._engine is not None
        # Clean up without awaiting dispose on a non-existent server
        mgr._engine = None
        mgr._sessionmaker = None


# ===================================================================
# api/v1/ws.py - update_device_status callback
# ===================================================================


class TestUpdateDeviceStatus:
    """Tests for the update_device_status callback in ws.py."""

    @pytest.mark.asyncio
    async def test_update_device_status_found(self, db_session, test_user):
        from streamarr.models.device import Device

        device = Device(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            device_id="dev-123",
            is_active=True,
        )
        db_session.add(device)
        await db_session.commit()

        status_data = {
            "is_playing": True,
            "media_type": "movie",
            "media_title": "Test Movie",
            "position": 100,
            "duration": 7200,
            "media_guid": str(uuid.uuid4()),
        }

        # Mock get_db_session to yield our test session
        async def mock_get_db_session():
            yield db_session

        with patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session):
            from streamarr.api.v1.ws import update_device_status

            await update_device_status(
                str(test_user.guid), "dev-123", status_data
            )

        await db_session.refresh(device)
        assert device.is_playing is True
        assert device.current_media_title == "Test Movie"
        assert device.current_playback_position == 100

    @pytest.mark.asyncio
    async def test_update_device_status_not_found(self, db_session, test_user):
        async def mock_get_db_session():
            yield db_session

        with patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session):
            from streamarr.api.v1.ws import update_device_status

            # Should not raise, just log warning
            await update_device_status(
                str(test_user.guid), "nonexistent-device", {"is_playing": False}
            )

    @pytest.mark.asyncio
    async def test_update_device_status_invalid_media_guid(self, db_session, test_user):
        from streamarr.models.device import Device

        device = Device(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            device_id="dev-456",
            is_active=True,
        )
        db_session.add(device)
        await db_session.commit()

        status_data = {
            "is_playing": False,
            "media_guid": "not-a-valid-uuid",
        }

        async def mock_get_db_session():
            yield db_session

        with patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session):
            from streamarr.api.v1.ws import update_device_status

            await update_device_status(
                str(test_user.guid), "dev-456", status_data
            )

        await db_session.refresh(device)
        assert device.current_media_guid is None

    @pytest.mark.asyncio
    async def test_update_device_status_no_media_guid(self, db_session, test_user):
        from streamarr.models.device import Device

        device = Device(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            device_id="dev-789",
            is_active=True,
        )
        db_session.add(device)
        await db_session.commit()

        status_data = {
            "is_playing": True,
            "media_guid": None,
        }

        async def mock_get_db_session():
            yield db_session

        with patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session):
            from streamarr.api.v1.ws import update_device_status

            await update_device_status(
                str(test_user.guid), "dev-789", status_data
            )

        await db_session.refresh(device)
        assert device.current_media_guid is None

    @pytest.mark.asyncio
    async def test_update_device_status_db_exception(self, db_session, test_user):
        """When db operations fail, rollback should be called."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock(side_effect=Exception("db error"))
        mock_session.rollback = AsyncMock()

        async def mock_get_db_session():
            yield mock_session

        with patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session):
            from streamarr.api.v1.ws import update_device_status

            await update_device_status(
                str(test_user.guid), "dev-error", {"is_playing": False}
            )

        mock_session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_device_status_media_guid_as_uuid(self, db_session, test_user):
        """media_guid passed as UUID object (not string)."""
        from streamarr.models.device import Device

        device = Device(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            device_id="dev-uuid-obj",
            is_active=True,
        )
        db_session.add(device)
        await db_session.commit()

        media_guid = uuid.uuid4()
        status_data = {
            "is_playing": True,
            "media_guid": media_guid,  # UUID object, not string
        }

        async def mock_get_db_session():
            yield db_session

        with patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session):
            from streamarr.api.v1.ws import update_device_status

            await update_device_status(
                str(test_user.guid), "dev-uuid-obj", status_data
            )

        await db_session.refresh(device)
        assert device.current_media_guid == media_guid


# ===================================================================
# api/v1/ws.py - websocket_endpoint
# ===================================================================


class TestWebSocketEndpoint:
    """Tests for the websocket_endpoint function."""

    @pytest.mark.asyncio
    async def test_websocket_invalid_token(self):
        from streamarr.api.v1.ws import websocket_endpoint

        mock_ws = AsyncMock()
        with patch("streamarr.api.v1.ws.jwt_handler") as mock_jwt:
            mock_jwt.verify_token.return_value = None
            await websocket_endpoint(mock_ws, token="bad-token")

        mock_ws.close.assert_called_once_with(
            code=4001, reason="Invalid or expired token"
        )

    @pytest.mark.asyncio
    async def test_websocket_wrong_token_type(self):
        from streamarr.api.v1.ws import websocket_endpoint

        mock_ws = AsyncMock()
        with patch("streamarr.api.v1.ws.jwt_handler") as mock_jwt:
            mock_jwt.verify_token.return_value = {"type": "refresh", "sub": "uid"}
            await websocket_endpoint(mock_ws, token="refresh-token")

        mock_ws.close.assert_called_once_with(
            code=4001, reason="Invalid or expired token"
        )

    @pytest.mark.asyncio
    async def test_websocket_no_sub_in_payload(self):
        from streamarr.api.v1.ws import websocket_endpoint

        mock_ws = AsyncMock()
        with patch("streamarr.api.v1.ws.jwt_handler") as mock_jwt:
            mock_jwt.verify_token.return_value = {"type": "access"}  # no sub
            await websocket_endpoint(mock_ws, token="token")

        mock_ws.close.assert_called_once_with(
            code=4001, reason="Invalid token payload"
        )

    @pytest.mark.asyncio
    async def test_websocket_user_not_found(self):
        from streamarr.api.v1.ws import websocket_endpoint

        mock_ws = AsyncMock()
        mock_db = AsyncMock()
        mock_db.get.return_value = None

        async def mock_get_db_session():
            yield mock_db

        with (
            patch("streamarr.api.v1.ws.jwt_handler") as mock_jwt,
            patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session),
        ):
            mock_jwt.verify_token.return_value = {
                "type": "access",
                "sub": str(uuid.uuid4()),
            }
            await websocket_endpoint(mock_ws, token="token")

        mock_ws.close.assert_called_once_with(
            code=4003, reason="User not found or inactive"
        )

    @pytest.mark.asyncio
    async def test_websocket_inactive_user(self):
        from streamarr.api.v1.ws import websocket_endpoint

        mock_ws = AsyncMock()
        mock_user = MagicMock()
        mock_user.is_active = False
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_user

        async def mock_get_db_session():
            yield mock_db

        with (
            patch("streamarr.api.v1.ws.jwt_handler") as mock_jwt,
            patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session),
        ):
            mock_jwt.verify_token.return_value = {
                "type": "access",
                "sub": str(uuid.uuid4()),
            }
            await websocket_endpoint(mock_ws, token="token")

        mock_ws.close.assert_called_once_with(
            code=4003, reason="User not found or inactive"
        )

    @pytest.mark.asyncio
    async def test_websocket_access_schedule_denied(self):
        from streamarr.api.v1.ws import websocket_endpoint

        mock_ws = AsyncMock()
        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.is_superuser = False
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_user
        permissions = MagicMock()
        permissions.access_schedule_active = False
        permissions.remote_access_enabled = True
        permission_service = MagicMock()
        permission_service.resolve_user_permissions = AsyncMock(return_value=permissions)

        async def mock_get_db_session():
            yield mock_db

        with (
            patch("streamarr.api.v1.ws.jwt_handler") as mock_jwt,
            patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session),
            patch("streamarr.api.v1.ws.PermissionService", return_value=permission_service),
        ):
            mock_jwt.verify_token.return_value = {
                "type": "access",
                "sub": str(uuid.uuid4()),
            }
            await websocket_endpoint(mock_ws, token="token")

        mock_ws.close.assert_called_once_with(
            code=4003, reason="Access is not allowed at this time"
        )

    @pytest.mark.asyncio
    async def test_websocket_connect_and_disconnect(self):
        from fastapi import WebSocketDisconnect

        from streamarr.api.v1.ws import websocket_endpoint

        mock_ws = AsyncMock()
        mock_ws.receive_json.side_effect = WebSocketDisconnect()

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_user
        device_lookup = MagicMock()
        device_lookup.scalar_one_or_none.return_value = "dev-1"
        mock_db.execute.return_value = device_lookup

        mock_manager = AsyncMock()
        mock_connection = AsyncMock()
        mock_manager.connect.return_value = mock_connection

        async def mock_get_db_session():
            yield mock_db

        user_id = str(uuid.uuid4())
        with (
            patch("streamarr.api.v1.ws.jwt_handler") as mock_jwt,
            patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session),
            patch("streamarr.api.v1.ws.get_websocket_manager", return_value=mock_manager),
        ):
            mock_jwt.verify_token.return_value = {
                "type": "access",
                "sub": user_id,
            }
            await websocket_endpoint(mock_ws, token="token", device_id="dev-1")

        mock_manager.connect.assert_called_once_with(mock_ws, user_id, "dev-1")
        mock_manager.disconnect.assert_called_once_with(mock_connection)

    @pytest.mark.asyncio
    async def test_websocket_handles_invalid_json(self):
        from streamarr.api.v1.ws import websocket_endpoint

        mock_ws = AsyncMock()
        # First call raises ValueError (invalid JSON), second raises disconnect
        from fastapi import WebSocketDisconnect

        mock_ws.receive_json.side_effect = [
            ValueError("bad json"),
            WebSocketDisconnect(),
        ]

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_user

        mock_connection = AsyncMock()
        mock_manager = AsyncMock()
        mock_manager.connect.return_value = mock_connection

        async def mock_get_db_session():
            yield mock_db

        with (
            patch("streamarr.api.v1.ws.jwt_handler") as mock_jwt,
            patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session),
            patch("streamarr.api.v1.ws.get_websocket_manager", return_value=mock_manager),
        ):
            mock_jwt.verify_token.return_value = {
                "type": "access",
                "sub": str(uuid.uuid4()),
            }
            await websocket_endpoint(mock_ws, token="token", device_id=None)

        mock_connection.send_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_handles_unexpected_exception(self):
        from streamarr.api.v1.ws import websocket_endpoint

        mock_ws = AsyncMock()
        mock_ws.receive_json.side_effect = RuntimeError("unexpected")

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_user

        mock_connection = AsyncMock()
        mock_manager = AsyncMock()
        mock_manager.connect.return_value = mock_connection

        async def mock_get_db_session():
            yield mock_db

        with (
            patch("streamarr.api.v1.ws.jwt_handler") as mock_jwt,
            patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session),
            patch("streamarr.api.v1.ws.get_websocket_manager", return_value=mock_manager),
        ):
            mock_jwt.verify_token.return_value = {
                "type": "access",
                "sub": str(uuid.uuid4()),
            }
            await websocket_endpoint(mock_ws, token="token", device_id=None)

        mock_manager.disconnect.assert_called_once_with(mock_connection)

    @pytest.mark.asyncio
    async def test_websocket_handles_message(self):
        from fastapi import WebSocketDisconnect

        from streamarr.api.v1.ws import websocket_endpoint

        mock_ws = AsyncMock()
        mock_ws.receive_json.side_effect = [
            {"action": "ping"},
            WebSocketDisconnect(),
        ]

        mock_user = MagicMock()
        mock_user.is_active = True
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_user

        mock_connection = AsyncMock()
        mock_manager = AsyncMock()
        mock_manager.connect.return_value = mock_connection

        async def mock_get_db_session():
            yield mock_db

        with (
            patch("streamarr.api.v1.ws.jwt_handler") as mock_jwt,
            patch("streamarr.api.v1.ws.get_db_session", mock_get_db_session),
            patch("streamarr.api.v1.ws.get_websocket_manager", return_value=mock_manager),
        ):
            mock_jwt.verify_token.return_value = {
                "type": "access",
                "sub": str(uuid.uuid4()),
            }
            await websocket_endpoint(mock_ws, token="token", device_id=None)

        mock_manager.handle_message.assert_called_once_with(
            mock_connection, {"action": "ping"}
        )


# ===================================================================
# plugins/loader.py
# ===================================================================


class TestPluginClass:
    """Tests for the Plugin class in loader.py."""

    pytestmark = pytest.mark.skipif(
        not HAS_LEGACY_PLUGIN_LOADER,
        reason="legacy streamarr.plugins.loader module has been removed",
    )

    def _make_manifest(self, **overrides):
        from streamarr.plugins.manifest import PluginManifest

        data = {
            "name": "Test Plugin",
            "domain": "test_plugin",
            "version": "1.0.0",
            "plugin_types": ["library"],
            "documentation": "https://example.com",
            "description": "A test plugin",
        }
        data.update(overrides)
        return PluginManifest(**data)

    def test_plugin_properties(self):
        from streamarr.plugins.loader import Plugin
        from streamarr.plugins.manifest import PluginType

        manifest = self._make_manifest()
        mock_class = MagicMock()

        plugin = Plugin(
            domain="test_plugin",
            manifest=manifest,
            plugin_class=mock_class,
            path=Path("/fake"),
        )

        assert plugin.name == "Test Plugin"
        assert plugin.version == "1.0.0"
        assert PluginType.LIBRARY in plugin.plugin_types

    def test_get_instance_creates_once(self):
        from streamarr.plugins.loader import Plugin

        manifest = self._make_manifest()
        mock_class = MagicMock()
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance

        plugin = Plugin(
            domain="test_plugin",
            manifest=manifest,
            plugin_class=mock_class,
            path=Path("/fake"),
        )

        with patch("streamarr.plugins.loader.get_hook_manager") as mock_hm:
            inst1 = plugin.get_instance()
            inst2 = plugin.get_instance()

        assert inst1 is inst2
        mock_class.assert_called_once()

    def test_load_translations_locale_not_in_manifest(self):
        from streamarr.plugins.loader import Plugin

        manifest = self._make_manifest(i18n={})
        plugin = Plugin(
            domain="test",
            manifest=manifest,
            plugin_class=MagicMock(),
            path=Path("/fake"),
        )
        assert plugin.load_translations("de-DE") == {}

    def test_load_translations_file_not_found(self, tmp_path):
        from streamarr.plugins.loader import Plugin

        manifest = self._make_manifest(i18n={"de-DE": "i18n/de.json"})
        plugin = Plugin(
            domain="test",
            manifest=manifest,
            plugin_class=MagicMock(),
            path=tmp_path,
        )
        assert plugin.load_translations("de-DE") == {}

    def test_load_translations_success(self, tmp_path):
        from streamarr.plugins.loader import Plugin

        i18n_dir = tmp_path / "i18n"
        i18n_dir.mkdir()
        trans_file = i18n_dir / "de.json"
        trans_file.write_text('{"hello": "Hallo"}')

        manifest = self._make_manifest(i18n={"de-DE": "i18n/de.json"})
        plugin = Plugin(
            domain="test",
            manifest=manifest,
            plugin_class=MagicMock(),
            path=tmp_path,
        )
        result = plugin.load_translations("de-DE")
        assert result == {"hello": "Hallo"}

    def test_load_translations_invalid_json(self, tmp_path):
        from streamarr.plugins.loader import Plugin

        i18n_dir = tmp_path / "i18n"
        i18n_dir.mkdir()
        trans_file = i18n_dir / "de.json"
        trans_file.write_text("not valid json {{{")

        manifest = self._make_manifest(i18n={"de-DE": "i18n/de.json"})
        plugin = Plugin(
            domain="test",
            manifest=manifest,
            plugin_class=MagicMock(),
            path=tmp_path,
        )
        result = plugin.load_translations("de-DE")
        assert result == {}

    @pytest.mark.asyncio
    async def test_async_setup_with_method(self):
        from streamarr.plugins.loader import Plugin

        manifest = self._make_manifest()
        mock_class = MagicMock()
        mock_class.async_setup = AsyncMock(return_value=True)

        plugin = Plugin(
            domain="test",
            manifest=manifest,
            plugin_class=mock_class,
            path=Path("/fake"),
        )
        result = await plugin.async_setup({"key": "value"})
        assert result is True

    @pytest.mark.asyncio
    async def test_async_setup_without_method(self):
        from streamarr.plugins.loader import Plugin

        manifest = self._make_manifest()
        mock_class = MagicMock(spec=[])  # no async_setup attribute

        plugin = Plugin(
            domain="test",
            manifest=manifest,
            plugin_class=mock_class,
            path=Path("/fake"),
        )
        result = await plugin.async_setup({})
        assert result is True

    @pytest.mark.asyncio
    async def test_async_setup_exception(self):
        from streamarr.plugins.loader import Plugin

        manifest = self._make_manifest()
        mock_class = MagicMock()
        mock_class.async_setup = AsyncMock(side_effect=Exception("fail"))

        plugin = Plugin(
            domain="test",
            manifest=manifest,
            plugin_class=mock_class,
            path=Path("/fake"),
        )
        result = await plugin.async_setup({})
        assert result is False

    @pytest.mark.asyncio
    async def test_async_unload_with_instance(self):
        from streamarr.plugins.loader import Plugin

        manifest = self._make_manifest()
        mock_class = MagicMock()
        mock_instance = AsyncMock()
        mock_class.return_value = mock_instance

        plugin = Plugin(
            domain="test",
            manifest=manifest,
            plugin_class=mock_class,
            path=Path("/fake"),
        )
        with patch("streamarr.plugins.loader.get_hook_manager"):
            plugin.get_instance()

        result = await plugin.async_unload()
        assert result is True
        mock_instance.close.assert_called_once()
        assert plugin._instance is None

    @pytest.mark.asyncio
    async def test_async_unload_no_instance(self):
        from streamarr.plugins.loader import Plugin

        manifest = self._make_manifest()
        plugin = Plugin(
            domain="test",
            manifest=manifest,
            plugin_class=MagicMock(),
            path=Path("/fake"),
        )
        result = await plugin.async_unload()
        assert result is True

    @pytest.mark.asyncio
    async def test_async_unload_exception(self):
        from streamarr.plugins.loader import Plugin

        manifest = self._make_manifest()
        mock_instance = AsyncMock()
        mock_instance.close.side_effect = Exception("fail")

        plugin = Plugin(
            domain="test",
            manifest=manifest,
            plugin_class=MagicMock(),
            path=Path("/fake"),
        )
        plugin._instance = mock_instance

        result = await plugin.async_unload()
        assert result is False


class TestPluginLoaderFunctions:
    """Tests for module-level plugin loader functions."""

    pytestmark = pytest.mark.skipif(
        not HAS_LEGACY_PLUGIN_LOADER,
        reason="legacy streamarr.plugins.loader module has been removed",
    )

    @pytest.mark.asyncio
    async def test_async_load_plugin_not_a_directory(self, tmp_path):
        from streamarr.plugins.loader import PluginLoadError, async_load_plugin

        fake_file = tmp_path / "not_a_dir.txt"
        fake_file.write_text("hello")

        with pytest.raises(PluginLoadError, match="not a directory"):
            await async_load_plugin(fake_file)

    @pytest.mark.asyncio
    async def test_async_load_plugin_no_manifest(self, tmp_path):
        from streamarr.plugins.loader import PluginLoadError, async_load_plugin

        plugin_dir = tmp_path / "myplugin"
        plugin_dir.mkdir()

        with pytest.raises(PluginLoadError, match="no manifest.json"):
            await async_load_plugin(plugin_dir)

    @pytest.mark.asyncio
    async def test_async_load_plugin_invalid_manifest(self, tmp_path):
        from streamarr.plugins.loader import PluginLoadError, async_load_plugin

        plugin_dir = tmp_path / "myplugin"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text("{}")

        with pytest.raises(PluginLoadError, match="Invalid manifest"):
            await async_load_plugin(plugin_dir)

    @pytest.mark.asyncio
    async def test_async_load_plugin_domain_mismatch(self, tmp_path):
        from streamarr.plugins.loader import PluginLoadError, async_load_plugin

        plugin_dir = tmp_path / "myplugin"
        plugin_dir.mkdir()
        manifest = {
            "name": "My Plugin",
            "domain": "different_domain",
            "version": "1.0.0",
            "plugin_types": ["library"],
            "documentation": "https://example.com",
            "description": "test",
        }
        (plugin_dir / "manifest.json").write_text(json.dumps(manifest))

        with pytest.raises(PluginLoadError, match="does not match directory"):
            await async_load_plugin(plugin_dir)

    @pytest.mark.asyncio
    async def test_async_discover_plugins_nonexistent_dir(self, tmp_path):
        from streamarr.plugins.loader import async_discover_plugins

        result = await async_discover_plugins(tmp_path / "nonexistent")
        assert result == {}

    @pytest.mark.asyncio
    async def test_async_discover_plugins_skips_hidden_and_underscore(self, tmp_path):
        from streamarr.plugins.loader import async_discover_plugins

        (tmp_path / "_internal").mkdir()
        (tmp_path / ".hidden").mkdir()

        result = await async_discover_plugins(tmp_path)
        assert result == {}

    def test_get_plugin_instance_not_found(self):
        import streamarr.libraries as lib_mod

        original_registry = lib_mod._registry
        original_instances = lib_mod._instances.copy()
        try:
            lib_mod._registry = {"MOVIES": MagicMock()}
            lib_mod._instances.clear()

            result = lib_mod.get_plugin_instance("NONEXISTENT")
            assert result is None
        finally:
            lib_mod._registry = original_registry
            lib_mod._instances.clear()
            lib_mod._instances.update(original_instances)

    def test_get_plugin_instance_case_insensitive(self):
        import streamarr.libraries as lib_mod

        mock_class = MagicMock()
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance

        original_registry = lib_mod._registry
        original_instances = lib_mod._instances.copy()
        try:
            lib_mod._registry = {"MOVIES": mock_class}
            lib_mod._instances.clear()

            result = lib_mod.get_plugin_instance("movies")
            assert result is mock_instance
        finally:
            lib_mod._registry = original_registry
            lib_mod._instances.clear()
            lib_mod._instances.update(original_instances)

    def test_get_available_media_types(self):
        import streamarr.libraries as lib_mod

        original_registry = lib_mod._registry
        try:
            lib_mod._registry = {"MOVIES": MagicMock(), "SHOWS": MagicMock()}

            result = lib_mod.get_available_media_types()
            assert "MOVIES" in result
            assert "SHOWS" in result
        finally:
            lib_mod._registry = original_registry

    def test_get_library_type_for_media_item_type_not_found(self):
        import streamarr.libraries as lib_mod

        original_registry = lib_mod._registry
        try:
            lib_mod._registry = {}

            result = lib_mod.get_library_type_for_media_item_type("NONEXISTENT")
            assert result is None
        finally:
            lib_mod._registry = original_registry

    def test_get_media_item_types_for_library_not_found(self):
        import streamarr.libraries as lib_mod

        original_registry = lib_mod._registry
        try:
            lib_mod._registry = {}

            result = lib_mod.get_media_item_types_for_library("NONEXISTENT")
            assert result == []
        finally:
            lib_mod._registry = original_registry

    def test_get_all_media_item_types(self):
        import streamarr.libraries as lib_mod

        mock_class = MagicMock()
        mock_instance = MagicMock()
        mock_instance.get_media_item_types.return_value = [
            {"name": "MOVIES"},
            {"name": "COLLECTIONS"},
        ]
        mock_class.return_value = mock_instance

        original_registry = lib_mod._registry
        try:
            lib_mod._registry = {"MOVIES": mock_class}

            result = lib_mod.get_all_media_item_types()
            assert "MOVIES" in result
            assert "COLLECTIONS" in result
        finally:
            lib_mod._registry = original_registry

    def test_get_all_media_item_types_dedup(self):
        """Duplicate type names across plugins should be deduplicated."""
        import streamarr.libraries as lib_mod

        mock_class_a = MagicMock()
        mock_inst_a = MagicMock()
        mock_inst_a.get_media_item_types.return_value = [{"name": "MOVIES"}]
        mock_class_a.return_value = mock_inst_a

        mock_class_b = MagicMock()
        mock_inst_b = MagicMock()
        mock_inst_b.get_media_item_types.return_value = [{"name": "MOVIES"}]
        mock_class_b.return_value = mock_inst_b

        original_registry = lib_mod._registry
        try:
            lib_mod._registry = {"A": mock_class_a, "B": mock_class_b}

            result = lib_mod.get_all_media_item_types()
            assert result.count("MOVIES") == 1
        finally:
            lib_mod._registry = original_registry


# ===================================================================
# services/download.py
# ===================================================================


class TestDownloadService:
    """Tests for DownloadService methods."""

    def _make_service(self, db=None):
        from streamarr.services.download import DownloadService

        return DownloadService(db=db or AsyncMock())

    @pytest.mark.asyncio
    async def test_extract_external_id_deluge(self):
        svc = self._make_service()
        downloader = MagicMock()
        downloader.type = "Deluge"

        result = await svc.extract_external_id_from_response(
            downloader, {"torrent_hash": "abc123"}
        )
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_extract_external_id_deluge_missing(self):
        svc = self._make_service()
        downloader = MagicMock()
        downloader.type = "Deluge"

        result = await svc.extract_external_id_from_response(downloader, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_external_id_sabnzbd(self):
        svc = self._make_service()
        downloader = MagicMock()
        downloader.type = "sabnzbd"

        result = await svc.extract_external_id_from_response(
            downloader, {"nzo_ids": ["nzo_123"]}
        )
        assert result == "nzo_123"

    @pytest.mark.asyncio
    async def test_extract_external_id_sabnzbd_empty(self):
        svc = self._make_service()
        downloader = MagicMock()
        downloader.type = "sabnzbd"

        result = await svc.extract_external_id_from_response(
            downloader, {"nzo_ids": []}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_external_id_spotdl(self):
        svc = self._make_service()
        downloader = MagicMock()
        downloader.type = "SpotDL"

        result = await svc.extract_external_id_from_response(
            downloader, {"job_id": "job-42"}
        )
        assert result == "job-42"

    @pytest.mark.asyncio
    async def test_extract_external_id_spotdl_missing(self):
        svc = self._make_service()
        downloader = MagicMock()
        downloader.type = "SpotDL"

        result = await svc.extract_external_id_from_response(downloader, {})
        assert result is None

    def test_is_valid_video_file(self, tmp_path):
        svc = self._make_service()

        # Valid video file
        video = tmp_path / "movie.mkv"
        video.write_text("data")
        assert svc.is_valid_video_file(video) is True

        # Sample file (should be excluded)
        sample = tmp_path / "Sample.mkv"
        sample.write_text("data")
        assert svc.is_valid_video_file(sample) is False

        # Wrong extension
        txt = tmp_path / "file.txt"
        txt.write_text("data")
        assert svc.is_valid_video_file(txt) is False

        # Non-existent file
        assert svc.is_valid_video_file(tmp_path / "nope.mkv") is False

        # Directory, not file
        subdir = tmp_path / "subdir.mkv"
        subdir.mkdir()
        assert svc.is_valid_video_file(subdir) is False

    def test_is_valid_audio_file(self, tmp_path):
        svc = self._make_service()

        mp3 = tmp_path / "song.mp3"
        mp3.write_text("data")
        assert svc.is_valid_audio_file(mp3) is True

        flac = tmp_path / "song.flac"
        flac.write_text("data")
        assert svc.is_valid_audio_file(flac) is True

        txt = tmp_path / "file.txt"
        txt.write_text("data")
        assert svc.is_valid_audio_file(txt) is False

        assert svc.is_valid_audio_file(tmp_path / "nope.mp3") is False

    def test_is_valid_media_file_music(self, tmp_path):
        svc = self._make_service()

        mp3 = tmp_path / "song.mp3"
        mp3.write_text("data")

        with patch(
            "streamarr.services.download.get_library_type_for_media_item_type",
            return_value="MUSIC",
        ):
            assert svc.is_valid_media_file(mp3, "SONGS") is True

    def test_is_valid_media_file_video(self, tmp_path):
        svc = self._make_service()

        mkv = tmp_path / "movie.mkv"
        mkv.write_text("data")

        with patch(
            "streamarr.services.download.get_library_type_for_media_item_type",
            return_value="MOVIES",
        ):
            assert svc.is_valid_media_file(mkv, "MOVIES") is True

    def test_is_valid_video_file_various_extensions(self, tmp_path):
        svc = self._make_service()

        for ext in [".mp4", ".avi", ".mov", ".wmv", ".flv", ".mpg", ".mpeg"]:
            f = tmp_path / f"file{ext}"
            f.write_text("data")
            assert svc.is_valid_video_file(f) is True, f"Expected {ext} to be valid"

    def test_is_valid_audio_file_various_extensions(self, tmp_path):
        svc = self._make_service()

        for ext in [".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma"]:
            f = tmp_path / f"file{ext}"
            f.write_text("data")
            assert svc.is_valid_audio_file(f) is True, f"Expected {ext} to be valid"

    @pytest.mark.asyncio
    async def test_mark_as_imported(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        svc = self._make_service(db=mock_db)

        download = MagicMock()
        download.status = "Completed"

        await svc.mark_as_imported(download)

        assert download.status == "Imported"
        mock_db.add.assert_called_once_with(download)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_as_failed_with_reason(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        svc = self._make_service(db=mock_db)

        download = MagicMock()
        download.status = "Completed"
        download.external_id = "ext-1"

        await svc.mark_as_failed(download, "bad data")

        assert download.status == "Failed"
        mock_db.add.assert_called_once_with(download)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_as_failed_no_reason(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        svc = self._make_service(db=mock_db)

        download = MagicMock()
        download.status = "Completed"

        await svc.mark_as_failed(download)
        assert download.status == "Failed"

    @pytest.mark.asyncio
    async def test_get_by_external_id(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "download_obj"
        mock_db.execute.return_value = mock_result

        svc = self._make_service(db=mock_db)
        result = await svc.get_by_external_id("ext-1")
        assert result == "download_obj"

    @pytest.mark.asyncio
    async def test_update_downloads_from_client_empty(self):
        mock_db = AsyncMock()
        svc = self._make_service(db=mock_db)

        downloader = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_downloads.return_value = []

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            result = await svc.update_downloads_from_client(downloader)

        assert result == {"updated": 0, "completed": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_update_downloads_from_client_with_changes(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_download = MagicMock()
        mock_download.external_id = "ext-1"
        mock_download.status = "Downloading"
        mock_download.progress = 50.0
        mock_download.speed_bps = 0

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_download]
        mock_db.execute.return_value = mock_result

        svc = self._make_service(db=mock_db)

        downloader = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_downloads.return_value = [
            {"external_id": "ext-1", "status": "Completed", "progress": 100.0}
        ]

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            result = await svc.update_downloads_from_client(downloader)

        assert result["updated"] == 1
        assert result["completed"] == 1
        assert mock_download.status == "Completed"

    @pytest.mark.asyncio
    async def test_update_downloads_skips_imported(self):
        mock_db = AsyncMock()
        mock_download = MagicMock()
        mock_download.external_id = "ext-1"
        mock_download.status = "Imported"
        mock_download.progress = 100.0

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_download]
        mock_db.execute.return_value = mock_result

        svc = self._make_service(db=mock_db)

        downloader = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_downloads.return_value = [
            {"external_id": "ext-1", "status": "Completed", "progress": 100.0}
        ]

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            result = await svc.update_downloads_from_client(downloader)

        assert result["updated"] == 0

    @pytest.mark.asyncio
    async def test_update_downloads_progress_change_only(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_download = MagicMock()
        mock_download.external_id = "ext-1"
        mock_download.status = "Downloading"
        mock_download.progress = 50.0

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_download]
        mock_db.execute.return_value = mock_result

        svc = self._make_service(db=mock_db)

        downloader = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_downloads.return_value = [
            {"external_id": "ext-1", "status": "Downloading", "progress": 75.0}
        ]

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            result = await svc.update_downloads_from_client(downloader)

        assert result["updated"] == 1
        assert result["completed"] == 0

    @pytest.mark.asyncio
    async def test_update_downloads_failed(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_download = MagicMock()
        mock_download.external_id = "ext-1"
        mock_download.status = "Downloading"
        mock_download.progress = 50.0

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_download]
        mock_db.execute.return_value = mock_result

        svc = self._make_service(db=mock_db)

        downloader = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_downloads.return_value = [
            {"external_id": "ext-1", "status": "Failed", "progress": 0.0}
        ]

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            result = await svc.update_downloads_from_client(downloader)

        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_add_music_download_no_spotdl(self):
        mock_db = AsyncMock()
        svc = self._make_service(db=mock_db)

        downloader = MagicMock()
        downloader.type = "sabnzbd"

        result = await svc.add_music_download("guid", [downloader])
        assert result is None

    @pytest.mark.asyncio
    async def test_blacklist_download_no_release_link(self):
        mock_db = AsyncMock()
        svc = self._make_service(db=mock_db)

        download = MagicMock()
        download.external_id = "ext-1"
        download.media_release_link = None

        result = await svc.blacklist_download(download)
        assert result is False

    @pytest.mark.asyncio
    async def test_blacklist_download_no_release(self):
        mock_db = AsyncMock()
        svc = self._make_service(db=mock_db)

        download = MagicMock()
        download.external_id = "ext-1"
        download.media_release_link = MagicMock()
        download.media_release_link.release = None

        result = await svc.blacklist_download(download)
        assert result is False

    @pytest.mark.asyncio
    async def test_blacklist_download_already_blacklisted(self):
        mock_db = AsyncMock()
        svc = self._make_service(db=mock_db)

        release = MagicMock()
        release.blacklisted_reason = "Already bad"
        release.title = "Test"

        download = MagicMock()
        download.external_id = "ext-1"
        download.media_release_link = MagicMock()
        download.media_release_link.release = release

        result = await svc.blacklist_download(download)
        assert result is True

    @pytest.mark.asyncio
    async def test_blacklist_download_success(self):
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        svc = self._make_service(db=mock_db)

        release = MagicMock()
        release.blacklisted_reason = None
        release.title = "Test Release"
        release.media_item_guid = uuid.uuid4()

        download = MagicMock()
        download.external_id = "ext-1"
        download.media_release_link = MagicMock()
        download.media_release_link.release = release

        result = await svc.blacklist_download(download, "Import failed")
        assert result is True
        assert release.blacklisted_reason == "Import failed"
        mock_db.add.assert_called_with(release)

    @pytest.mark.asyncio
    async def test_blacklist_download_exception(self):
        mock_db = AsyncMock()
        mock_db.refresh.side_effect = Exception("db error")
        svc = self._make_service(db=mock_db)

        download = MagicMock()
        download.external_id = "ext-1"

        result = await svc.blacklist_download(download)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_media_item_guid_success(self):
        mock_db = AsyncMock()
        svc = self._make_service(db=mock_db)

        expected_guid = uuid.uuid4()
        download = MagicMock()
        download.media_release_link = MagicMock()
        download.media_release_link.release = MagicMock()
        download.media_release_link.release.media_item_guid = expected_guid

        result = await svc.get_media_item_guid_for_download(download)
        assert result == expected_guid

    @pytest.mark.asyncio
    async def test_get_media_item_guid_no_link(self):
        mock_db = AsyncMock()
        svc = self._make_service(db=mock_db)

        download = MagicMock()
        download.media_release_link = None

        result = await svc.get_media_item_guid_for_download(download)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_media_item_guid_no_release(self):
        mock_db = AsyncMock()
        svc = self._make_service(db=mock_db)

        download = MagicMock()
        download.media_release_link = MagicMock()
        download.media_release_link.release = None

        result = await svc.get_media_item_guid_for_download(download)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_media_item_guid_exception(self):
        mock_db = AsyncMock()
        mock_db.refresh.side_effect = Exception("db error")
        svc = self._make_service(db=mock_db)

        download = MagicMock()

        result = await svc.get_media_item_guid_for_download(download)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_completed_download_not_found(self):
        mock_db = AsyncMock()
        svc = self._make_service(db=mock_db)

        with patch.object(svc, "get_by_external_id", return_value=None):
            result = await svc.handle_completed_download("ext-1", "/path")

        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_handle_completed_download_no_downloader(self):
        mock_db = AsyncMock()
        mock_db.get.return_value = None
        svc = self._make_service(db=mock_db)

        download = MagicMock()
        download.downloader_id = uuid.uuid4()

        with patch.object(svc, "get_by_external_id", return_value=download):
            result = await svc.handle_completed_download("ext-1", "/path")

        assert result["success"] is False
        assert "Downloader not found" in result["error"]

    @pytest.mark.asyncio
    async def test_update_downloads_no_change(self):
        """When status and progress are unchanged, updated should be 0."""
        mock_db = AsyncMock()
        mock_download = MagicMock()
        mock_download.external_id = "ext-1"
        mock_download.status = "Downloading"
        mock_download.progress = 50.0
        mock_download.speed_bps = 0

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_download]
        mock_db.execute.return_value = mock_result

        svc = self._make_service(db=mock_db)

        downloader = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_downloads.return_value = [
            {"external_id": "ext-1", "status": "Downloading", "progress": 50.0}
        ]

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            result = await svc.update_downloads_from_client(downloader)

        assert result["updated"] == 0

    @pytest.mark.asyncio
    async def test_update_downloads_unknown_external_id(self):
        """Downloads not in DB should be silently ignored."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        svc = self._make_service(db=mock_db)

        downloader = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_downloads.return_value = [
            {"external_id": "unknown-ext", "status": "Completed", "progress": 100.0}
        ]

        with patch.object(svc, "get_downloader_client", return_value=mock_client):
            result = await svc.update_downloads_from_client(downloader)

        assert result["updated"] == 0


# ===================================================================
# config.py
# ===================================================================


class TestConfig:
    """Tests for config dataclasses and AppSettings."""

    def test_oidc_config_defaults(self):
        cfg = OIDCConfig()
        assert cfg.enabled is False
        assert cfg.client_id is None
        assert cfg.scopes == ["openid", "profile", "email"]
        assert "sub" in cfg.claim_mapping

    def test_invites_config_defaults(self):
        cfg = InvitesConfig()
        assert cfg.enabled is True
        assert cfg.default_expiry_hours == 72

    def test_payment_config_defaults(self):
        cfg = PaymentConfig()
        assert cfg.enabled is False
        assert cfg.provider == "stripe"

    def test_email_config_defaults(self):
        cfg = EmailConfig()
        assert cfg.enabled is False
        assert cfg.smtp_port == 587

    def test_transcoding_config_defaults(self):
        cfg = TranscodingConfig()
        assert cfg.enabled is False
        assert cfg.ffmpeg_path == "ffmpeg"

    def test_metadata_config_defaults(self):
        cfg = MetadataConfig()
        assert cfg.tmdb_api_key is None
        assert cfg.locale == "de-DE"

    def test_library_config_defaults(self):
        cfg = LibraryConfig()
        assert cfg.enabled is True
        assert cfg.library_path == "/library"
        assert cfg.download_rules == []

    def test_library_config_custom_path(self):
        cfg = LibraryConfig(library_path="/custom/path")
        assert cfg.library_path == "/custom/path"

    def test_app_settings_init(self):
        app = AppSettings()
        assert app.oidc is not None
        assert app.invites is not None
        assert app.payment is not None
        assert app.email is not None
        assert app.transcoding is not None
        assert app.metadata is not None
        assert app.movies.library_path == "/library/movies"
        assert app.shows.library_path == "/library/shows"
        assert app.music.library_path == "/library/music"
        assert app.books.library_path == "/library/books"
        assert app.games.library_path == "/library/games"

    def test_connection_settings_has_secret_key(self):
        """The module-level settings should have the test SECRET_KEY."""
        from streamarr.config import settings

        assert settings.secret_key is not None
        assert settings.secret_key != ""

    def test_connection_settings_database_url(self):
        from streamarr.config import connection_settings

        # In tests, DATABASE_URL is set to sqlite
        assert "sqlite" in connection_settings.database_url

    def test_oidc_config_custom_scopes(self):
        cfg = OIDCConfig(scopes=["openid", "custom_scope"])
        assert cfg.scopes == ["openid", "custom_scope"]

    def test_email_config_custom(self):
        cfg = EmailConfig(
            enabled=True,
            smtp_host="mail.example.com",
            smtp_port=465,
            smtp_use_ssl=True,
            smtp_use_tls=False,
        )
        assert cfg.enabled is True
        assert cfg.smtp_host == "mail.example.com"
        assert cfg.smtp_use_ssl is True

    def test_transcoding_config_kubernetes(self):
        cfg = TranscodingConfig(
            kubernetes_enabled=True,
            job_cpu_limit="4",
            job_memory_limit="8Gi",
        )
        assert cfg.kubernetes_enabled is True
        assert cfg.job_cpu_limit == "4"
