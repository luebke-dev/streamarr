"""
Device Service

This service handles all device-related operations for user device management.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

logger = logging.getLogger(__name__)

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.device import Device
from pyrate.schemas.device import DeviceRead, DeviceReadWithUser


class DeviceService:
    """Service for managing user devices"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_device(
        self,
        user_id: UUID,
        device_id: str,
        device_info: dict | None = None,
        ip_address: str | None = None,
    ) -> Device:
        """Get existing device or create a new one"""
        # Try to find existing device
        existing = await self.get_by_device_id(user_id, device_id)

        if existing:
            # Update last activity and device info
            existing.last_activity = datetime.now(UTC)
            if ip_address:
                existing.last_ip_address = ip_address
            if device_info:
                existing.device_info = device_info
                existing.browser = device_info.get("browser")
                existing.platform = device_info.get("platform")
                existing.user_agent = device_info.get("user_agent")
                existing.language = device_info.get("language")
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

        # Create new device
        device = Device(
            user_id=user_id,
            device_id=device_id,
            device_info=device_info,
            browser=device_info.get("browser") if device_info else None,
            platform=device_info.get("platform") if device_info else None,
            user_agent=device_info.get("user_agent") if device_info else None,
            language=device_info.get("language") if device_info else None,
            last_ip_address=ip_address,
        )
        self.db.add(device)
        await self.db.commit()
        await self.db.refresh(device)
        logger.info("Created new device %s for user %s", device.guid, user_id)
        return device

    async def get_by_id(self, device_guid: UUID) -> Device | None:
        """Get device by GUID"""
        result = await self.db.execute(
            select(Device)
            .options(selectinload(Device.user))
            .where(Device.guid == device_guid)
        )
        return result.scalar_one_or_none()

    async def get_by_device_id(self, user_id: UUID, device_id: str) -> Device | None:
        """Get device by user_id and device_id combination"""
        result = await self.db.execute(
            select(Device).where(
                and_(
                    Device.user_id == user_id,
                    Device.device_id == device_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 100,
        include_inactive: bool = False,
    ) -> list[Device]:
        """Get all devices for a user"""
        query = select(Device).where(Device.user_id == user_id)

        if not include_inactive:
            query = query.where(Device.is_active)

        query = query.order_by(Device.last_activity.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        search: str | None = None,
        include_inactive: bool = False,
    ) -> tuple[list[Device], int]:
        """Get all devices with pagination and optional search"""
        query = select(Device).options(selectinload(Device.user))
        count_query = select(func.count(Device.guid))

        if not include_inactive:
            query = query.where(Device.is_active)
            count_query = count_query.where(Device.is_active)

        if search:
            search_filter = f"%{search}%"
            query = query.where(
                Device.name.ilike(search_filter)
                | Device.browser.ilike(search_filter)
                | Device.platform.ilike(search_filter)
                | Device.device_id.ilike(search_filter)
            )
            count_query = count_query.where(
                Device.name.ilike(search_filter)
                | Device.browser.ilike(search_filter)
                | Device.platform.ilike(search_filter)
                | Device.device_id.ilike(search_filter)
            )

        query = query.order_by(Device.last_activity.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        count_result = await self.db.execute(count_query)

        return list(result.scalars().all()), count_result.scalar_one()

    async def update_device(
        self,
        device_guid: UUID,
        name: str | None = None,
        is_trusted: bool | None = None,
    ) -> Device | None:
        """Update device properties"""
        device = await self.get_by_id(device_guid)
        if not device:
            logger.warning("Device %s not found for update", device_guid)
            return None

        if name is not None:
            device.name = name
        if is_trusted is not None:
            device.is_trusted = is_trusted

        await self.db.commit()
        await self.db.refresh(device)
        logger.info("Updated device %s", device_guid)
        return device

    async def deactivate_device(self, device_guid: UUID) -> bool:
        """Deactivate a device (soft delete)"""
        device = await self.get_by_id(device_guid)
        if not device:
            logger.warning("Device %s not found for deactivation", device_guid)
            return False

        device.is_active = False
        await self.db.commit()
        logger.info("Deactivated device %s", device_guid)
        return True

    async def delete_device(self, device_guid: UUID) -> bool:
        """Permanently delete a device"""
        device = await self.get_by_id(device_guid)
        if not device:
            logger.warning("Device %s not found for deletion", device_guid)
            return False

        await self.db.delete(device)
        await self.db.commit()
        logger.info("Deleted device %s", device_guid)
        return True

    async def count_by_user(self, user_id: UUID, active_only: bool = True) -> int:
        """Count devices for a user"""
        query = select(func.count(Device.guid)).where(Device.user_id == user_id)
        if active_only:
            query = query.where(Device.is_active)
        result = await self.db.execute(query)
        return result.scalar_one()

    def enrich_device_read(
        self, device: Device, connected_device_ids: set[str]
    ) -> DeviceRead:
        """Convert a Device to DeviceRead with WebSocket connection status."""
        device_read = DeviceRead.model_validate(device)
        device_read.is_ws_connected = device.device_id in connected_device_ids
        return device_read

    def enrich_device_read_with_user(
        self, device: Device, connected_device_ids: set[str]
    ) -> DeviceReadWithUser:
        """Convert a Device to DeviceReadWithUser with user info and WS status."""
        device_data = DeviceReadWithUser.model_validate(device)
        if device.user:
            device_data.user_email = device.user.email
            device_data.user_name = (
                f"{device.user.first_name} {device.user.last_name}".strip()
            )
        device_data.is_ws_connected = device.device_id in connected_device_ids
        return device_data

    async def update_last_activity(
        self, device_guid: UUID, ip_address: str | None = None
    ) -> None:
        """Update last activity timestamp for a device"""
        device = await self.get_by_id(device_guid)
        if device:
            device.last_activity = datetime.now(UTC)
            if ip_address:
                device.last_ip_address = ip_address
            await self.db.commit()
