"""
Friendship Service

Verwaltet Freundschaftsanfragen und -verbindungen zwischen Benutzern.
"""

import logging
import uuid

logger = logging.getLogger(__name__)

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.friendship import Friendship, FriendshipStatus
from pyrate.models.user import User


class FriendshipService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def send_request(
        self, requester_id: uuid.UUID, addressee_email: str
    ) -> Friendship:
        """Freundschaftsanfrage an einen Benutzer per E-Mail senden"""

        # Zielbenutzer per E-Mail finden
        result = await self.db.execute(
            select(User).where(User.email == addressee_email)
        )
        addressee = result.scalar_one_or_none()

        if not addressee:
            raise ValueError("no_user")

        if addressee.guid == requester_id:
            raise ValueError("self_request")

        # Check if a connection already exists in either direction.
        existing = await self._get_pair(requester_id, addressee.guid)
        if existing:
            if existing.status == FriendshipStatus.accepted:
                raise ValueError("already_friends")
            if existing.status == FriendshipStatus.pending:
                raise ValueError("already_pending")
            if existing.status == FriendshipStatus.blocked:
                raise ValueError("blocked")

        friendship = Friendship(
            requester_id=requester_id,
            addressee_id=addressee.guid,
            status=FriendshipStatus.pending,
        )
        self.db.add(friendship)
        await self.db.commit()
        await self.db.refresh(friendship)
        logger.info("Friend request sent from %s to %s", requester_id, addressee.guid)
        return await self._load(friendship.guid)

    async def accept(
        self, friendship_id: uuid.UUID, current_user_id: uuid.UUID
    ) -> Friendship:
        """Freundschaftsanfrage annehmen"""
        friendship = await self._load(friendship_id)

        if not friendship or friendship.addressee_id != current_user_id:
            raise ValueError("not_found")
        if friendship.status != FriendshipStatus.pending:
            raise ValueError("not_pending")

        friendship.status = FriendshipStatus.accepted
        await self.db.commit()
        await self.db.refresh(friendship)
        logger.info("Friend request %s accepted by user %s", friendship_id, current_user_id)
        await self._enqueue_rec_rebuild_for_pair(
            friendship.requester_id, friendship.addressee_id
        )
        return await self._load(friendship.guid)

    async def reject(
        self, friendship_id: uuid.UUID, current_user_id: uuid.UUID
    ) -> bool:
        """Reject a friend request (deletes the entry)."""
        friendship = await self._load(friendship_id)

        if not friendship or friendship.addressee_id != current_user_id:
            raise ValueError("not_found")
        if friendship.status != FriendshipStatus.pending:
            raise ValueError("not_pending")

        await self.db.delete(friendship)
        await self.db.commit()
        logger.info("Friend request %s rejected by user %s", friendship_id, current_user_id)
        return True

    async def remove(
        self, friendship_id: uuid.UUID, current_user_id: uuid.UUID
    ) -> bool:
        """End a friendship or withdraw a pending request."""
        friendship = await self._load(friendship_id)

        if not friendship:
            raise ValueError("not_found")
        if (
            friendship.requester_id != current_user_id
            and friendship.addressee_id != current_user_id
        ):
            raise ValueError("not_found")

        was_accepted = friendship.status == FriendshipStatus.accepted
        requester_id = friendship.requester_id
        addressee_id = friendship.addressee_id
        await self.db.delete(friendship)
        await self.db.commit()
        logger.info("Friendship %s removed by user %s", friendship_id, current_user_id)
        if was_accepted:
            await self._enqueue_rec_rebuild_for_pair(requester_id, addressee_id)
        return True

    async def _enqueue_rec_rebuild_for_pair(
        self, user_a: uuid.UUID, user_b: uuid.UUID
    ) -> None:
        """Refresh both users' friend-based recommendation lists + profile
        friend_guids caches after a friendship accept/remove."""
        try:
            from pyrate.worker import rebuild_user_recommendations

            await rebuild_user_recommendations.kiq(str(user_a))
            await rebuild_user_recommendations.kiq(str(user_b))
        except Exception as e:
            logger.warning("Failed to enqueue rec rebuilds for pair: %s", e)

    async def create_accepted(
        self, user_a_id: uuid.UUID, user_b_id: uuid.UUID
    ) -> Friendship:
        """Create an already-accepted friendship directly (e.g. after invite-based registration)."""
        # Check if it already exists.
        existing = await self._get_pair(user_a_id, user_b_id)
        if existing:
            if existing.status != FriendshipStatus.accepted:
                existing.status = FriendshipStatus.accepted
                await self.db.commit()
                await self.db.refresh(existing)
            return existing

        friendship = Friendship(
            requester_id=user_a_id,
            addressee_id=user_b_id,
            status=FriendshipStatus.accepted,
        )
        self.db.add(friendship)
        await self.db.commit()
        await self.db.refresh(friendship)
        return friendship

    async def get_friends(self, user_id: uuid.UUID) -> list[Friendship]:
        """Alle akzeptierten Freundschaften eines Benutzers"""
        result = await self.db.execute(
            select(Friendship)
            .options(
                selectinload(Friendship.requester), selectinload(Friendship.addressee)
            )
            .where(
                and_(
                    or_(
                        Friendship.requester_id == user_id,
                        Friendship.addressee_id == user_id,
                    ),
                    Friendship.status == FriendshipStatus.accepted,
                )
            )
            .order_by(Friendship.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_pending_received(self, user_id: uuid.UUID) -> list[Friendship]:
        """Ausstehende eingehende Freundschaftsanfragen"""
        result = await self.db.execute(
            select(Friendship)
            .options(
                selectinload(Friendship.requester), selectinload(Friendship.addressee)
            )
            .where(
                and_(
                    Friendship.addressee_id == user_id,
                    Friendship.status == FriendshipStatus.pending,
                )
            )
            .order_by(Friendship.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_pending_sent(self, user_id: uuid.UUID) -> list[Friendship]:
        """Ausstehende gesendete Freundschaftsanfragen"""
        result = await self.db.execute(
            select(Friendship)
            .options(
                selectinload(Friendship.requester), selectinload(Friendship.addressee)
            )
            .where(
                and_(
                    Friendship.requester_id == user_id,
                    Friendship.status == FriendshipStatus.pending,
                )
            )
            .order_by(Friendship.created_at.desc())
        )
        return list(result.scalars().all())

    # --- Hilfsmethoden ---

    async def _load(self, friendship_id: uuid.UUID) -> Friendship | None:
        result = await self.db.execute(
            select(Friendship)
            .options(
                selectinload(Friendship.requester), selectinload(Friendship.addressee)
            )
            .where(Friendship.guid == friendship_id)
        )
        return result.scalar_one_or_none()

    async def _get_pair(
        self, user_a: uuid.UUID, user_b: uuid.UUID
    ) -> Friendship | None:
        result = await self.db.execute(
            select(Friendship).where(
                or_(
                    and_(
                        Friendship.requester_id == user_a,
                        Friendship.addressee_id == user_b,
                    ),
                    and_(
                        Friendship.requester_id == user_b,
                        Friendship.addressee_id == user_a,
                    ),
                )
            )
        )
        return result.scalar_one_or_none()
