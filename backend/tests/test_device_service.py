"""Tests for the DeviceService."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.device import Device
from streamarr.models.user import User
from streamarr.services.device import DeviceService


class TestDeviceGetOrCreate:
    """Test get_or_create_device operations."""

    @pytest.mark.asyncio
    async def test_create_new_device(self, db_session: AsyncSession, test_user: User):
        """Test creating a new device when none exists."""
        service = DeviceService(db_session)
        device_info = {
            "browser": "Chrome",
            "platform": "Linux",
            "user_agent": "Mozilla/5.0",
            "language": "en-US",
        }

        device = await service.get_or_create_device(
            user_id=test_user.guid,
            device_id="test-device-001",
            device_info=device_info,
            ip_address="192.168.1.1",
        )

        assert device is not None
        assert device.device_id == "test-device-001"
        assert device.user_id == test_user.guid
        assert device.browser == "Chrome"
        assert device.platform == "Linux"
        assert device.user_agent == "Mozilla/5.0"
        assert device.language == "en-US"
        assert device.last_ip_address == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_get_existing_device(self, db_session: AsyncSession, test_user: User):
        """Test that get_or_create returns existing device and updates it."""
        service = DeviceService(db_session)
        device_info = {
            "browser": "Chrome",
            "platform": "Linux",
        }

        # Create device first
        device1 = await service.get_or_create_device(
            user_id=test_user.guid,
            device_id="test-device-001",
            device_info=device_info,
        )

        # Get same device again with updated info
        updated_info = {
            "browser": "Firefox",
            "platform": "Windows",
            "user_agent": "Mozilla/5.0 Firefox",
            "language": "de-DE",
        }
        device2 = await service.get_or_create_device(
            user_id=test_user.guid,
            device_id="test-device-001",
            device_info=updated_info,
            ip_address="10.0.0.1",
        )

        assert device1.guid == device2.guid
        assert device2.browser == "Firefox"
        assert device2.platform == "Windows"
        assert device2.last_ip_address == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_create_device_without_info(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test creating a device without device_info."""
        service = DeviceService(db_session)

        device = await service.get_or_create_device(
            user_id=test_user.guid,
            device_id="minimal-device",
        )

        assert device is not None
        assert device.device_id == "minimal-device"
        assert device.browser is None
        assert device.platform is None


class TestDeviceGetById:
    """Test get_by_id operations."""

    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session: AsyncSession, test_user: User):
        """Test retrieving a device by its GUID."""
        service = DeviceService(db_session)
        device = await service.get_or_create_device(
            user_id=test_user.guid,
            device_id="test-device-001",
        )

        retrieved = await service.get_by_id(device.guid)

        assert retrieved is not None
        assert retrieved.guid == device.guid
        assert retrieved.device_id == "test-device-001"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session: AsyncSession):
        """Test retrieving a non-existent device."""
        service = DeviceService(db_session)

        retrieved = await service.get_by_id(uuid.uuid4())

        assert retrieved is None


