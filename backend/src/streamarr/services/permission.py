"""Permission Service - Central permission resolver with Global > Group > User-Override priority."""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from streamarr.libraries.categories import MEDIA_TYPE_TO_CATEGORY
from streamarr.models.user import User
from streamarr.schemas.group import EffectivePermissions
from streamarr.services.group import GroupService
from streamarr.services.settings import SettingsService

# Mapping from library names used in groups to plugin setting keys
LIBRARY_TO_PLUGIN = {
    "movies": "movies",
    "series": "shows",
    "games": "games",
    "books": "books",
    "music": "music",
    "photos": "photos",
}

# Parent library category -> library permission name (SHOWS is exposed as
# "series" for historical reasons).
_CATEGORY_TO_LIBRARY = {
    "MOVIES": "movies",
    "SHOWS": "series",
    "MUSIC": "music",
    "BOOKS": "books",
    "GAMES": "games",
    "PHOTOS": "photos",
}

# Mapping from MediaType enum values to library permission names, derived from
# the canonical category map so subtypes stay in sync automatically.
MEDIA_TYPE_TO_LIBRARY = {
    mt: _CATEGORY_TO_LIBRARY[cat] for mt, cat in MEDIA_TYPE_TO_CATEGORY.items()
}

VIDEO_QUALITY_RANKS = {"sd": 1, "hd": 2, "fhd": 3, "uhd": 4}
AUDIO_QUALITY_RANKS = {"lossy": 1, "lossless": 2}

VIDEO_QUALITY_BY_RANK = {v: k for k, v in VIDEO_QUALITY_RANKS.items()}
AUDIO_QUALITY_BY_RANK = {v: k for k, v in AUDIO_QUALITY_RANKS.items()}


