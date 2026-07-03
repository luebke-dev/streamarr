"""
Invite Service

This service handles all invite-related operations for user invitations.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

logger = logging.getLogger(__name__)

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.auth.jwt_handler import jwt_handler
from pyrate.config import settings
from pyrate.models.invite import Invite
from pyrate.schemas.invite import InviteCreate, InviteUpdate


class InviteService:
    """Service for managing user invitations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        invite_create: InviteCreate,
        created_by_user_id: UUID,
        token: str,
        expires_at: datetime,
    ) -> Invite:
        """Create a new invite"""
        db_invite = Invite(
            created_by_user_id=created_by_user_id,
            token=token,
            expires_at=expires_at,
            description=invite_create.description,
            max_uses=invite_create.max_uses,
        )
        self.db.add(db_invite)
        await self.db.commit()
        await self.db.refresh(db_invite)
        return db_invite

    async def create_invite_with_token(
        self,
        invite_create: InviteCreate,
        created_by_user_id: UUID,
    ) -> Invite:
        """
        Create an invite with auto-generated JWT token and computed expiry.

        Handles expiry calculation from either expires_at or expiry_hours,
        validates against max_expiry_hours, and generates the JWT token.

        Returns:
            The created Invite.

        Raises:
            ValueError: If expiry_hours exceeds the configured maximum.
        """
        if invite_create.expires_at:
            expires_at = invite_create.expires_at
            delta = expires_at - datetime.now(UTC)
            expiry_hours = max(1, int(delta.total_seconds() / 3600))
        else:
            expiry_hours = (
                invite_create.expiry_hours or settings.invites.default_expiry_hours
            )
            if expiry_hours > settings.invites.max_expiry_hours:
                raise ValueError(
                    f"Expiry time cannot exceed {settings.invites.max_expiry_hours} hours"
                )
            expires_at = datetime.now(UTC) + timedelta(hours=expiry_hours)

        token_data = {
            "created_by_user_id": str(created_by_user_id),
            "expires_at": expires_at.isoformat(),
        }
        token = jwt_handler.create_invite_token(token_data, timedelta(hours=expiry_hours))

        invite = await self.create(
            invite_create=invite_create,
            created_by_user_id=created_by_user_id,
            token=token,
            expires_at=expires_at,
        )
        logger.info(
            "Created invite %s by user %s, expires %s, max_uses=%d",
            invite.guid, created_by_user_id, expires_at, invite.max_uses,
        )
        return invite

    async def get_by_id(self, invite_id: UUID) -> Invite | None:
        """Get invite by ID"""
        result = await self.db.execute(
            select(Invite)
            .options(selectinload(Invite.created_by), selectinload(Invite.used_by))
            .where(Invite.guid == invite_id)
        )
        return result.scalar_one_or_none()

    async def get_by_token(self, token: str) -> Invite | None:
        """Get invite by token"""
        result = await self.db.execute(
            select(Invite)
            .options(selectinload(Invite.created_by), selectinload(Invite.used_by))
            .where(Invite.token == token)
        )
        return result.scalar_one_or_none()

    async def get_valid_by_token(self, token: str) -> Invite | None:
        """Get valid (active, not expired, not fully used) invite by token"""
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(Invite)
            .options(selectinload(Invite.created_by), selectinload(Invite.used_by))
            .where(
                and_(
                    Invite.token == token,
                    Invite.is_active,
                    Invite.expires_at > now,
                    Invite.current_uses < Invite.max_uses,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self, user_id: UUID, skip: int = 0, limit: int = 100
    ) -> list[Invite]:
        """Get invites created by a user"""
        result = await self.db.execute(
            select(Invite)
            .options(selectinload(Invite.used_by))
            .where(Invite.created_by_user_id == user_id)
            .order_by(Invite.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_user_paginated(
        self, user_id: UUID, skip: int = 0, limit: int = 100
    ) -> tuple[list[Invite], int]:
        """Get invites created by a user with total count"""
        # Get total count
        count_result = await self.db.execute(
            select(func.count(Invite.guid)).where(Invite.created_by_user_id == user_id)
        )
        total = count_result.scalar() or 0

        # Get paginated results
        result = await self.db.execute(
            select(Invite)
            .options(selectinload(Invite.created_by), selectinload(Invite.used_by))
            .where(Invite.created_by_user_id == user_id)
            .order_by(Invite.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        invites = list(result.scalars().all())

        return invites, total

    async def get_all(
        self, skip: int = 0, limit: int = 100, include_expired: bool = False
    ) -> list[Invite]:
        """Get all invites"""
        query = select(Invite).options(
            selectinload(Invite.created_by), selectinload(Invite.used_by)
        )

        if not include_expired:
            now = datetime.now(UTC)
            query = query.where(Invite.expires_at > now)

        query = query.order_by(Invite.created_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_all_paginated(
        self, skip: int = 0, limit: int = 100, include_expired: bool = False
    ) -> tuple[list[Invite], int]:
        """Get all invites with total count"""
        # Build base query for count
        count_query = select(func.count(Invite.guid))
        if not include_expired:
            now = datetime.now(UTC)
            count_query = count_query.where(Invite.expires_at > now)

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Get paginated results
        query = select(Invite).options(
            selectinload(Invite.created_by), selectinload(Invite.used_by)
        )

        if not include_expired:
            now = datetime.now(UTC)
            query = query.where(Invite.expires_at > now)

        query = query.order_by(Invite.created_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        invites = list(result.scalars().all())

        return invites, total

    async def update(
        self, invite_id: UUID, invite_update: InviteUpdate
    ) -> Invite | None:
        """Update an invite"""
        result = await self.db.execute(select(Invite).where(Invite.guid == invite_id))
        db_invite = result.scalar_one_or_none()

        if not db_invite:
            return None

        update_data = invite_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_invite, field, value)

        await self.db.commit()
        await self.db.refresh(db_invite)
        return db_invite

    async def use_invite(self, invite_id: UUID, used_by_user_id: UUID) -> Invite | None:
        """
        Mark an invite as used by incrementing usage counter.

        If max uses is reached, marks the invite as fully used.
        """
        result = await self.db.execute(select(Invite).where(Invite.guid == invite_id))
        db_invite = result.scalar_one_or_none()

        if not db_invite:
            return None

        db_invite.current_uses += 1
        db_invite.used_by_user_id = used_by_user_id

        # If this was the last use, mark as used
        if db_invite.current_uses >= db_invite.max_uses:
            db_invite.is_used = True
            db_invite.used_at = datetime.now(UTC)
            logger.info("Invite %s fully consumed (%d/%d uses)", invite_id, db_invite.current_uses, db_invite.max_uses)
        else:
            logger.info("Invite %s used by user %s (%d/%d uses)", invite_id, used_by_user_id, db_invite.current_uses, db_invite.max_uses)

        await self.db.commit()
        await self.db.refresh(db_invite)
        return db_invite

    async def deactivate(self, invite_id: UUID) -> Invite | None:
        """Deactivate an invite (prevents further usage)"""
        result = await self.db.execute(select(Invite).where(Invite.guid == invite_id))
        db_invite = result.scalar_one_or_none()

        if not db_invite:
            return None

        db_invite.is_active = False
        await self.db.commit()
        await self.db.refresh(db_invite)
        return db_invite

    async def delete(self, invite_id: UUID) -> bool:
        """Delete an invite"""
        result = await self.db.execute(select(Invite).where(Invite.guid == invite_id))
        db_invite = result.scalar_one_or_none()

        if not db_invite:
            return False

        await self.db.delete(db_invite)
        await self.db.commit()
        return True

    async def cleanup_expired(self) -> int:
        """
        Delete expired invites.

        Returns the number of invites deleted.
        """
        now = datetime.now(UTC)
        result = await self.db.execute(
            delete(Invite).where(Invite.expires_at < now)
        )
        await self.db.commit()
        count = result.rowcount
        if count > 0:
            logger.info("Cleaned up %d expired invites", count)
        return count
