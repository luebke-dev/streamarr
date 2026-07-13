"""API endpoints for the friendship system."""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from streamarr.api.dependencies import CurrentUser, DatabaseSession
from streamarr.services.friendship import FriendshipService

router = APIRouter()


# --- Schemas ---


class FriendRequestCreate(BaseModel):
    email: EmailStr


class FriendUserRead(BaseModel):
    guid: uuid.UUID
    email: str
    first_name: str
    last_name: str
    preferred_username: str | None = None
    picture: str | None = None

    model_config = {"from_attributes": True}


class FriendshipRead(BaseModel):
    guid: uuid.UUID
    status: str
    requester: FriendUserRead
    addressee: FriendUserRead

    model_config = {"from_attributes": True}


# --- Endpunkte ---


@router.post(
    "/request", response_model=FriendshipRead, status_code=status.HTTP_201_CREATED
)
async def send_friend_request(
    body: FriendRequestCreate,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Freundschaftsanfrage per E-Mail senden"""
    service = FriendshipService(db)
    try:
        friendship = await service.send_request(
            requester_id=current_user.guid,
            addressee_email=body.email,
        )
    except ValueError as e:
        error_map = {
            "no_user": (404, "No user found with this email address"),
            "self_request": (400, "You cannot send a friend request to yourself"),
            "already_friends": (409, "You are already friends with this user"),
            "already_pending": (
                409,
                "A friend request to this user is already pending",
            ),
            "blocked": (409, "Cannot send a friend request to this user"),
        }
        code, detail = error_map.get(str(e), (400, "Could not send friend request"))
        raise HTTPException(status_code=code, detail=detail)

    return FriendshipRead.model_validate(friendship)


@router.get("", response_model=list[FriendshipRead])
async def list_friends(
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Alle akzeptierten Freundschaften des aktuellen Benutzers"""
    service = FriendshipService(db)
    friends = await service.get_friends(current_user.guid)
    return [FriendshipRead.model_validate(f) for f in friends]


@router.get("/pending", response_model=list[FriendshipRead])
async def list_pending_requests(
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Eingehende ausstehende Freundschaftsanfragen"""
    service = FriendshipService(db)
    requests = await service.get_pending_received(current_user.guid)
    return [FriendshipRead.model_validate(r) for r in requests]


@router.get("/sent", response_model=list[FriendshipRead])
async def list_sent_requests(
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Gesendete ausstehende Freundschaftsanfragen"""
    service = FriendshipService(db)
    requests = await service.get_pending_sent(current_user.guid)
    return [FriendshipRead.model_validate(r) for r in requests]


@router.post("/{friendship_id}/accept", response_model=FriendshipRead)
async def accept_friend_request(
    friendship_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Freundschaftsanfrage annehmen"""
    service = FriendshipService(db)
    try:
        friendship = await service.accept(friendship_id, current_user.guid)
    except ValueError as e:
        detail_map = {
            "not_found": "Friend request not found",
            "not_pending": "This request is no longer pending",
        }
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail_map.get(str(e), "Could not accept request"),
        )
    return FriendshipRead.model_validate(friendship)


@router.post("/{friendship_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_friend_request(
    friendship_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Freundschaftsanfrage ablehnen"""
    service = FriendshipService(db)
    try:
        await service.reject(friendship_id, current_user.guid)
    except ValueError as e:
        detail_map = {
            "not_found": "Friend request not found",
            "not_pending": "This request is no longer pending",
        }
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail_map.get(str(e), "Could not reject request"),
        )


@router.delete("/{friendship_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_friend(
    friendship_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """End a friendship or withdraw a pending request."""
    service = FriendshipService(db)
    try:
        await service.remove(friendship_id, current_user.guid)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Friendship not found",
        )
