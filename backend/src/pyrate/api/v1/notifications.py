"""
Notification API endpoints
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.auth.dependencies import get_current_superuser, get_current_user
from pyrate.database import get_db_session
from pyrate.models.notification import NotificationStatus
from pyrate.models.user import User
from pyrate.schemas.notification import (
    AdminNotificationCreate,
    NotificationBulkCreate,
    NotificationCreate,
    NotificationListResponse,
    NotificationResponse,
)
from pyrate.services.notification import (
    NotificationDispatchService,
    NotificationService,
)
from pyrate.services.settings import SettingsService

# TODO: Worker needs migration to unified models
from pyrate.worker import send_notification_email

logger = logging.getLogger(__name__)

router = APIRouter()


class NotificationProviderConfig(BaseModel):
    """Configurable outbound notification provider."""

    id: str = Field(min_length=1, max_length=80)
    type: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    config: dict = Field(default_factory=dict)


class NotificationProviderType(BaseModel):
    """Supported notification provider type and config schema."""

    type: str
    name: str
    description: str
    config_schema: dict = Field(default_factory=dict)
    supports_direct_event_dispatch: bool = True


class NotificationEventSubscription(BaseModel):
    """Event subscription mapped to one or more providers."""

    event_type: str = Field(min_length=1, max_length=120)
    provider_ids: list[str] = Field(default_factory=list)
    enabled: bool = True
    filters: dict = Field(default_factory=dict)


class NotificationEventDefinition(BaseModel):
    """Discoverable notification event shape for admin configuration."""

    event_type: str
    name: str
    description: str
    payload_schema: dict = Field(default_factory=dict)
    default_severity: str = "info"


class NotificationSettingsResponse(BaseModel):
    providers: list[NotificationProviderConfig] = Field(default_factory=list)
    event_subscriptions: list[NotificationEventSubscription] = Field(default_factory=list)


class NotificationEventDispatchRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=120)
    payload: dict = Field(default_factory=dict)


class NotificationProviderDispatchResult(BaseModel):
    provider_id: str
    status: str
    detail: str


class NotificationEventDispatchResponse(BaseModel):
    event_type: str
    results: list[NotificationProviderDispatchResult]


PROVIDER_TYPES: list[NotificationProviderType] = [
    NotificationProviderType(
        type="webhook",
        name="Webhook",
        description="POST event payloads to an HTTP endpoint.",
        config_schema={
            "url": {"type": "string", "required": True},
            "headers": {"type": "object", "required": False},
        },
    ),
    NotificationProviderType(
        type="slack",
        name="Slack",
        description="Send event summaries to a Slack incoming webhook.",
        config_schema={
            "url": {"type": "string", "required": True},
            "username": {"type": "string", "required": False},
            "channel": {"type": "string", "required": False},
        },
    ),
    NotificationProviderType(
        type="discord",
        name="Discord",
        description="Send event summaries to a Discord webhook.",
        config_schema={
            "url": {"type": "string", "required": True},
            "username": {"type": "string", "required": False},
        },
    ),
    NotificationProviderType(
        type="email",
        name="Email",
        description="Match events for persisted email notification records.",
        config_schema={
            "template": {"type": "string", "required": False},
        },
        supports_direct_event_dispatch=False,
    ),
]


EVENT_DEFINITIONS: list[NotificationEventDefinition] = [
    NotificationEventDefinition(
        event_type="activity.created",
        name="Activity Created",
        description="A durable server activity log entry was created.",
        payload_schema={
            "severity": {"type": "string", "required": False},
            "message": {"type": "string", "required": True},
            "entity_type": {"type": "string", "required": False},
            "entity_guid": {"type": "string", "required": False},
            "actor_guid": {"type": "string", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="task.failed",
        name="Task Failed",
        description="A scheduled or worker task failed.",
        payload_schema={
            "severity": {"type": "string", "required": False},
            "task_id": {"type": "string", "required": True},
            "message": {"type": "string", "required": False},
        },
        default_severity="error",
    ),
    NotificationEventDefinition(
        event_type="task.completed",
        name="Task Completed",
        description="A scheduled or worker task completed.",
        payload_schema={
            "task_id": {"type": "string", "required": True},
            "run_id": {"type": "string", "required": False},
            "message": {"type": "string", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="library.scan",
        name="Library Scan",
        description="A library scan completed.",
        payload_schema={
            "library_guid": {"type": "string", "required": False},
            "library_type": {"type": "string", "required": False},
            "discovered_count": {"type": "integer", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="library.refresh",
        name="Library Refresh",
        description="A library refresh completed.",
        payload_schema={
            "library_guid": {"type": "string", "required": False},
            "library_type": {"type": "string", "required": False},
            "discovered_count": {"type": "integer", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="metadata.manual_update",
        name="Metadata Updated",
        description="A media item's metadata was manually changed.",
        payload_schema={
            "entity_guid": {"type": "string", "required": False},
            "updated_fields": {"type": "array", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="metadata.identify_apply",
        name="Metadata Identify Applied",
        description="A provider identify result was applied to a media item.",
        payload_schema={
            "entity_guid": {"type": "string", "required": False},
            "provider": {"type": "string", "required": False},
            "provider_id": {"type": "string", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="metadata.images_update",
        name="Artwork Updated",
        description="A media item's artwork was changed.",
        payload_schema={
            "entity_guid": {"type": "string", "required": False},
            "updated_fields": {"type": "array", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="subtitle.download",
        name="Subtitle Downloaded",
        description="A subtitle provider result was attached to a media item.",
        payload_schema={
            "provider": {"type": "string", "required": True},
            "provider_id": {"type": "string", "required": True},
            "subtitle_id": {"type": "string", "required": False},
            "language": {"type": "string", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="subtitle.upload",
        name="Subtitle Uploaded",
        description="A user uploaded subtitle text for a media item.",
        payload_schema={
            "subtitle_id": {"type": "string", "required": False},
            "language": {"type": "string", "required": False},
            "format": {"type": "string", "required": False},
            "file_name": {"type": "string", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="offline.item_update",
        name="Offline Item Updated",
        description="A device offline-sync item changed state.",
        payload_schema={
            "device_id": {"type": "string", "required": False},
            "media_guid": {"type": "string", "required": True},
            "status": {"type": "string", "required": True},
        },
    ),
    NotificationEventDefinition(
        event_type="offline.sync_request",
        name="Offline Sync Requested",
        description="A media item was queued for offline availability on a device.",
        payload_schema={
            "device_id": {"type": "string", "required": False},
            "media_guid": {"type": "string", "required": True},
            "status": {"type": "string", "required": True},
        },
    ),
    NotificationEventDefinition(
        event_type="session.command",
        name="Session Command",
        description="A remote control command was sent to a device session.",
        payload_schema={
            "device_id": {"type": "string", "required": True},
            "command": {"type": "string", "required": True},
            "status": {"type": "string", "required": True},
        },
    ),
    NotificationEventDefinition(
        event_type="session.capabilities",
        name="Session Capabilities",
        description="A client device updated its playback/control capabilities.",
        payload_schema={
            "device_id": {"type": "string", "required": True},
            "supported_commands": {"type": "array", "required": False},
            "supports_play_queue": {"type": "boolean", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="session.user_add",
        name="Session User Added",
        description="A user was attached to a collaborative device session.",
        payload_schema={
            "device_id": {"type": "string", "required": True},
            "target_user_guid": {"type": "string", "required": True},
        },
    ),
    NotificationEventDefinition(
        event_type="session.user_remove",
        name="Session User Removed",
        description="A user was detached from a collaborative device session.",
        payload_schema={
            "device_id": {"type": "string", "required": True},
            "target_user_guid": {"type": "string", "required": True},
        },
    ),
    NotificationEventDefinition(
        event_type="cast.command",
        name="Cast Command",
        description="A command was sent to a configured cast target.",
        payload_schema={
            "target_id": {"type": "string", "required": True},
            "protocol": {"type": "string", "required": True},
            "command": {"type": "string", "required": True},
        },
    ),
    NotificationEventDefinition(
        event_type="cast.targets_update",
        name="Cast Targets Updated",
        description="The configured cast target registry was changed.",
        payload_schema={"count": {"type": "integer", "required": False}},
    ),
    NotificationEventDefinition(
        event_type="backup.database_export",
        name="Database Backup Exported",
        description="A database backup export was generated.",
        payload_schema={
            "table_counts": {"type": "object", "required": False},
            "include_secrets": {"type": "boolean", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="backup.database_restore",
        name="Database Backup Restored",
        description="A database backup restore was applied.",
        payload_schema={
            "table_counts": {"type": "object", "required": False},
            "delete_missing": {"type": "boolean", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="backup.media_manifest_copy",
        name="Media Manifest Copy",
        description="Media files were copied from a backup manifest.",
        payload_schema={
            "dry_run": {"type": "boolean", "required": False},
            "copied": {"type": "integer", "required": False},
            "failed": {"type": "integer", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="settings.network_update",
        name="Network Settings Updated",
        description="Network or SSL settings were changed.",
        payload_schema={
            "changed_fields": {"type": "array", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="api_key.created",
        name="API Key Created",
        description="An API key was created.",
        payload_schema={
            "entity_guid": {"type": "string", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="api_key.revoked",
        name="API Key Revoked",
        description="An API key was revoked.",
        payload_schema={
            "entity_guid": {"type": "string", "required": False},
        },
    ),
    NotificationEventDefinition(
        event_type="branding.update",
        name="Branding Updated",
        description="Public branding configuration was changed.",
        payload_schema={
            "changed_fields": {"type": "array", "required": False},
        },
    ),
]


async def _load_notification_settings(db: AsyncSession) -> NotificationSettingsResponse:
    settings = SettingsService(db)
    providers = await settings.get("notifications.providers", [])
    subscriptions = await settings.get("notifications.event_subscriptions", [])
    return NotificationSettingsResponse(
        providers=providers if isinstance(providers, list) else [],
        event_subscriptions=subscriptions if isinstance(subscriptions, list) else [],
    )


async def _load_plugin_event_definitions(
    db: AsyncSession,
) -> list[NotificationEventDefinition]:
    raw_plugins = await SettingsService(db).get("plugins.installed", [])
    if not isinstance(raw_plugins, list):
        return []

    core_event_types = {definition.event_type for definition in EVENT_DEFINITIONS}
    plugin_events: list[NotificationEventDefinition] = []
    seen_plugin_event_types: set[str] = set()
    for raw_plugin in raw_plugins:
        if not isinstance(raw_plugin, dict):
            continue
        if raw_plugin.get("enabled") is False:
            continue
        if raw_plugin.get("status") in {"disabled", "uninstalled", "failed"}:
            continue

        raw_events = raw_plugin.get("notification_events")
        if not isinstance(raw_events, list):
            continue
        for raw_event in raw_events:
            if not isinstance(raw_event, dict):
                continue
            try:
                definition = NotificationEventDefinition(**raw_event)
            except Exception:
                logger.warning(
                    "Ignoring invalid plugin notification event from plugin %s",
                    raw_plugin.get("id") or raw_plugin.get("name") or "unknown",
                )
                continue
            if (
                definition.event_type in core_event_types
                or definition.event_type in seen_plugin_event_types
                or not definition.event_type.startswith("plugin.")
            ):
                continue
            plugin_events.append(definition)
            seen_plugin_event_types.add(definition.event_type)
    return sorted(plugin_events, key=lambda definition: definition.event_type)


async def _load_owned_notification(
    notification_id: UUID,
    notification_service: NotificationService,
    current_user: User,
):
    """Load a notification or raise 404/403 if it doesn't exist or isn't owned."""
    notification = await notification_service.get_by_id(notification_id)
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )
    if notification.user_id != current_user.guid and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this notification",
        )
    return notification


@router.get("/admin/provider-types", response_model=list[NotificationProviderType])
async def list_notification_provider_types(
    _: User = Depends(get_current_superuser),
):
    """List supported outbound notification provider types."""
    return PROVIDER_TYPES


@router.get("/admin/events", response_model=list[NotificationEventDefinition])
async def list_notification_events(
    _: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db_session),
):
    """List core and plugin-provided notification event types."""
    return [*EVENT_DEFINITIONS, *await _load_plugin_event_definitions(db)]


@router.get("/admin/settings", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_superuser),
):
    """Get configurable notification providers and event subscriptions."""
    return await _load_notification_settings(db)


@router.put("/admin/settings", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    body: NotificationSettingsResponse,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_superuser),
):
    """Replace configurable notification providers and event subscriptions."""
    settings = SettingsService(db)
    provider_type_ids = {provider_type.type for provider_type in PROVIDER_TYPES}
    unknown_provider_types = sorted(
        {
            provider.type
            for provider in body.providers
            if provider.type not in provider_type_ids
        }
    )
    if unknown_provider_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported notification provider types: {', '.join(unknown_provider_types)}",
        )

    provider_ids = {provider.id for provider in body.providers}
    unknown_provider_ids = sorted(
        {
            provider_id
            for subscription in body.event_subscriptions
            for provider_id in subscription.provider_ids
            if provider_id not in provider_ids
        }
    )
    if unknown_provider_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown notification providers: {', '.join(unknown_provider_ids)}",
        )

    await settings.set(
        "notifications.providers",
        [provider.model_dump() for provider in body.providers],
    )
    await settings.set(
        "notifications.event_subscriptions",
        [subscription.model_dump() for subscription in body.event_subscriptions],
    )
    return await _load_notification_settings(db)


@router.post("/admin/dispatch-event", response_model=NotificationEventDispatchResponse)
async def dispatch_notification_event(
    body: NotificationEventDispatchRequest,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_superuser),
):
    """Dispatch a notification event to configured providers. Superuser only."""
    results = await NotificationDispatchService(db).dispatch_event(
        body.event_type,
        body.payload,
    )
    return NotificationEventDispatchResponse(event_type=body.event_type, results=results)


@router.get("/", response_model=list[NotificationListResponse])
async def get_notifications(
    skip: int = 0,
    limit: int = 100,
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """Get notifications for the current user"""
    notification_service = NotificationService(db)
    notifications, _ = await notification_service.get_user_notifications(
        user_id=current_user.guid, unread_only=unread_only, skip=skip, limit=limit
    )
    return notifications


@router.get("/unread-count", response_model=dict)
async def get_unread_count(
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """Get count of unread notifications for the current user"""
    notification_service = NotificationService(db)
    count = await notification_service.get_unread_count(user_id=current_user.guid)
    return {"count": count}


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """Get a specific notification"""
    notification_service = NotificationService(db)
    return await _load_owned_notification(notification_id, notification_service, current_user)


@router.post(
    "/", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED
)
async def create_notification(
    notification_create: NotificationCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """
    Create a notification for a user
    (Only superusers can create notifications for other users)
    """
    # Check if user is trying to create notification for someone else
    if (
        notification_create.user_id != current_user.guid
        and not current_user.is_superuser
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create notifications for other users",
        )

    notification_service = NotificationService(db)
    notification = await notification_service.create(notification_create)
    logger.info("User %s created notification %s", current_user.guid, notification.guid)

    # Queue email sending if enabled
    if notification.send_email:
        await send_notification_email.kiq(str(notification.guid))

    return notification


@router.post("/bulk", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_bulk_notifications(
    bulk_create: NotificationBulkCreate,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_superuser),
):
    """
    Create notifications for multiple users at once
    (Only superusers can use this endpoint)
    """
    notification_service = NotificationService(db)
    created_notifications = []

    for user_id in bulk_create.user_ids:
        notification_create = NotificationCreate(
            user_id=user_id,
            subject=bulk_create.subject,
            message=bulk_create.message,
            notification_type=bulk_create.notification_type,
            send_email=bulk_create.send_email,
            email_template=bulk_create.email_template,
            extra_data=bulk_create.extra_data,
        )
        notification = await notification_service.create(notification_create)
        created_notifications.append(notification)

        # Queue email sending if enabled
        if notification.send_email:
            await send_notification_email.kiq(str(notification.guid))

    logger.info("Admin sent bulk notifications to %d users", len(bulk_create.user_ids))
    return {
        "message": f"Created {len(created_notifications)} notifications",
        "count": len(created_notifications),
    }


@router.post("/admin/send", response_model=dict, status_code=status.HTTP_201_CREATED)
async def admin_send_notification(
    admin_notification: AdminNotificationCreate,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_superuser),
):
    """
    Admin endpoint to send notification to specific users or all users
    (Only superusers can use this endpoint)
    """
    notification_service = NotificationService(db, email_task=send_notification_email)
    try:
        result = await notification_service.send_admin_broadcast(admin_notification)
        logger.info("Admin sent broadcast notification: %s", admin_notification.subject)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.put("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_as_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """Mark a notification as read"""
    notification_service = NotificationService(db)
    await _load_owned_notification(notification_id, notification_service, current_user)
    notification = await notification_service.mark_as_read(notification_id)
    logger.info("User %s marked notification %s as read", current_user.guid, notification_id)
    return notification


@router.put("/mark-all-read", response_model=dict)
async def mark_all_notifications_as_read(
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """Mark all notifications as read for the current user"""
    notification_service = NotificationService(db)
    count = await notification_service.mark_all_as_read(user_id=current_user.guid)
    logger.info("User %s marked all notifications as read (%d)", current_user.guid, count)
    return {"message": f"Marked {count} notifications as read", "count": count}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a notification"""
    notification_service = NotificationService(db)
    await _load_owned_notification(notification_id, notification_service, current_user)
    await notification_service.delete(notification_id)


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_notifications(
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """Delete all notifications for the current user"""
    notification_service = NotificationService(db)
    await notification_service.delete_all_for_user(user_id=current_user.guid)


# Admin endpoints
@router.get("/admin/all", response_model=list[NotificationResponse])
async def admin_get_all_notifications(
    skip: int = 0,
    limit: int = 100,
    status_filter: NotificationStatus | None = None,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_superuser),
):
    """
    Get all notifications across all users
    (Only superusers can use this endpoint)
    """
    notification_service = NotificationService(db)
    notifications, _ = await notification_service.get_all(
        status=status_filter, skip=skip, limit=limit
    )
    return notifications
