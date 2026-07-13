from fastapi import APIRouter

from streamarr.api.v1.activity_logs import router as activity_logs_router
from streamarr.api.v1.api_keys import router as api_keys_router
from streamarr.api.v1.attachments import router as attachments_router
from streamarr.api.v1.auth import router as auth_router
from streamarr.api.v1.backups import router as backups_router
from streamarr.api.v1.banners import router as banners_router
from streamarr.api.v1.branding import router as branding_router
from streamarr.api.v1.cast import router as cast_router
from streamarr.api.v1.chapters import router as chapters_router
from streamarr.api.v1.client_logs import router as client_logs_router
from streamarr.api.v1.computing import router as computing_router
from streamarr.api.v1.devices import router as devices_router
from streamarr.api.v1.downloaders import router as downloaders_router
from streamarr.api.v1.downloads import router as downloads_router
from streamarr.api.v1.environment import router as environment_router
from streamarr.api.v1.favorites import router as favorites_router
from streamarr.api.v1.filters import router as filters_router
from streamarr.api.v1.friends import router as friends_router
from streamarr.api.v1.game_runtimes import router as game_runtimes_router
from streamarr.api.v1.genres import router as genres_router
from streamarr.api.v1.groups import router as groups_router
from streamarr.api.v1.indexers import router as indexers_router
from streamarr.api.v1.install import router as install_router
from streamarr.api.v1.invites import router as invites_router
from streamarr.api.v1.libraries import router as libraries_router
from streamarr.api.v1.lightrays import router as lightrays_router
from streamarr.api.v1.lists import (
    collections_router,
    playlists_router,
)
from streamarr.api.v1.lists import (
    router as lists_router,
)
from streamarr.api.v1.mass_operations import router as mass_operations_router
from streamarr.api.v1.localization import router as localization_router
from streamarr.api.v1.lyrics import router as lyrics_router
from streamarr.api.v1.media import router as media_router
from streamarr.api.v1.media_markers import router as media_markers_router
from streamarr.api.v1.metadata import router as metadata_router
from streamarr.api.v1.notifications import router as notifications_router
from streamarr.api.v1.overlays import router as overlays_router
from streamarr.api.v1.page_layouts import router as page_layouts_router
from streamarr.api.v1.parties import router as parties_router
from streamarr.api.v1.persons import router as persons_router
from streamarr.api.v1.platforms import router as platforms_router
from streamarr.api.v1.play import router as play_router
from streamarr.api.v1.plugins import router as plugins_router
from streamarr.api.v1.search import router as search_router
from streamarr.api.v1.sessions import router as sessions_router
from streamarr.api.v1.settings import router as settings_router
from streamarr.api.v1.smart_collections import router as smart_collections_router
from streamarr.api.v1.stream import router as stream_router
from streamarr.api.v1.subscriptions import router as subscriptions_router
from streamarr.api.v1.subtitles import router as subtitles_router
from streamarr.api.v1.suggestions import router as suggestions_router
from streamarr.api.v1.system import router as system_router
from streamarr.api.v1.tasks import router as tasks_router
from streamarr.api.v1.trailers import router as trailers_router
from streamarr.api.v1.user_data import router as user_data_router
from streamarr.api.v1.users import router as users_router
from streamarr.api.v1.viewing_history import router as viewing_history_router
from streamarr.api.v1.vouchers import router as vouchers_router
from streamarr.api.v1.webhooks import router as webhooks_router
from streamarr.api.v1.ws import router as ws_router

router = APIRouter()

# Authentication routes (no prefix, directly under /api/v1)
router.include_router(auth_router)

# Installation routes (no prefix, directly under /api/v1)
router.include_router(install_router, prefix="/install", tags=["installation"])

