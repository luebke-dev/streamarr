import logging
import uuid

from fastapi import APIRouter, Body, HTTPException, status

from pyrate.api.dependencies import CurrentSuperuser, CurrentUser, DatabaseSession
from pyrate.schemas.group import (
    BulkUserGroupAssignment,
    EffectivePermissions,
    GroupCreate,
    GroupRead,
    GroupUpdate,
    GroupWithMembers,
    UserGroupAssignment,
    UserPermissions,
    UserWithGroups,
)
from pyrate.services.group import GroupService
from pyrate.services.permission import PermissionService

logger = logging.getLogger(__name__)

router = APIRouter()


# Group CRUD Endpoints
@router.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    *,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    group_data: GroupCreate,
):
    """Create a new group (admin only)"""
    service = GroupService(db)

    # Check if group name already exists
    existing = await service.get_group_by_name(group_data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Group with name '{group_data.name}' already exists",
        )

    group = await service.create_group(group_data)
    logger.info("Admin %s created group %s", current_user.guid, group.guid)

    return await service.get_group_read_with_count(group.guid)


@router.get("", response_model=list[GroupRead])
async def list_groups(
    *,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    skip: int = 0,
    limit: int = 100,
    include_inactive: bool = False,
):
    """List all groups (admin only)"""
    service = GroupService(db)
    return await service.list_groups_with_count(
        skip=skip, limit=limit, include_inactive=include_inactive
    )


# User-Group Assignment Endpoints
# NOTE: These must be registered before /{group_id} routes to avoid
# FastAPI matching "assign" as a group_id parameter.
@router.post("/assign", status_code=status.HTTP_204_NO_CONTENT)
async def assign_user_to_group(
    *,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    assignment: UserGroupAssignment,
):
    """Assign a user to a group (admin only)"""
    service = GroupService(db)

    # Verify group exists
    group = await service.get_group(assignment.group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    await service.add_user_to_group(assignment.user_id, assignment.group_id)
    logger.info("Admin %s assigned user %s to group %s", current_user.guid, assignment.user_id, assignment.group_id)


@router.post("/assign/bulk", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_assign_users_to_group(
    *,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    assignment: BulkUserGroupAssignment,
):
    """Assign multiple users to a group (admin only)"""
    service = GroupService(db)

    # Verify group exists
    group = await service.get_group(assignment.group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    added = await service.add_users_to_group(assignment.user_ids, assignment.group_id)
    logger.info(
        "Admin %s bulk-assigned %d users to group %s (newly added: %d)",
        current_user.guid, len(assignment.user_ids), assignment.group_id, added,
    )


@router.delete("/assign", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_from_group(
    *,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    assignment: UserGroupAssignment = Body(...),
):
    """Remove a user from a group (admin only)"""
    service = GroupService(db)
    success = await service.remove_user_from_group(
        assignment.user_id, assignment.group_id
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User-group link not found",
        )
    logger.info("Admin %s removed user %s from group %s", current_user.guid, assignment.user_id, assignment.group_id)


# Individual group endpoints (must come after /assign routes)
@router.get("/{group_id}", response_model=GroupWithMembers)
async def get_group(
    *,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    group_id: uuid.UUID,
):
    """Get a specific group with member list (admin only)"""
    service = GroupService(db)
    group = await service.get_group(group_id)

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    # Get members
    members = await service.get_group_members(group_id)
    member_ids = [member.guid for member in members]

    return GroupWithMembers(
        **group.__dict__,
        member_count=len(member_ids),
        member_ids=member_ids,
    )


@router.patch("/{group_id}", response_model=GroupRead)
async def update_group(
    *,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    group_id: uuid.UUID,
    group_data: GroupUpdate,
):
    """Update a group (admin only)"""
    service = GroupService(db)

    # Check if name is being changed and if it conflicts
    if group_data.name:
        existing = await service.get_group_by_name(group_data.name)
        if existing and existing.guid != group_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Group with name '{group_data.name}' already exists",
            )

    group = await service.update_group(group_id, group_data)

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )
    logger.info("Admin %s updated group %s", current_user.guid, group_id)

    return await service.get_group_read_with_count(group.guid)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    *,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    group_id: uuid.UUID,
):
    """Delete a group (admin only)"""
    service = GroupService(db)
    success = await service.delete_group(group_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )
    logger.info("Admin %s deleted group %s", current_user.guid, group_id)


@router.get("/user/{user_id}", response_model=UserWithGroups)
async def get_user_groups(
    *,
    db: DatabaseSession,
    current_user: CurrentUser,
    user_id: uuid.UUID,
):
    """
    Get all groups for a user.
    Users can view their own groups, admins can view any user's groups.
    """
    # Check permissions
    if not current_user.is_superuser and current_user.guid != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this user's groups",
        )

    service = GroupService(db)
    result = await service.get_user_with_groups(user_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return result


@router.get("/user/{user_id}/permissions", response_model=UserPermissions)
async def get_user_permissions(
    *,
    db: DatabaseSession,
    current_user: CurrentUser,
    user_id: uuid.UUID,
):
    """
    Get computed permissions for a user.
    Users can view their own permissions, admins can view any user's permissions.
    """
    # Check permissions
    if not current_user.is_superuser and current_user.guid != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this user's permissions",
        )

    service = GroupService(db)
    return await service.compute_user_permissions(user_id)


@router.get(
    "/user/{user_id}/effective-permissions", response_model=EffectivePermissions
)
async def get_user_effective_permissions(
    *,
    db: DatabaseSession,
    current_user: CurrentUser,
    user_id: uuid.UUID,
):
    """
    Get effective permissions for a user (merged from Global > Group > User-Override).
    Users can view their own, admins can view any user's permissions.
    """
    if not current_user.is_superuser and current_user.guid != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this user's permissions",
        )

    service = PermissionService(db)
    return await service.resolve_user_permissions(user_id)
