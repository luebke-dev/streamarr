"""Settings Service - Key-Value based settings management."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, TypeVar

import redis.asyncio as redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.config import settings as app_settings
from pyrate.models.setting import DEFAULT_SETTINGS, Setting

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Process-global setting cache ────────────────────────────────────────────
#
# pg_stat_statements showed ~75k `SELECT settings WHERE key=$1` per 14 days,
# almost all returning the same handful of stable values. The previous
# per-instance ``self._cache`` was thrown away every request because each
# request spins up its own SettingsService. Move to a process-global cache
# that survives request boundaries and is invalidated cross-process via
# Redis Pub/Sub when ``set()``/``delete()`` runs.

_INVALIDATE_CHANNEL = "pyrate:settings:invalidate"
_BROADCAST_ALL = "*"
_MISSING = object()  # sentinel: "no DB row for this key" — avoids re-querying

_cache: dict[str, Any] = {}
_invalidator_task: asyncio.Task | None = None
_invalidator_lock = asyncio.Lock()


async def _invalidator_loop() -> None:
    """Subscribe to the invalidation channel; evict on every message."""
    r = redis.from_url(
        app_settings.redis_url, encoding="utf-8", decode_responses=True
    )
    try:
        pubsub = r.pubsub()
        await pubsub.subscribe(_INVALIDATE_CHANNEL)
        logger.debug("Settings cache: subscribed to %s", _INVALIDATE_CHANNEL)
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            key = message.get("data")
            if key == _BROADCAST_ALL or key is None:
                _cache.clear()
            else:
                _cache.pop(key, None)
            # Re-hydrate the process-global settings snapshot so worker/
            # scheduler/web processes pick up admin changes live, not just on
            # restart. Best-effort: a failure must not kill the loop.
            try:
                from pyrate.config import load_settings_from_database

                await load_settings_from_database()
            except Exception:
                logger.exception("Settings invalidator: snapshot re-hydrate failed")
    except asyncio.CancelledError:
        raise
    except Exception:
        # Don't let pubsub hiccups crash callers — just log and clear so the
        # next start-up is a fresh state.
        logger.exception("Settings invalidator loop crashed; clearing cache")
        _cache.clear()
    finally:
        try:
            await r.aclose()
        except Exception:
            pass


async def _ensure_invalidator_running() -> None:
    global _invalidator_task
    if _invalidator_task is not None and not _invalidator_task.done():
        return
    async with _invalidator_lock:
        if _invalidator_task is not None and not _invalidator_task.done():
            return
        _invalidator_task = asyncio.create_task(
            _invalidator_loop(), name="settings-invalidator"
        )


async def _publish_invalidate(key: str) -> None:
    try:
        r = redis.from_url(
            app_settings.redis_url, encoding="utf-8", decode_responses=True
        )
        try:
            await r.publish(_INVALIDATE_CHANNEL, key)
        finally:
            await r.aclose()
    except Exception:
        # Cache invalidation is best-effort — never let a Redis blip fail a
        # settings write. The next read after the affected process's TTL or
        # restart will see the new value anyway.
        logger.warning("Settings cache invalidate publish failed", exc_info=True)


async def clear_settings_cache() -> None:
    """Clear the cache locally and broadcast a global flush.

    Useful for tests and one-off admin actions; not part of the hot path.
    """
    _cache.clear()
    await _publish_invalidate(_BROADCAST_ALL)


class SettingsService:
    """Service for managing key-value based settings."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str, default: T | None = None) -> T | None:
        """Return a setting value, falling back to ``default`` or ``DEFAULT_SETTINGS``.

        Process-global cache hits stay out of Postgres entirely; misses fetch
        once and store either the value or ``_MISSING`` so we never re-query
        a key that has no DB row.
        """
        await _ensure_invalidator_running()

        cached = _cache.get(key, _MISSING)
        if cached is not _MISSING:
            return cached

        statement = select(Setting).where(Setting.key == key)
        result = await self.session.execute(statement)
        setting = result.scalars().first()

        if setting is not None:
            _cache[key] = setting.value
            return setting.value

        # Cache the miss too — DEFAULT_SETTINGS lookups are cheap but the DB
        # round-trip behind the miss isn't.
        _cache[key] = _MISSING
        if default is not None:
            return default
        return DEFAULT_SETTINGS.get(key)

    async def set(self, key: str, value: Any) -> Setting:
        """Set a setting value. Creates or updates the setting."""
        statement = select(Setting).where(Setting.key == key)
        result = await self.session.execute(statement)
        setting = result.scalars().first()

        if setting is None:
            setting = Setting(key=key, value=value)
            self.session.add(setting)
        else:
            setting.value = value
            setting.updated_at = datetime.now(UTC)
            self.session.add(setting)

        await self.session.commit()
        await self.session.refresh(setting)

        # Local update + broadcast eviction. The local update covers the
        # common case where the same process reads after writing; the
        # broadcast handles other workers/replicas.
        _cache[key] = value
        await _publish_invalidate(key)
        logger.debug("Set setting key=%s", key)

        return setting

    async def delete(self, key: str) -> bool:
        """Delete a setting. Returns True if setting existed."""
        statement = delete(Setting).where(Setting.key == key)
        result = await self.session.execute(statement)
        await self.session.commit()

        _cache.pop(key, None)
        await _publish_invalidate(key)

        deleted = result.rowcount > 0
        if deleted:
            logger.debug("Deleted setting key=%s", key)
        else:
            logger.debug("Setting not found for deletion key=%s", key)
        return deleted

    async def get_all(self, prefix: str | None = None) -> dict[str, Any]:
        """Get all settings, optionally filtered by prefix.

        Returns a dict with all settings merged with defaults.
        """
        if prefix:
            statement = select(Setting).where(Setting.key.startswith(prefix))
        else:
            statement = select(Setting)

        result = await self.session.execute(statement)
        settings = result.scalars().all()

        # Start with defaults
        if prefix:
            all_settings = {
                k: v for k, v in DEFAULT_SETTINGS.items() if k.startswith(prefix)
            }
        else:
            all_settings = dict(DEFAULT_SETTINGS)

        # Override with stored values, populating the global cache as a
        # side-effect so subsequent ``get(key)`` calls are free.
        for setting in settings:
            all_settings[setting.key] = setting.value
            _cache[setting.key] = setting.value

        return all_settings

    async def set_many(self, settings: dict[str, Any]) -> list[Setting]:
        """Set multiple settings at once."""
        results = []
        for key, value in settings.items():
            setting = await self.set(key, value)
            results.append(setting)
        return results

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Get multiple settings by keys in a single query."""
        await _ensure_invalidator_running()

        out: dict[str, Any] = {}
        missing: list[str] = []
        for k in keys:
            cached = _cache.get(k, _MISSING)
            if cached is _MISSING:
                # Either truly absent or known-missing — distinguish via
                # explicit membership check.
                if k in _cache:  # cached miss
                    out[k] = DEFAULT_SETTINGS.get(k)
                else:
                    missing.append(k)
            else:
                out[k] = cached

        if missing:
            result = await self.session.execute(
                select(Setting).where(Setting.key.in_(missing))
            )
            found_keys: set[str] = set()
            for setting in result.scalars().all():
                out[setting.key] = setting.value
                _cache[setting.key] = setting.value
                found_keys.add(setting.key)
            for k in missing:
                if k not in found_keys:
                    _cache[k] = _MISSING
                    out[k] = DEFAULT_SETTINGS.get(k)

        return out

    # ============================================
    # Convenience methods for common setting groups
    # ============================================

    # Plugin settings (metadata providers)
    async def get_tmdb_api_key(self) -> str | None:
        """Get TMDB API key."""
        return await self.get("plugin.tmdb.api_key")

    async def get_tvdb_api_key(self) -> str | None:
        """Get TVDB API key."""
        return await self.get("plugin.tvdb.api_key")

    async def get_igdb_credentials(self) -> tuple[str | None, str | None]:
        """Get IGDB client ID and secret."""
        client_id = await self.get("plugin.igdb.client_id")
        client_secret = await self.get("plugin.igdb.client_secret")
        return client_id, client_secret

    async def get_spotify_credentials(self) -> tuple[str | None, str | None]:
        """Get Spotify client ID and secret."""
        client_id = await self.get("plugin.spotify.client_id")
        client_secret = await self.get("plugin.spotify.client_secret")
        return client_id, client_secret

    async def get_locale(self) -> str:
        """Get system locale."""
        return await self.get("system.locale") or "de-DE"

    # Library settings (plugin-based)
    async def get_library_settings(self, library: str) -> dict[str, Any]:
        """Get all settings for a specific library (movies, shows, music, etc.)."""
        return await self.get_all(f"plugin.{library}.")

    async def is_library_enabled(self, library: str) -> bool:
        """Check if a library is enabled."""
        return await self.get(f"plugin.{library}.enabled", True)

    async def get_library_path(self, library: str) -> str:
        """Get the library path."""
        return await self.get(f"plugin.{library}.library_path", f"/library/{library}")

    # OIDC settings
    async def get_oidc_settings(self) -> dict[str, Any]:
        """Get all OIDC settings."""
        return await self.get_all("oidc.")

    async def is_oidc_enabled(self) -> bool:
        """Check if OIDC is enabled."""
        return await self.get("oidc.enabled", False)

    # Email settings
    async def get_email_settings(self) -> dict[str, Any]:
        """Get all email settings."""
        return await self.get_all("email.")

    async def is_email_enabled(self) -> bool:
        """Check if email is enabled."""
        return await self.get("email.enabled", False)

    # Transcoding settings
    async def get_transcoding_settings(self) -> dict[str, Any]:
        """Get all transcoding settings."""
        return await self.get_all("transcoding.")

    async def is_transcoding_enabled(self) -> bool:
        """Check if transcoding is enabled."""
        return await self.get("transcoding.enabled", False)

    # Invite settings
    async def get_invite_settings(self) -> dict[str, Any]:
        """Get all invite settings."""
        return await self.get_all("invites.")

    # CORS settings
    async def get_cors_origins(self) -> list[str]:
        """Get allowed CORS origins."""
        return await self.get("cors.allowed_origins", [])

    # Subscription settings
    async def get_subscription_settings(self) -> dict[str, Any]:
        """Get all subscription settings."""
        return await self.get_all("subscriptions.")

    async def is_subscriptions_enabled(self) -> bool:
        """Check if subscriptions feature is enabled."""
        return await self.get("subscriptions.enabled", False)

    async def is_invites_enabled(self) -> bool:
        """Check if invite system is enabled."""
        return await self.get("invites.enabled", True)

    async def is_friends_enabled(self) -> bool:
        """Check if friends system is enabled."""
        return await self.get("friends.enabled", True)


# Standalone helper functions for use in workers/tasks
async def get_tmdb_api_key(session: AsyncSession) -> str | None:
    """Standalone helper to get TMDB API key."""
    service = SettingsService(session)
    return await service.get_tmdb_api_key()


async def get_igdb_credentials(session: AsyncSession) -> tuple[str | None, str | None]:
    """Standalone helper to get IGDB credentials."""
    service = SettingsService(session)
    return await service.get_igdb_credentials()


async def get_spotify_credentials(session: AsyncSession) -> tuple[str | None, str | None]:
    """Standalone helper to get Spotify credentials."""
    service = SettingsService(session)
    return await service.get_spotify_credentials()


async def get_locale(session: AsyncSession) -> str:
    """Standalone helper to get locale."""
    service = SettingsService(session)
    return await service.get_locale()


async def get_setting(
    session: AsyncSession, key: str, default: T | None = None
) -> T | None:
    """Standalone helper to get any setting."""
    service = SettingsService(session)
    return await service.get(key, default)