class TestDeviceGetByUser:
    """Test get_by_user operations."""

    @pytest.mark.asyncio
    async def test_get_by_user(self, db_session: AsyncSession, test_user: User):
        """Test getting all devices for a user."""
        service = DeviceService(db_session)

        await service.get_or_create_device(
            user_id=test_user.guid, device_id="device-1"
        )
        await service.get_or_create_device(
            user_id=test_user.guid, device_id="device-2"
        )
        await service.get_or_create_device(
            user_id=test_user.guid, device_id="device-3"
        )

        devices = await service.get_by_user(test_user.guid)

        assert len(devices) == 3

    @pytest.mark.asyncio
    async def test_get_by_user_excludes_inactive(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that inactive devices are excluded by default."""
        service = DeviceService(db_session)

        await service.get_or_create_device(
            user_id=test_user.guid, device_id="active-device"
        )
        inactive = await service.get_or_create_device(
            user_id=test_user.guid, device_id="inactive-device"
        )
        await service.deactivate_device(inactive.guid)

        active_devices = await service.get_by_user(test_user.guid)
        all_devices = await service.get_by_user(
            test_user.guid, include_inactive=True
        )

        assert len(active_devices) == 1
        assert len(all_devices) == 2

    @pytest.mark.asyncio
    async def test_get_by_user_pagination(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test pagination for user devices."""
        service = DeviceService(db_session)

        for i in range(5):
            await service.get_or_create_device(
                user_id=test_user.guid, device_id=f"device-{i}"
            )

        page1 = await service.get_by_user(test_user.guid, skip=0, limit=2)
        page2 = await service.get_by_user(test_user.guid, skip=2, limit=2)

        assert len(page1) == 2
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_get_by_user_empty(self, db_session: AsyncSession, test_user: User):
        """Test getting devices for a user with no devices."""
        service = DeviceService(db_session)

        devices = await service.get_by_user(test_user.guid)

        assert len(devices) == 0


class TestDeviceUpdate:
    """Test device update operations."""

    @pytest.mark.asyncio
    async def test_update_device_name(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test updating a device name."""
        service = DeviceService(db_session)
        device = await service.get_or_create_device(
            user_id=test_user.guid, device_id="test-device"
        )

        updated = await service.update_device(device.guid, name="My Phone")

        assert updated is not None
        assert updated.name == "My Phone"

    @pytest.mark.asyncio
    async def test_update_device_trusted(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test marking a device as trusted."""
        service = DeviceService(db_session)
        device = await service.get_or_create_device(
            user_id=test_user.guid, device_id="test-device"
        )

        updated = await service.update_device(device.guid, is_trusted=True)

        assert updated is not None
        assert updated.is_trusted is True

    @pytest.mark.asyncio
    async def test_update_nonexistent_device(self, db_session: AsyncSession):
        """Test updating a non-existent device returns None."""
        service = DeviceService(db_session)

        result = await service.update_device(uuid.uuid4(), name="Nope")

        assert result is None


class TestDeviceDeactivateAndDelete:
    """Test device deactivation and deletion."""

    @pytest.mark.asyncio
    async def test_deactivate_device(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test deactivating a device."""
        service = DeviceService(db_session)
        device = await service.get_or_create_device(
            user_id=test_user.guid, device_id="test-device"
        )

        result = await service.deactivate_device(device.guid)

        assert result is True
        deactivated = await service.get_by_id(device.guid)
        assert deactivated.is_active is False

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent_device(self, db_session: AsyncSession):
        """Test deactivating a non-existent device."""
        service = DeviceService(db_session)

        result = await service.deactivate_device(uuid.uuid4())

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_device(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test permanently deleting a device."""
        service = DeviceService(db_session)
        device = await service.get_or_create_device(
            user_id=test_user.guid, device_id="test-device"
        )

        result = await service.delete_device(device.guid)

        assert result is True
        deleted = await service.get_by_id(device.guid)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_device(self, db_session: AsyncSession):
        """Test deleting a non-existent device."""
        service = DeviceService(db_session)

        result = await service.delete_device(uuid.uuid4())

        assert result is False


class TestDeviceCount:
    """Test device counting operations."""

    @pytest.mark.asyncio
    async def test_count_by_user(self, db_session: AsyncSession, test_user: User):
        """Test counting devices for a user."""
        service = DeviceService(db_session)

        await service.get_or_create_device(
            user_id=test_user.guid, device_id="device-1"
        )
        await service.get_or_create_device(
            user_id=test_user.guid, device_id="device-2"
        )

        count = await service.count_by_user(test_user.guid)

        assert count == 2

    @pytest.mark.asyncio
    async def test_count_by_user_active_only(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test counting only active devices."""
        service = DeviceService(db_session)

        await service.get_or_create_device(
            user_id=test_user.guid, device_id="device-1"
        )
        inactive = await service.get_or_create_device(
            user_id=test_user.guid, device_id="device-2"
        )
        await service.deactivate_device(inactive.guid)

        active_count = await service.count_by_user(test_user.guid, active_only=True)
        total_count = await service.count_by_user(test_user.guid, active_only=False)

        assert active_count == 1
        assert total_count == 2


class TestDeviceGetAll:
    """Test get_all operations."""

    @pytest.mark.asyncio
    async def test_get_all_devices(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test getting all devices across users."""
        service = DeviceService(db_session)

        await service.get_or_create_device(
            user_id=test_user.guid, device_id="user1-device"
        )
        await service.get_or_create_device(
            user_id=test_user2.guid, device_id="user2-device"
        )

        devices, total = await service.get_all()

        assert total == 2
        assert len(devices) == 2

    @pytest.mark.asyncio
    async def test_get_all_with_search(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test searching devices."""
        service = DeviceService(db_session)

        await service.get_or_create_device(
            user_id=test_user.guid,
            device_id="chrome-device",
            device_info={"browser": "Chrome", "platform": "Linux"},
        )
        await service.get_or_create_device(
            user_id=test_user.guid,
            device_id="firefox-device",
            device_info={"browser": "Firefox", "platform": "Windows"},
        )

        devices, total = await service.get_all(search="Chrome")

        assert total == 1
        assert len(devices) == 1

    @pytest.mark.asyncio
    async def test_get_all_pagination(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test paginated device listing."""
        service = DeviceService(db_session)

        for i in range(5):
            await service.get_or_create_device(
                user_id=test_user.guid, device_id=f"device-{i}"
            )

        devices, total = await service.get_all(skip=0, limit=2)

        assert total == 5
        assert len(devices) == 2


class TestDeviceUpdateLastActivity:
    """Test updating last activity."""

    @pytest.mark.asyncio
    async def test_update_last_activity(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test updating device last activity timestamp."""
        service = DeviceService(db_session)
        device = await service.get_or_create_device(
            user_id=test_user.guid, device_id="test-device"
        )
        original_activity = device.last_activity

        await service.update_last_activity(device.guid, ip_address="10.0.0.1")

        updated = await service.get_by_id(device.guid)
        assert updated.last_ip_address == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_update_last_activity_nonexistent(self, db_session: AsyncSession):
        """Test updating last activity for non-existent device does nothing."""
        service = DeviceService(db_session)

        # Should not raise an error
        await service.update_last_activity(uuid.uuid4())