class PermissionService:
    """Resolves effective permissions: Global > Group > User-Override."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = SettingsService(db)
        self.group_service = GroupService(db)

    async def _get_global_permissions(self) -> dict:
        """Load global permission settings."""
        settings = await self.settings.get_all("permissions.")
        return {
            "allowed_libraries": settings.get(
                "permissions.allowed_libraries",
                ["movies", "series", "games", "books", "music", "photos"],
            ),
            "max_concurrent_streams": settings.get(
                "permissions.max_concurrent_streams", 3
            ),
            "max_game_streams": settings.get("permissions.max_game_streams", 1),
            "max_video_quality": settings.get("permissions.max_video_quality", "uhd"),
            "max_audio_quality": settings.get(
                "permissions.max_audio_quality", "lossless"
            ),
            "max_concurrent_transcodings": settings.get(
                "permissions.max_concurrent_transcodings", 2
            ),
            "offline_download_limit": settings.get(
                "permissions.offline_download_limit"
            ),
            "offline_download_period_minutes": settings.get(
                "permissions.offline_download_period_minutes", 1440
            ),
            "prefetch_limit": settings.get("permissions.prefetch_limit"),
            "prefetch_period_minutes": settings.get(
                "permissions.prefetch_period_minutes", 1440
            ),
            "on_demand_fetch_limit": settings.get(
                "permissions.on_demand_fetch_limit"
            ),
            "on_demand_fetch_period_minutes": settings.get(
                "permissions.on_demand_fetch_period_minutes", 1440
            ),
            "indexer_api_requests_limit": settings.get(
                "permissions.indexer_api_requests_limit"
            ),
            "indexer_api_requests_period_minutes": settings.get(
                "permissions.indexer_api_requests_period_minutes", 60
            ),
            "indexer_downloads_limit": settings.get(
                "permissions.indexer_downloads_limit"
            ),
            "indexer_downloads_period_minutes": settings.get(
                "permissions.indexer_downloads_period_minutes", 1440
            ),
            "playback_limit": settings.get("permissions.playback_limit"),
            "playback_period_minutes": settings.get(
                "permissions.playback_period_minutes", 1440
            ),
            "favorites_permanent": settings.get(
                "favorites.permanent", False
            ),
            "remote_access_enabled": settings.get(
                "network.remote_access_enabled", True
            ),
        }

    async def _get_enabled_libraries(self) -> set[str]:
        """Get set of globally enabled libraries (checking plugin.X.enabled)."""
        enabled = set()
        for lib_name, plugin_name in LIBRARY_TO_PLUGIN.items():
            if await self.settings.is_library_enabled(plugin_name):
                enabled.add(lib_name)
        return enabled

    async def _get_user(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.guid == user_id))
        return result.scalar_one_or_none()

    async def resolve_user_permissions(
        self, user_id: uuid.UUID
    ) -> EffectivePermissions:
        """
        Compute effective permissions for a user.

        Priority: Global (cap) > Group (merged) > User-Override
        - User-Override fields (when not None) take precedence over group
        - Group permissions are merged from all user groups
        - Global settings are always the upper bound (cap)
        - Disabled libraries (plugin.X.enabled=False) are always removed
        """
        user = await self._get_user(user_id)
        if not user:
            logger.warning("Permission resolution for non-existent user_id=%s, returning empty permissions", user_id)
            return self._empty_permissions(user_id)

        # Superusers get maximum permissions
        if user.is_superuser:
            logger.debug("Superuser permissions granted for user_id=%s", user_id)
            return await self._superuser_permissions(user_id)

        global_perms = await self._get_global_permissions()
        enabled_libraries = await self._get_enabled_libraries()
        group_perms = await self.group_service.compute_user_permissions(user_id)

        has_groups = len(group_perms.group_names) > 0
        source = "global"

        # Resolve each field: user-override → group → global
        # Libraries
        if user.allowed_libraries is not None:
            allowed_libraries = user.allowed_libraries
            source = "user_override"
        elif has_groups:
            allowed_libraries = group_perms.allowed_libraries
            source = "group"
        else:
            allowed_libraries = global_perms["allowed_libraries"]

        # Cap by global + enabled libraries
        global_libs = set(global_perms["allowed_libraries"])
        allowed_libraries = sorted(
            set(allowed_libraries) & global_libs & enabled_libraries
        )

        # Integer fields: user-override → group → global, capped by global
        max_concurrent_streams = self._resolve_int(
            user.max_concurrent_streams,
            group_perms.max_concurrent_streams if has_groups else None,
            global_perms["max_concurrent_streams"],
            cap=global_perms["max_concurrent_streams"],
        )
        max_game_streams = self._resolve_int(
            user.max_game_streams,
            group_perms.max_game_streams if has_groups else None,
            global_perms["max_game_streams"],
            cap=global_perms["max_game_streams"],
        )
        max_concurrent_transcodings = self._resolve_int(
            user.max_concurrent_transcodings,
            group_perms.max_concurrent_transcodings if has_groups else None,
            global_perms["max_concurrent_transcodings"],
            cap=global_perms["max_concurrent_transcodings"],
        )

        # Quality fields: user-override → group → global, capped by global
        max_video_quality = self._resolve_quality(
            user.max_video_quality,
            group_perms.max_video_quality if has_groups else None,
            global_perms["max_video_quality"],
            VIDEO_QUALITY_RANKS,
        )
        max_audio_quality = self._resolve_quality(
            user.max_audio_quality,
            group_perms.max_audio_quality if has_groups else None,
            global_perms["max_audio_quality"],
            AUDIO_QUALITY_RANKS,
        )

        # Rate limit fields: user-override → group → global, capped by global
        offline_download_limit, offline_download_period = self._resolve_rate_limit(
            user.offline_download_limit,
            user.offline_download_period_minutes,
            group_perms.offline_download_limit if has_groups else None,
            group_perms.offline_download_period_minutes if has_groups else None,
            global_perms["offline_download_limit"],
            global_perms["offline_download_period_minutes"],
        )
        prefetch_limit, prefetch_period = self._resolve_rate_limit(
            user.prefetch_limit,
            user.prefetch_period_minutes,
            group_perms.prefetch_limit if has_groups else None,
            group_perms.prefetch_period_minutes if has_groups else None,
            global_perms["prefetch_limit"],
            global_perms["prefetch_period_minutes"],
        )
        on_demand_fetch_limit, on_demand_fetch_period = self._resolve_rate_limit(
            user.on_demand_fetch_limit,
            user.on_demand_fetch_period_minutes,
            group_perms.on_demand_fetch_limit if has_groups else None,
            group_perms.on_demand_fetch_period_minutes if has_groups else None,
            global_perms["on_demand_fetch_limit"],
            global_perms["on_demand_fetch_period_minutes"],
        )
        indexer_api_limit, indexer_api_period = self._resolve_rate_limit(
            user.indexer_api_requests_limit,
            user.indexer_api_requests_period_minutes,
            group_perms.indexer_api_requests_limit if has_groups else None,
            group_perms.indexer_api_requests_period_minutes if has_groups else None,
            global_perms["indexer_api_requests_limit"],
            global_perms["indexer_api_requests_period_minutes"],
        )
        indexer_dl_limit, indexer_dl_period = self._resolve_rate_limit(
            user.indexer_downloads_limit,
            user.indexer_downloads_period_minutes,
            group_perms.indexer_downloads_limit if has_groups else None,
            group_perms.indexer_downloads_period_minutes if has_groups else None,
            global_perms["indexer_downloads_limit"],
            global_perms["indexer_downloads_period_minutes"],
        )
        playback_limit_val, playback_period = self._resolve_rate_limit(
            user.playback_limit,
            user.playback_period_minutes,
            group_perms.playback_limit if has_groups else None,
            group_perms.playback_period_minutes if has_groups else None,
            global_perms["playback_limit"],
            global_perms["playback_period_minutes"],
        )

        # favorites_permanent: True if ANY level says True (OR logic)
        favorites_permanent = global_perms["favorites_permanent"]
        if has_groups and group_perms.favorites_permanent:
            favorites_permanent = True
        if user.favorites_permanent is not None:
            favorites_permanent = user.favorites_permanent
        # Global True always wins (admin override)
        if global_perms["favorites_permanent"]:
            favorites_permanent = True

        remote_access_enabled = bool(global_perms["remote_access_enabled"])
        if user.remote_access_enabled is not None:
            remote_access_enabled = remote_access_enabled and bool(
                user.remote_access_enabled
            )

        access_schedules = user.access_schedules or []
        access_schedule_active = self._access_schedule_active(access_schedules)

        logger.debug(
            "Resolved permissions for user_id=%s source=%s libraries=%s groups=%s",
            user_id, source, allowed_libraries, group_perms.group_names,
        )

        return EffectivePermissions(
            user_id=user_id,
            allowed_libraries=allowed_libraries,
            max_concurrent_streams=max_concurrent_streams,
            max_game_streams=max_game_streams,
            max_video_quality=max_video_quality,
            max_audio_quality=max_audio_quality,
            max_concurrent_transcodings=max_concurrent_transcodings,
            offline_download_limit=offline_download_limit,
            offline_download_period_minutes=offline_download_period,
            prefetch_limit=prefetch_limit,
            prefetch_period_minutes=prefetch_period,
            on_demand_fetch_limit=on_demand_fetch_limit,
            on_demand_fetch_period_minutes=on_demand_fetch_period,
            indexer_api_requests_limit=indexer_api_limit,
            indexer_api_requests_period_minutes=indexer_api_period,
            indexer_downloads_limit=indexer_dl_limit,
            indexer_downloads_period_minutes=indexer_dl_period,
            playback_limit=playback_limit_val,
            playback_period_minutes=playback_period,
            favorites_permanent=favorites_permanent,
            remote_access_enabled=remote_access_enabled,
            access_schedules=access_schedules,
            access_schedule_active=access_schedule_active,
            group_names=group_perms.group_names,
            source=source,
        )

    def _resolve_int(
        self,
        user_override: int | None,
        group_value: int | None,
        global_value: int,
        cap: int,
    ) -> int:
        """Resolve an integer permission: user-override → group → global, capped by global."""
        if user_override is not None:
            return min(user_override, cap)
        if group_value is not None:
            return min(group_value, cap)
        return global_value

    def _resolve_quality(
        self,
        user_override: str | None,
        group_value: str | None,
        global_value: str | None,
        ranks: dict[str, int],
    ) -> str | None:
        """Resolve a quality permission, capped by global."""
        if global_value is None:
            return None

        global_rank = ranks.get(global_value, 0)

        if user_override is not None:
            override_rank = ranks.get(user_override, 0)
            return user_override if override_rank <= global_rank else global_value

        if group_value is not None:
            group_rank = ranks.get(group_value, 0)
            return group_value if group_rank <= global_rank else global_value

        return global_value

    def _resolve_rate_limit(
        self,
        user_limit: int | None,
        user_period: int | None,
        group_limit: int | None,
        group_period: int | None,
        global_limit: int | None,
        global_period: int,
    ) -> tuple[int | None, int]:
        """Resolve a rate limit: user-override → group → global, capped by global."""
        # Determine the effective limit and period
        if user_limit is not None:
            limit = user_limit
            period = user_period if user_period is not None else global_period
        elif group_limit is not None:
            limit = group_limit
            period = group_period if group_period is not None else global_period
        else:
            return global_limit, global_period

        # Cap by global if global is set (not None = not unlimited)
        if global_limit is not None:
            # Normalize both to per-minute rate for comparison
            effective_rate = limit / period if period > 0 else float("inf")
            global_rate = (
                global_limit / global_period if global_period > 0 else float("inf")
            )
            if effective_rate > global_rate:
                return global_limit, global_period

        return limit, period

    def _empty_permissions(self, user_id: uuid.UUID) -> EffectivePermissions:
        """Return minimal permissions for non-existent user."""
        return EffectivePermissions(
            user_id=user_id,
            allowed_libraries=[],
            max_concurrent_streams=0,
            max_game_streams=0,
            max_video_quality=None,
            max_audio_quality=None,
            max_concurrent_transcodings=0,
            offline_download_limit=0,
            offline_download_period_minutes=1440,
            prefetch_limit=0,
            prefetch_period_minutes=1440,
            on_demand_fetch_limit=0,
            on_demand_fetch_period_minutes=1440,
            indexer_api_requests_limit=0,
            indexer_api_requests_period_minutes=60,
            indexer_downloads_limit=0,
            indexer_downloads_period_minutes=1440,
            playback_limit=0,
            playback_period_minutes=1440,
            favorites_permanent=False,
            remote_access_enabled=False,
            access_schedules=[],
            access_schedule_active=False,
            group_names=[],
            source="global",
        )

    async def _superuser_permissions(
        self, user_id: uuid.UUID
    ) -> EffectivePermissions:
        """Return maximum permissions for superuser."""
        enabled_libraries = await self._get_enabled_libraries()
        return EffectivePermissions(
            user_id=user_id,
            allowed_libraries=sorted(enabled_libraries),
            max_concurrent_streams=999,
            max_game_streams=999,
            max_video_quality="uhd",
            max_audio_quality="lossless",
            max_concurrent_transcodings=999,
            offline_download_limit=None,
            offline_download_period_minutes=1,
            prefetch_limit=None,
            prefetch_period_minutes=1,
            on_demand_fetch_limit=None,
            on_demand_fetch_period_minutes=1,
            indexer_api_requests_limit=None,
            indexer_api_requests_period_minutes=1,
            indexer_downloads_limit=None,
            indexer_downloads_period_minutes=1,
            playback_limit=None,
            playback_period_minutes=1,
            favorites_permanent=False,
            remote_access_enabled=True,
            access_schedules=[],
            access_schedule_active=True,
            group_names=[],
            source="superuser",
        )

    def _access_schedule_active(self, schedules: list[dict]) -> bool:
        """Return True when there is no schedule or now falls inside one."""
        if not schedules:
            return True
        now = datetime.now()
        current_day = now.strftime("%A").lower()
        current_hour = now.hour
        for schedule in schedules:
            if not isinstance(schedule, dict):
                continue
            if schedule.get("day_of_week") != current_day:
                continue
            start_hour = schedule.get("start_hour", 0)
            end_hour = schedule.get("end_hour", 24)
            if start_hour <= current_hour < end_hour:
                return True
        return False

    # Convenience check methods

    async def check_library_access(
        self, user_id: uuid.UUID, library_type: str
    ) -> bool:
        perms = await self.resolve_user_permissions(user_id)
        allowed = library_type in perms.allowed_libraries
        if not allowed:
            logger.warning("Library access denied: user_id=%s library=%s", user_id, library_type)
        return allowed

    async def check_video_quality(
        self, user_id: uuid.UUID, requested_quality: str
    ) -> bool:
        perms = await self.resolve_user_permissions(user_id)
        if not perms.max_video_quality:
            logger.warning("Video quality denied (no quality set): user_id=%s requested=%s", user_id, requested_quality)
            return False
        max_rank = VIDEO_QUALITY_RANKS.get(perms.max_video_quality, 0)
        requested_rank = VIDEO_QUALITY_RANKS.get(requested_quality, 0)
        allowed = requested_rank <= max_rank
        if not allowed:
            logger.warning("Video quality denied: user_id=%s requested=%s max=%s", user_id, requested_quality, perms.max_video_quality)
        return allowed

    async def check_audio_quality(
        self, user_id: uuid.UUID, requested_quality: str
    ) -> bool:
        perms = await self.resolve_user_permissions(user_id)
        if not perms.max_audio_quality:
            logger.warning("Audio quality denied (no quality set): user_id=%s requested=%s", user_id, requested_quality)
            return False
        max_rank = AUDIO_QUALITY_RANKS.get(perms.max_audio_quality, 0)
        requested_rank = AUDIO_QUALITY_RANKS.get(requested_quality, 0)
        allowed = requested_rank <= max_rank
        if not allowed:
            logger.warning("Audio quality denied: user_id=%s requested=%s max=%s", user_id, requested_quality, perms.max_audio_quality)
        return allowed
