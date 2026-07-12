"""Admin API key management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from pyrate.api.dependencies import CurrentSuperuser, DatabaseSession
from pyrate.auth.api_key_utils import (
    api_key_display_prefix,
    generate_api_key,
    hash_api_key,
)
from pyrate.models.api_key import ApiKey
from pyrate.models.user import User
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.services.activity_log import ActivityLogService

router = APIRouter()


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    user_guid: uuid.UUID | None = None


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    guid: uuid.UUID
    name: str
    key_prefix: str
    user_guid: uuid.UUID
    created_by_guid: uuid.UUID | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreateResponse(ApiKeyRead):
    key: str


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(db: DatabaseSession, current_user: CurrentSuperuser):
    """List all API keys visible to administrators."""
    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Create an API key. The raw key is returned only once."""
    user_guid = payload.user_guid or current_user.guid
    user = await db.get(User, user_guid)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    raw_key = generate_api_key()
    api_key = ApiKey(
        guid=uuid.uuid4(),
        name=payload.name,
        key_prefix=api_key_display_prefix(raw_key),
        key_hash=hash_api_key(raw_key),
        user_guid=user.guid,
        created_by_guid=current_user.guid,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="api_key.created",
            message=f"API key '{api_key.name}' was created",
            entity_type="api_key",
            entity_guid=api_key.guid,
        ),
        actor_guid=current_user.guid,
    )
    return ApiKeyCreateResponse(
        **ApiKeyRead.model_validate(api_key).model_dump(),
        key=raw_key,
    )


@router.post("/{api_key_guid}/revoke", response_model=ApiKeyRead)
async def revoke_api_key(
    api_key_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Revoke an API key without deleting its audit metadata."""
    api_key = await db.get(ApiKey, api_key_guid)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(api_key)
        await ActivityLogService(db).create(
            ActivityLogCreate(
                event_type="api_key.revoked",
                message=f"API key '{api_key.name}' was revoked",
                entity_type="api_key",
                entity_guid=api_key.guid,
            ),
            actor_guid=current_user.guid,
        )
    return api_key


@router.delete("/{api_key_guid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    api_key_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Delete an API key record."""
    api_key = await db.get(ApiKey, api_key_guid)
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    api_key_name = api_key.name
    await db.delete(api_key)
    await db.commit()
    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="api_key.deleted",
            message=f"API key '{api_key_name}' was deleted",
            entity_type="api_key",
            entity_guid=api_key_guid,
        ),
        actor_guid=current_user.guid,
    )
