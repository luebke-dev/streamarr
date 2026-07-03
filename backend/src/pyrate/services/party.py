"""Service for group watch sessions."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.friendship import Friendship, FriendshipStatus
from pyrate.models.user import User
from pyrate.models.party import WatchParty, WatchPartyMember
from pyrate.schemas.party import (
    PlaybackSync,
    WatchPartyAdminResponse,
    WatchPartyCreate,
    WatchPartyListResponse,
    WatchPartyMemberResponse,
    WatchPartyResponse,
    WatchPartyUpdate,
)

logger = logging.getLogger(__name__)


class WatchPartyService:
    """Service for managing group watch sessions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(
        self, user_id: uuid.UUID, data: WatchPartyCreate
    ) -> WatchPartyResponse:
        """
        Create a new group session.

        Args:
            user_id: ID of the user creating the session
            data: Session creation data

        Returns:
            Created session information
        """
        # Create session
        session = WatchParty(
            owner_id=user_id,
            media_id=data.media_id,
            media_type=data.media_type,
            name=data.name,
            allow_control=data.allow_control,
        )
        self.db.add(session)
        await self.db.flush()

        # Add owner as first member and host
        member = WatchPartyMember(
            party_id=session.guid,
            user_id=user_id,
            is_host=True,
        )
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(session, ["members"])

        logger.info(
            "Created group session %s (code: %s) for user %s",
            session.guid, session.party_code, user_id,
        )

        return await self._session_to_response(session)

    async def join_session(
        self, user_id: uuid.UUID, party_code: str
    ) -> WatchPartyResponse:
        """
        Join an existing session via code.

        Args:
            user_id: ID of the user joining
            party_code: Session code to join

        Returns:
            Session information

        Raises:
            ValueError: If session not found, inactive, full, or user already joined
        """
        # Find session
        stmt = (
            select(WatchParty)
            .where(
                WatchParty.party_code == party_code.upper(),
                WatchParty.is_active,
                WatchParty.expires_at > datetime.now(UTC),
            )
            .options(selectinload(WatchParty.members))
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise ValueError("Session not found or expired")

        # Check if already a member
        existing_member = next(
            (m for m in session.members if m.user_id == user_id), None
        )
        if existing_member:
            if existing_member.is_connected:
                raise ValueError("You are already in this session")
            # Rejoin - mark as connected again
            existing_member.is_connected = True
            existing_member.left_at = None
            existing_member.last_heartbeat = datetime.now(UTC)
            await self.db.commit()
            await self.db.refresh(session, ["members"])
            logger.info("User %s rejoined session %s", user_id, session.guid)
            return await self._session_to_response(session)

        # Add new member
        member = WatchPartyMember(
            party_id=session.guid,
            user_id=user_id,
            is_host=False,
        )
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(session, ["members"])

        logger.info("User %s joined session %s", user_id, session.guid)

        return await self._session_to_response(session)

    async def leave_session(self, user_id: uuid.UUID, party_id: uuid.UUID):
        """
        Leave a session.

        Args:
            user_id: ID of the user leaving
            party_id: ID of the session to leave
        """
        stmt = select(WatchPartyMember).where(
            WatchPartyMember.party_id == party_id,
            WatchPartyMember.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        member = result.scalar_one_or_none()

        if member:
            member.is_connected = False
            member.left_at = datetime.now(UTC)
            await self.db.commit()

            logger.info("User %s left session %s", user_id, party_id)

            # If owner left, end the session
            if member.is_host:
                await self.end_session(party_id)

    async def kick_member(
        self, party_id: uuid.UUID, host_id: uuid.UUID, target_user_id: uuid.UUID
    ):
        """
        Remove a member from the session (host only).

        Args:
            party_id: ID of the session
            host_id: ID of the host performing the kick
            target_user_id: ID of the user to kick

        Raises:
            ValueError: If session not found, user not host, or target not found
        """
        stmt = (
            select(WatchParty)
            .where(WatchParty.guid == party_id, WatchParty.is_active)
            .options(selectinload(WatchParty.members))
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise ValueError("Session not found or inactive")

        if session.owner_id != host_id:
            raise ValueError("Only the host can remove members")

        target_member = next(
            (m for m in session.members if m.user_id == target_user_id), None
        )
        if not target_member:
            raise ValueError("Member not found in session")

        if target_member.is_host:
            raise ValueError("Cannot remove the host")

        target_member.is_connected = False
        target_member.left_at = datetime.now(UTC)
        await self.db.commit()

        logger.info("Host %s kicked user %s from session %s", host_id, target_user_id, party_id)

    async def end_session(
        self, party_id: uuid.UUID, host_id: uuid.UUID | None = None
    ):
        """
        End a session. If host_id is provided, validates ownership.

        Args:
            party_id: ID of the session to end
            host_id: If provided, validates that this user is the host

        Raises:
            ValueError: If session not found or user is not the host
        """
        stmt = select(WatchParty).where(WatchParty.guid == party_id)
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise ValueError("Session not found")

        if host_id is not None and session.owner_id != host_id:
            raise ValueError("Only the host can end the session")

        session.is_active = False
        session.ended_at = datetime.now(UTC)
        await self.db.commit()

        logger.info("Ended session %s", party_id)

    async def update_session(
        self, party_id: uuid.UUID, host_id: uuid.UUID, data: WatchPartyUpdate
    ) -> WatchPartyResponse:
        """
        Update session settings (host only).

        Args:
            party_id: ID of the session
            host_id: ID of the user performing the update
            data: Update data

        Returns:
            Updated session information

        Raises:
            ValueError: If session not found or user is not host
        """
        stmt = (
            select(WatchParty)
            .where(WatchParty.guid == party_id)
            .options(selectinload(WatchParty.members))
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise ValueError("Session not found")

        if session.owner_id != host_id:
            raise ValueError("Only the host can update the session")

        # Update fields if provided
        if data.name is not None:
            session.name = data.name
        if data.allow_control is not None:
            session.allow_control = data.allow_control

        media_changed = data.media_id is not None and data.media_id != session.media_id
        if data.media_id is not None:
            session.media_id = data.media_id
        if data.media_type is not None:
            session.media_type = data.media_type

        # Reset playback state when media changes
        if media_changed:
            session.current_time = 0
            session.is_playing = False
            session.last_sync_at = datetime.now(UTC)
            # Update cached media title
            from pyrate.models.media import MediaItem
            item = await self.db.get(MediaItem, data.media_id)
            if item:
                session.media_title = item.title

        await self.db.commit()
        await self.db.refresh(session, ["members"])

        logger.info("Updated session %s", party_id)

        return await self._session_to_response(session)

    async def sync_playback(
        self, party_id: uuid.UUID, user_id: uuid.UUID, sync_data: PlaybackSync
    ) -> WatchPartyResponse:
        """
        Update playback state for a session.

        Args:
            party_id: ID of the session
            user_id: ID of the user sending the update
            sync_data: Playback state data

        Returns:
            Updated session information

        Raises:
            ValueError: If session not found or user not authorized
        """
        stmt = (
            select(WatchParty)
            .where(WatchParty.guid == party_id, WatchParty.is_active)
            .options(selectinload(WatchParty.members))
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise ValueError("Session not found or inactive")

        # Check if user is a member
        member = next((m for m in session.members if m.user_id == user_id), None)
        if not member or not member.is_connected:
            raise ValueError("You are not a member of this session")

        # Check if user has control permission
        if not session.allow_control and not member.is_host:
            raise ValueError("Only the host can control playback")

        # Update session state
        session.current_time = sync_data.current_time
        session.is_playing = sync_data.is_playing
        session.playback_rate = sync_data.playback_rate
        session.last_sync_at = datetime.now(UTC)

        # Update member position
        member.last_position = sync_data.current_time
        member.last_heartbeat = datetime.now(UTC)

        await self.db.commit()
        await self.db.refresh(session, ["members"])

        return await self._session_to_response(session)

    async def get_session(self, party_id: uuid.UUID) -> WatchPartyResponse | None:
        """
        Get session information.

        Args:
            party_id: ID of the session

        Returns:
            Session information or None if not found
        """
        stmt = (
            select(WatchParty)
            .where(WatchParty.guid == party_id)
            .options(selectinload(WatchParty.members))
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            return None

        return await self._session_to_response(session)

    async def get_user_sessions(
        self, user_id: uuid.UUID
    ) -> list[WatchPartyListResponse]:
        """
        Get all active sessions for a user.

        Args:
            user_id: ID of the user

        Returns:
            List of sessions the user is part of
        """
        # Get sessions where user is a member
        stmt = (
            select(WatchParty)
            .join(WatchParty.members)
            .where(
                WatchPartyMember.user_id == user_id,
                WatchPartyMember.is_connected,
                WatchParty.is_active,
                WatchParty.expires_at > datetime.now(UTC),
            )
            .options(selectinload(WatchParty.members))
        )
        result = await self.db.execute(stmt)
        sessions = result.scalars().all()

        return [
            WatchPartyListResponse(
                guid=s.guid,
                party_code=s.party_code,
                name=s.name,
                media_title=s.media_title,
                member_count=sum(1 for m in s.members if m.is_connected),
                is_active=s.is_active,
                is_owner=s.owner_id == user_id,
                created_at=s.created_at,
            )
            for s in sessions
        ]

    async def heartbeat(self, party_id: uuid.UUID, user_id: uuid.UUID):
        """
        Update member heartbeat to show they're still connected.

        Only updates if the user is actually a connected member of the session.
        """
        stmt = select(WatchPartyMember).where(
            WatchPartyMember.party_id == party_id,
            WatchPartyMember.user_id == user_id,
            WatchPartyMember.is_connected,
        )
        result = await self.db.execute(stmt)
        member = result.scalar_one_or_none()

        if member:
            member.last_heartbeat = datetime.now(UTC)
            await self.db.commit()

    async def _session_to_response(self, session: WatchParty) -> WatchPartyResponse:
        """Convert session model to response schema."""
        # Batch-fetch user info for all members in one query
        user_ids = [m.user_id for m in session.members]
        if user_ids:
            stmt = select(User).where(User.guid.in_(user_ids))
            result = await self.db.execute(stmt)
            users = {u.guid: u for u in result.scalars().all()}
        else:
            users = {}

        members = []
        for m in session.members:
            user = users.get(m.user_id)
            username = f"{user.first_name} {user.last_name}" if user else "Unknown"
            members.append(
                WatchPartyMemberResponse(
                    guid=m.guid,
                    user_id=m.user_id,
                    username=username,
                    is_host=m.is_host,
                    is_connected=m.is_connected,
                    last_position=m.last_position,
                    last_heartbeat=m.last_heartbeat,
                    joined_at=m.joined_at,
                )
            )

        # Compute adjusted position for late joiners
        adjusted_time = session.current_time
        if session.is_playing and session.last_sync_at:
            last_sync = session.last_sync_at
            if last_sync.tzinfo is None:
                last_sync = last_sync.replace(tzinfo=UTC)
            elapsed = (datetime.now(UTC) - last_sync).total_seconds()
            if elapsed > 0:
                adjusted_time += elapsed * session.playback_rate

        return WatchPartyResponse(
            guid=session.guid,
            party_code=session.party_code,
            name=session.name,
            owner_id=session.owner_id,
            media_id=session.media_id,
            media_type=session.media_type,
            media_title=session.media_title,
            current_time=session.current_time,
            adjusted_current_time=adjusted_time,
            is_playing=session.is_playing,
            playback_rate=session.playback_rate,
            last_sync_at=session.last_sync_at,
            is_active=session.is_active,
            allow_control=session.allow_control,
            created_at=session.created_at,
            expires_at=session.expires_at,
            members=members,
        )

    async def get_friends_sessions(
        self, user_id: uuid.UUID
    ) -> list[WatchPartyListResponse]:
        """
        Get active watch parties hosted by friends of the user.

        Args:
            user_id: ID of the current user

        Returns:
            List of active watch parties from friends
        """
        # Get friend user IDs
        friend_stmt = select(Friendship).where(
            or_(
                Friendship.requester_id == user_id,
                Friendship.addressee_id == user_id,
            ),
            Friendship.status == FriendshipStatus.accepted,
        )
        result = await self.db.execute(friend_stmt)
        friendships = result.scalars().all()

        friend_ids = []
        for f in friendships:
            if f.requester_id == user_id:
                friend_ids.append(f.addressee_id)
            else:
                friend_ids.append(f.requester_id)

        if not friend_ids:
            return []

        # Get active sessions owned by friends
        stmt = (
            select(WatchParty)
            .where(
                WatchParty.owner_id.in_(friend_ids),
                WatchParty.is_active,
                WatchParty.expires_at > datetime.now(UTC),
            )
            .options(
                selectinload(WatchParty.members),
                selectinload(WatchParty.owner),
            )
        )
        result = await self.db.execute(stmt)
        sessions = result.scalars().all()

        return [
            WatchPartyListResponse(
                guid=s.guid,
                party_code=s.party_code,
                name=s.name,
                owner_name=f"{s.owner.first_name} {s.owner.last_name}",
                media_title=s.media_title,
                member_count=sum(1 for m in s.members if m.is_connected),
                is_active=s.is_active,
                is_owner=False,
                created_at=s.created_at,
            )
            for s in sessions
        ]

    async def get_all_active_sessions(self) -> list[WatchPartyAdminResponse]:
        """
        Get all active watch parties (admin only).

        Returns:
            List of all active watch parties with details
        """
        stmt = (
            select(WatchParty)
            .where(
                WatchParty.is_active,
                WatchParty.expires_at > datetime.now(UTC),
            )
            .options(
                selectinload(WatchParty.members),
                selectinload(WatchParty.owner),
            )
            .order_by(WatchParty.created_at.desc())
        )
        result = await self.db.execute(stmt)
        sessions = result.scalars().all()

        return [
            WatchPartyAdminResponse(
                guid=s.guid,
                party_code=s.party_code,
                name=s.name,
                owner_name=f"{s.owner.first_name} {s.owner.last_name}",
                media_title=s.media_title,
                member_count=len(s.members),
                connected_count=sum(1 for m in s.members if m.is_connected),
                is_active=s.is_active,
                allow_control=s.allow_control,
                created_at=s.created_at,
                expires_at=s.expires_at,
            )
            for s in sessions
        ]

    async def admin_end_session(self, party_id: uuid.UUID):
        """
        Force-end a watch party (admin only).

        Args:
            party_id: ID of the session to end

        Raises:
            ValueError: If session not found
        """
        stmt = select(WatchParty).where(WatchParty.guid == party_id)
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise ValueError("Session not found")

        session.is_active = False
        session.ended_at = datetime.now(UTC)
        await self.db.commit()

        logger.info("Admin force-ended session %s", party_id)
