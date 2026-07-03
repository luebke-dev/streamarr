"""Domain-level metrics helpers for pyrate.media."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import Counter, Gauge, Histogram

LAYOUT_RENDER_SECONDS = Histogram(
    "pyrate_layout_render_seconds",
    "Time spent rendering a page layout payload.",
    ("scope", "cache_status"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
LAYOUT_CACHE_EVENTS = Counter(
    "pyrate_layout_cache_events_total",
    "Rendered page layout cache events.",
    ("event",),
)
LAYOUT_CACHE_INVALIDATIONS = Counter(
    "pyrate_layout_cache_invalidations_total",
    "Rendered page layout cache invalidations.",
    ("reason",),
)
ARTWORK_CACHE_EVENTS = Counter(
    "pyrate_artwork_cache_events_total",
    "Artwork cache events.",
    ("event", "host"),
)
ARTWORK_CACHE_BYTES = Gauge(
    "pyrate_artwork_cache_bytes",
    "Current artwork cache size on disk.",
)
ARTWORK_CACHE_FILES = Gauge(
    "pyrate_artwork_cache_files",
    "Current artwork cache file count.",
)
DOWNLOAD_STATUS_TRANSITIONS = Counter(
    "pyrate_download_status_transitions_total",
    "Download status transitions observed by pyrate.",
    ("from_status", "to_status", "source"),
)
DOWNLOAD_RETRY_EVENTS = Counter(
    "pyrate_download_retry_events_total",
    "Download retry and fallback decisions.",
    ("event",),
)
MEDIA_ITEMS = Gauge(
    "pyrate_media_items_total",
    "Media items by type and availability status.",
    ("media_type", "availability_status"),
)
MEDIA_FILES = Gauge(
    "pyrate_media_files_total",
    "Media files by media type.",
    ("media_type",),
)
MEDIA_RELEASES = Gauge(
    "pyrate_media_releases_total",
    "Media releases by media type.",
    ("media_type",),
)
DOWNLOADS = Gauge(
    "pyrate_downloads_total",
    "Downloads by status, phase, media type, and downloader type.",
    ("status", "phase", "media_type", "downloader_type"),
)
DOWNLOAD_PROGRESS_PERCENT = Gauge(
    "pyrate_download_progress_percent",
    "Average download progress percent by status.",
    ("status",),
)
DOWNLOADERS_CONFIGURED = Gauge(
    "pyrate_downloaders_configured_total",
    "Configured download clients by type.",
    ("downloader_type",),
)
INDEXERS_CONFIGURED = Gauge(
    "pyrate_indexers_configured_total",
    "Configured indexers by type.",
    ("indexer_type",),
)
LIBRARIES_CONFIGURED = Gauge(
    "pyrate_libraries_configured_total",
    "Configured libraries by type and enabled state.",
    ("library_type", "enabled"),
)
USERS = Gauge(
    "pyrate_users_total",
    "Users by active, superuser, and email verification state.",
    ("active", "superuser", "email_verified"),
)
DEVICES = Gauge(
    "pyrate_devices_total",
    "Devices by active, trusted, and playback state.",
    ("active", "trusted", "playing"),
)
FAVORITES = Gauge(
    "pyrate_favorites_total",
    "Favorites by media type.",
    ("media_type",),
)
VIEWING_HISTORY = Gauge(
    "pyrate_viewing_history_total",
    "Viewing-history rows by media type and completion state.",
    ("media_type", "completed"),
)
NOTIFICATIONS = Gauge(
    "pyrate_notifications_total",
    "Notifications by type and status.",
    ("notification_type", "status"),
)
LISTS = Gauge(
    "pyrate_lists_total",
    "Lists by type, visibility, and active state.",
    ("list_type", "visibility", "active"),
)
MEDIA_MISSING_ARTWORK = Gauge(
    "pyrate_media_missing_artwork_total",
    "Media items missing poster or backdrop artwork.",
    ("media_type", "artwork_type"),
)
SERVICE_HEALTH = Gauge(
    "pyrate_service_health",
    "Service health where 1 is healthy and 0 is unhealthy.",
    ("component",),
)
STORAGE_BYTES = Gauge(
    "pyrate_storage_bytes",
    "Storage bytes by named path and kind.",
    ("path_name", "kind"),
)
DOWNLOADER_CLIENT_HEALTH = Gauge(
    "pyrate_downloader_client_health",
    "Downloader client API health where 1 is healthy and 0 is unhealthy.",
    ("downloader_type", "downloader_label"),
)
DOWNLOADER_CLIENT_REQUEST_SECONDS = Histogram(
    "pyrate_downloader_client_request_seconds",
    "Duration of downloader client status polling.",
    ("downloader_type", "downloader_label", "status"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
DOWNLOADER_CLIENT_JOBS = Gauge(
    "pyrate_downloader_client_jobs_total",
    "Jobs reported directly by configured downloader clients.",
    ("downloader_type", "downloader_label", "status"),
)
WEBSOCKET_CONNECTIONS = Gauge(
    "pyrate_websocket_connections",
    "Active WebSocket connections in this backend process.",
)
WEBSOCKET_ONLINE_USERS = Gauge(
    "pyrate_websocket_online_users",
    "Distinct users with active WebSocket connections in this backend process.",
)
WEBSOCKET_CONNECTED_DEVICES = Gauge(
    "pyrate_websocket_connected_devices",
    "Distinct devices with active WebSocket connections in this backend process.",
)
WEBSOCKET_SUBSCRIPTIONS = Gauge(
    "pyrate_websocket_subscriptions",
    "Active WebSocket subscriptions by resource type in this backend process.",
    ("resource_type",),
)
WEBSOCKET_CONNECTION_EVENTS = Counter(
    "pyrate_websocket_connection_events_total",
    "WebSocket connect and disconnect events.",
    ("event",),
)
WEBSOCKET_MESSAGES = Counter(
    "pyrate_websocket_messages_total",
    "WebSocket inbound messages by action.",
    ("action",),
)
WORKER_TASK_EVENTS = Counter(
    "pyrate_worker_task_events_total",
    "Task lifecycle events recorded by pyrate.",
    ("task_id", "category", "status"),
)
INDEXER_SEARCHES = Counter(
    "pyrate_indexer_searches_total",
    "Indexer search attempts.",
    ("indexer_type", "content_type", "status"),
)
INDEXER_SEARCH_SECONDS = Histogram(
    "pyrate_indexer_search_seconds",
    "Indexer search duration.",
    ("indexer_type", "content_type", "status"),
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
INDEXER_SEARCH_RESULTS = Histogram(
    "pyrate_indexer_search_results",
    "Number of results returned by indexer searches.",
    ("indexer_type", "content_type"),
    buckets=(0, 1, 2, 5, 10, 25, 50, 100, 250, 500),
)
METRICS_SAMPLER_RUNS = Counter(
    "pyrate_metrics_sampler_runs_total",
    "Periodic metrics sampler runs.",
    ("status",),
)
METRICS_SAMPLER_SECONDS = Histogram(
    "pyrate_metrics_sampler_seconds",
    "Periodic metrics sampler duration.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
METRICS_SAMPLER_LAST_SUCCESS = Gauge(
    "pyrate_metrics_sampler_last_success_timestamp_seconds",
    "Unix timestamp of the latest successful metrics sampler run.",
)


@contextmanager
def observe_layout_render(scope: str, cache_status: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        LAYOUT_RENDER_SECONDS.labels(scope=scope, cache_status=cache_status).observe(
            time.perf_counter() - started
        )


def record_layout_cache_event(event: str) -> None:
    LAYOUT_CACHE_EVENTS.labels(event=event).inc()


def record_layout_cache_invalidation(reason: str) -> None:
    LAYOUT_CACHE_INVALIDATIONS.labels(reason=reason).inc()


def record_artwork_cache_event(event: str, host: str | None = None) -> None:
    ARTWORK_CACHE_EVENTS.labels(event=event, host=host or "unknown").inc()


def set_artwork_cache_stats(file_count: int, total_bytes: int) -> None:
    ARTWORK_CACHE_FILES.set(file_count)
    ARTWORK_CACHE_BYTES.set(total_bytes)


def record_download_transition(
    from_status: str | None,
    to_status: str | None,
    source: str,
) -> None:
    DOWNLOAD_STATUS_TRANSITIONS.labels(
        from_status=from_status or "unknown",
        to_status=to_status or "unknown",
        source=source,
    ).inc()


def record_download_retry_event(event: str) -> None:
    DOWNLOAD_RETRY_EVENTS.labels(event=event).inc()


def record_worker_task_event(task_id: str, category: str, status: str) -> None:
    WORKER_TASK_EVENTS.labels(
        task_id=task_id or "unknown",
        category=category or "unknown",
        status=status or "unknown",
    ).inc()


def record_websocket_connection_event(event: str) -> None:
    WEBSOCKET_CONNECTION_EVENTS.labels(event=event).inc()


def record_websocket_message(action: str | None) -> None:
    WEBSOCKET_MESSAGES.labels(action=action or "unknown").inc()


def set_websocket_stats(
    *,
    connections: int,
    online_users: int,
    connected_devices: int,
    subscriptions_by_type: dict[str, int],
) -> None:
    WEBSOCKET_CONNECTIONS.set(connections)
    WEBSOCKET_ONLINE_USERS.set(online_users)
    WEBSOCKET_CONNECTED_DEVICES.set(connected_devices)
    WEBSOCKET_SUBSCRIPTIONS.clear()
    for resource_type, count in subscriptions_by_type.items():
        WEBSOCKET_SUBSCRIPTIONS.labels(resource_type=resource_type).set(count)


def set_inventory_stats(
    *,
    media_items: dict[tuple[str, str], int],
    media_files: dict[str, int],
    media_releases: dict[str, int],
    downloads: dict[tuple[str, str, str, str], int],
    download_progress: dict[str, float],
    downloaders: dict[str, int],
    indexers: dict[str, int],
    libraries: dict[tuple[str, str], int],
    users: dict[tuple[str, str, str], int],
    devices: dict[tuple[str, str, str], int],
    favorites: dict[str, int],
    viewing_history: dict[tuple[str, str], int],
    notifications: dict[tuple[str, str], int],
    lists: dict[tuple[str, str, str], int],
    missing_artwork: dict[tuple[str, str], int],
) -> None:
    MEDIA_ITEMS.clear()
    for (media_type, availability_status), count in media_items.items():
        MEDIA_ITEMS.labels(
            media_type=media_type,
            availability_status=availability_status,
        ).set(count)

    MEDIA_FILES.clear()
    for media_type, count in media_files.items():
        MEDIA_FILES.labels(media_type=media_type).set(count)

    MEDIA_RELEASES.clear()
    for media_type, count in media_releases.items():
        MEDIA_RELEASES.labels(media_type=media_type).set(count)

    DOWNLOADS.clear()
    for (status, phase, media_type, downloader_type), count in downloads.items():
        DOWNLOADS.labels(
            status=status,
            phase=phase,
            media_type=media_type,
            downloader_type=downloader_type,
        ).set(count)

    DOWNLOAD_PROGRESS_PERCENT.clear()
    for status, progress in download_progress.items():
        DOWNLOAD_PROGRESS_PERCENT.labels(status=status).set(progress)

    DOWNLOADERS_CONFIGURED.clear()
    for downloader_type, count in downloaders.items():
        DOWNLOADERS_CONFIGURED.labels(downloader_type=downloader_type).set(count)

    INDEXERS_CONFIGURED.clear()
    for indexer_type, count in indexers.items():
        INDEXERS_CONFIGURED.labels(indexer_type=indexer_type).set(count)

    LIBRARIES_CONFIGURED.clear()
    for (library_type, enabled), count in libraries.items():
        LIBRARIES_CONFIGURED.labels(library_type=library_type, enabled=enabled).set(count)

    USERS.clear()
    for (active, superuser, email_verified), count in users.items():
        USERS.labels(
            active=active,
            superuser=superuser,
            email_verified=email_verified,
        ).set(count)

    DEVICES.clear()
    for (active, trusted, playing), count in devices.items():
        DEVICES.labels(active=active, trusted=trusted, playing=playing).set(count)

    FAVORITES.clear()
    for media_type, count in favorites.items():
        FAVORITES.labels(media_type=media_type).set(count)

    VIEWING_HISTORY.clear()
    for (media_type, completed), count in viewing_history.items():
        VIEWING_HISTORY.labels(media_type=media_type, completed=completed).set(count)

    NOTIFICATIONS.clear()
    for (notification_type, status), count in notifications.items():
        NOTIFICATIONS.labels(
            notification_type=notification_type,
            status=status,
        ).set(count)

    LISTS.clear()
    for (list_type, visibility, active), count in lists.items():
        LISTS.labels(list_type=list_type, visibility=visibility, active=active).set(count)

    MEDIA_MISSING_ARTWORK.clear()
    for (media_type, artwork_type), count in missing_artwork.items():
        MEDIA_MISSING_ARTWORK.labels(
            media_type=media_type,
            artwork_type=artwork_type,
        ).set(count)


def set_service_health(component: str, healthy: bool) -> None:
    SERVICE_HEALTH.labels(component=component).set(1 if healthy else 0)


def set_storage_stats(path_name: str, *, total: int, used: int, free: int) -> None:
    STORAGE_BYTES.labels(path_name=path_name, kind="total").set(total)
    STORAGE_BYTES.labels(path_name=path_name, kind="used").set(used)
    STORAGE_BYTES.labels(path_name=path_name, kind="free").set(free)


def clear_downloader_client_stats() -> None:
    DOWNLOADER_CLIENT_HEALTH.clear()
    DOWNLOADER_CLIENT_JOBS.clear()


def record_downloader_client_poll(
    *,
    downloader_type: str,
    downloader_label: str,
    status: str,
    duration_seconds: float,
) -> None:
    DOWNLOADER_CLIENT_REQUEST_SECONDS.labels(
        downloader_type=downloader_type or "unknown",
        downloader_label=downloader_label or "unknown",
        status=status,
    ).observe(duration_seconds)


def set_downloader_client_health(
    *,
    downloader_type: str,
    downloader_label: str,
    healthy: bool,
) -> None:
    DOWNLOADER_CLIENT_HEALTH.labels(
        downloader_type=downloader_type or "unknown",
        downloader_label=downloader_label or "unknown",
    ).set(1 if healthy else 0)


def set_downloader_client_jobs(
    *,
    downloader_type: str,
    downloader_label: str,
    statuses: dict[str, int],
) -> None:
    for status, count in statuses.items():
        DOWNLOADER_CLIENT_JOBS.labels(
            downloader_type=downloader_type or "unknown",
            downloader_label=downloader_label or "unknown",
            status=status or "unknown",
        ).set(count)


def record_metrics_sampler(status: str, duration_seconds: float) -> None:
    METRICS_SAMPLER_RUNS.labels(status=status).inc()
    METRICS_SAMPLER_SECONDS.observe(duration_seconds)
    if status == "success":
        METRICS_SAMPLER_LAST_SUCCESS.set(time.time())


@contextmanager
def observe_indexer_search(indexer_type: str, content_type: str) -> Iterator[list[int]]:
    started = time.perf_counter()
    result_count = [0]
    status = "success"
    try:
        yield result_count
    except Exception:
        status = "error"
        raise
    finally:
        INDEXER_SEARCHES.labels(
            indexer_type=indexer_type or "unknown",
            content_type=content_type or "unknown",
            status=status,
        ).inc()
        INDEXER_SEARCH_SECONDS.labels(
            indexer_type=indexer_type or "unknown",
            content_type=content_type or "unknown",
            status=status,
        ).observe(time.perf_counter() - started)
        if status == "success":
            INDEXER_SEARCH_RESULTS.labels(
                indexer_type=indexer_type or "unknown",
                content_type=content_type or "unknown",
            ).observe(result_count[0])