router.include_router(activity_logs_router, prefix="/activity-logs", tags=["activity-logs"])
router.include_router(api_keys_router, prefix="/api-keys", tags=["api-keys"])
router.include_router(backups_router, prefix="/backups", tags=["backups"])
router.include_router(banners_router, prefix="/banners", tags=["banners"])
router.include_router(branding_router, prefix="/branding", tags=["branding"])
router.include_router(cast_router, prefix="/cast", tags=["cast"])
router.include_router(client_logs_router, prefix="/client-logs", tags=["client-logs"])
router.include_router(collections_router, prefix="/collections", tags=["collections"])
router.include_router(downloaders_router, prefix="/downloaders", tags=["downloaders"])
router.include_router(devices_router, prefix="/devices", tags=["devices"])
router.include_router(environment_router, prefix="/environment", tags=["environment"])
router.include_router(favorites_router, prefix="/favorites", tags=["favorites"])
router.include_router(
    game_runtimes_router, prefix="/game-runtimes", tags=["game-runtimes"]
)
router.include_router(filters_router, prefix="/filters", tags=["filters"])
router.include_router(libraries_router, prefix="/libraries", tags=["libraries"])
router.include_router(lightrays_router, prefix="/lightrays", tags=["lightrays"])
router.include_router(localization_router, prefix="/localization", tags=["localization"])
router.include_router(media_router, prefix="/media", tags=["media"])
router.include_router(attachments_router, prefix="/media", tags=["attachments"])
router.include_router(chapters_router, prefix="/media", tags=["chapters"])
router.include_router(lyrics_router, prefix="/media", tags=["lyrics"])
router.include_router(media_markers_router, prefix="/media", tags=["media-markers"])
router.include_router(subtitles_router, prefix="/media", tags=["subtitles"])
router.include_router(user_data_router, prefix="/media", tags=["user-data"])
router.include_router(play_router, prefix="/play", tags=["play"])
router.include_router(playlists_router, prefix="/playlists", tags=["playlists"])
router.include_router(plugins_router, prefix="/plugins", tags=["plugins"])
router.include_router(stream_router, prefix="/stream", tags=["stream"])
router.include_router(suggestions_router, prefix="/suggestions", tags=["suggestions"])
router.include_router(system_router, prefix="/system", tags=["system"])
router.include_router(trailers_router, prefix="/trailers", tags=["trailers"])
router.include_router(indexers_router, prefix="/indexers", tags=["indexers"])
router.include_router(downloads_router, prefix="/downloads", tags=["downloads"])
router.include_router(genres_router, prefix="/genres", tags=["genres"])
router.include_router(groups_router, prefix="/groups", tags=["groups"])
router.include_router(persons_router, prefix="/persons", tags=["persons"])
router.include_router(platforms_router, prefix="/platforms", tags=["platforms"])
router.include_router(users_router, prefix="/users", tags=["users"])
router.include_router(lists_router, prefix="/lists", tags=["lists"])
router.include_router(
    notifications_router, prefix="/notifications", tags=["notifications"]
)
router.include_router(invites_router, prefix="/invites", tags=["invites"])
router.include_router(friends_router, prefix="/friends", tags=["friends"])
router.include_router(computing_router, prefix="/computing", tags=["computing"])
router.include_router(metadata_router, prefix="/metadata", tags=["metadata"])

router.include_router(search_router, prefix="/search", tags=["search"])
router.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
router.include_router(settings_router, prefix="/settings", tags=["settings"])
router.include_router(subscriptions_router)
router.include_router(vouchers_router)
router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
router.include_router(
    viewing_history_router, prefix="/viewing-history", tags=["viewing-history"]
)
router.include_router(
    parties_router, prefix="/parties", tags=["parties"]
)
router.include_router(
    page_layouts_router, prefix="/page-layouts", tags=["page-layouts"]
)

router.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])

# Smart-collection / overlay / mass-operation admin APIs
router.include_router(
    smart_collections_router,
    prefix="/smart-collections",
    tags=["smart-collections"],
)
router.include_router(
    overlays_router, prefix="/overlays", tags=["overlays"]
)
router.include_router(
    mass_operations_router,
    prefix="/mass-operations",
    tags=["mass-operations"],
)

# WebSocket endpoint (no additional prefix, will be /api/ws)
router.include_router(ws_router, tags=["websocket"])
