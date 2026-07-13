"""Quality profile resolution + upgrade-decision primitives (Subsystem 1).

Owns: the per-media-type (and optional favorites-variant) QualityProfile,
parsing a release/file onto the canonical ladder, and the cutoff /
"is an upgrade wanted" decisions consumed by the favorites backfill,
RSS sync and the periodic upgrade scan.

Profiles are global per media type (mirroring the legacy
``scoring.config.{type}`` pattern) — there is no per-item profile. Which
profile applies is derived from ``media_item.media_type`` plus whether the
item is favorite-monitored (the ``monitored``/``monitored_source`` columns
written by Subsystem 2; read directly here to avoid a hard dependency).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.libraries import get_plugin_instance
from streamarr.libraries.categories import (
    DOWNLOADABLE_CATEGORIES,
    MEDIA_TYPE_TO_CATEGORY,
)
from streamarr.libraries.quality import (
    QualityInfo,
    QualityKind,
    canonical_rank,
    kind_for_media_type,
    parse_quality,
    qualities_for_media_type,
)
from streamarr.models.media import MediaFile, MediaItem, MediaRelease
from streamarr.schemas.scoring import QualityProfile

logger = logging.getLogger(__name__)

# media_type -> library plugin key (derived from the canonical category map;
# only the downloadable categories carry a plugin / quality profile).
_PLUGIN_KEY = {
    mt: cat
    for mt, cat in MEDIA_TYPE_TO_CATEGORY.items()
    if cat in DOWNLOADABLE_CATEGORIES
}

# media_type -> profile/settings key segment (lowercased plugin key).
_PROFILE_TYPE = {mt: cat.lower() for mt, cat in _PLUGIN_KEY.items()}

PROFILE_TYPES = ("movies", "shows", "music", "books", "games")

# Sensible default cutoff per ladder kind (upgrades target this rung).
_DEFAULT_CUTOFF = {
    QualityKind.VIDEO: "webdl-1080p",
    QualityKind.AUDIO: "lossless",
    QualityKind.BOOK: "epub",
    QualityKind.AUDIOBOOK: "m4b-audiobook",
    QualityKind.GAME: "standard",
}


def _media_type_name(media_type: Any) -> str:
    return str(getattr(media_type, "value", media_type) or "").upper()


def profile_type_for(media_type: Any) -> str:
    return _PROFILE_TYPE.get(_media_type_name(media_type), "movies")


def plugin_key_for(media_type: Any) -> str:
    """Library plugin key for a media type (MOVIES/SHOWS/MUSIC/BOOKS/GAMES)."""
    return _PLUGIN_KEY.get(_media_type_name(media_type), "")


def _plugin_for(media_type: Any):
    return get_plugin_instance(plugin_key_for(media_type))


def default_profile(media_type: Any) -> QualityProfile:
    """All canonical rungs allowed, cutoff at a sensible mid/high rung."""
    defs = qualities_for_media_type(media_type)
    kind = kind_for_media_type(media_type)
    cutoff = _DEFAULT_CUTOFF.get(kind, defs[-1].id if defs else None)
    ids = {d.id for d in defs}
    if cutoff not in ids and defs:
        cutoff = defs[-1].id
    from streamarr.schemas.scoring import QualityItem

    return QualityProfile(
        name="default",
        items=[QualityItem(id=d.id, allowed=True) for d in defs],
        cutoff=cutoff,
        upgrade_allowed=True,
        scoring=None,
    )


class QualityProfileService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ----- profile resolution ------------------------------------------- #

    @staticmethod
    def settings_key(profile_type: str, *, favorites: bool) -> str:
        return (
            f"quality.profile.favorites.{profile_type}"
            if favorites
            else f"quality.profile.{profile_type}"
        )

    async def _load_profile(
        self, profile_type: str, *, favorites: bool
    ) -> QualityProfile | None:
        from streamarr.services.settings import SettingsService

        try:
            raw = await SettingsService(self.db).get(
                self.settings_key(profile_type, favorites=favorites), None
            )
        except Exception as e:  # pragma: no cover - settings backend hiccup
            logger.warning("Could not load quality profile %s: %s", profile_type, e)
            return None
        if not raw:
            return None
        try:
            return QualityProfile.model_validate(raw)
        except Exception as e:
            logger.warning("Invalid quality profile %s, ignoring: %s", profile_type, e)
            return None

    async def get_profile(
        self, media_type: Any, *, favorite: bool
    ) -> QualityProfile:
        """Precedence: favorites profile (if favorite & configured) >
        standard per-type profile > built-in default."""
        ptype = profile_type_for(media_type)
        if favorite:
            fav = await self._load_profile(ptype, favorites=True)
            if fav is not None:
                return fav
        std = await self._load_profile(ptype, favorites=False)
        if std is not None:
            return std
        return default_profile(media_type)

    @staticmethod
    def is_favorite_monitored(media_item: MediaItem) -> bool:
        """Read S2's monitoring columns directly (no service dependency)."""
        return bool(
            getattr(media_item, "monitored", False)
            and getattr(media_item, "monitored_source", None) == "favorite"
        )

    async def resolve_profile(
        self, media_item: MediaItem, *, favorite: bool | None = None
    ) -> QualityProfile:
        if favorite is None:
            favorite = self.is_favorite_monitored(media_item)
        return await self.get_profile(media_item.media_type, favorite=favorite)

    async def effective(
        self, media_item: MediaItem
    ) -> tuple[QualityProfile, bool]:
        """Return (profile, is_explicit). ``is_explicit`` is True only when a
        profile is actually configured in settings (favorites variant wins for
        favorite-monitored items). When False the built-in default is returned
        and callers should preserve legacy (pure-additive) behaviour."""
        ptype = profile_type_for(media_item.media_type)
        if self.is_favorite_monitored(media_item):
            fav = await self._load_profile(ptype, favorites=True)
            if fav is not None:
                return fav, True
        std = await self._load_profile(ptype, favorites=False)
        if std is not None:
            return std, True
        return default_profile(media_item.media_type), False

    def to_scoring_preferences(self, profile: QualityProfile) -> dict | None:
        """The additive within-rung tiebreaker config (or None = defaults)."""
        return profile.scoring or None

    # ----- quality parsing ---------------------------------------------- #

    async def parse_release_quality(
        self, release: MediaRelease, media_type: Any
    ) -> QualityInfo:
        metadata = release.release_metadata
        if not metadata:
            plugin = _plugin_for(media_type)
            if plugin is not None:
                try:
                    metadata = await plugin.extract_release_metadata(release.title)
                except Exception as e:  # pragma: no cover
                    logger.debug("extract_release_metadata failed: %s", e)
                    metadata = {}
        return parse_quality(
            metadata or {}, media_type=media_type, title=release.title
        )

    def parse_file_quality(
        self, media_file: MediaFile, media_type: Any
    ) -> QualityInfo:
        """Prefer the persisted canonical rung (set at import), else
        derive a best-effort rung from probe info."""
        kind = kind_for_media_type(media_type)
        from streamarr.libraries.quality import quality_def

        # Trust a persisted canonical rung id (written by
        # link_media_file_to_release) — do NOT re-parse it.
        if media_file.quality:
            d = quality_def(kind, media_file.quality)
            if d is not None:
                return QualityInfo(
                    id=d.id, label=d.label, kind=kind,
                    rank=canonical_rank(kind, d.id), revision=0,
                )

        # Derive a metadata dict from the probed file.
        md: dict[str, Any] = {}
        if media_file.format:
            md["format"] = media_file.format
        if media_file.bitrate:
            md["bitrate"] = media_file.bitrate
        if kind is QualityKind.VIDEO:
            h = media_file.height or 0
            if h >= 2000:
                md["resolution"] = "2160p"
            elif h >= 1000:
                md["resolution"] = "1080p"
            elif h >= 700:
                md["resolution"] = "720p"
            elif h > 0:
                md["resolution"] = "480p"
            q = (media_file.quality or "").lower()
            for src in ("remux", "bluray", "web-dl", "webrip", "hdtv", "dvd"):
                if src in q:
                    md["source"] = src
                    md["is_remux"] = src == "remux"
                    break
        return parse_quality(md, media_type=media_type, title="")

    # ----- profile ranking ---------------------------------------------- #

    @staticmethod
    def _allowed_order(profile: QualityProfile) -> list[str]:
        return [it.id for it in profile.items if it.allowed]

    def profile_position(
        self, profile: QualityProfile, quality_id: str
    ) -> int | None:
        """Index in the profile's allowed list (None if disallowed/absent)."""
        order = self._allowed_order(profile)
        try:
            return order.index(quality_id)
        except ValueError:
            return None

    # ----- current file selection --------------------------------------- #

    async def best_existing_file(
        self, media_item_guid: uuid.UUID
    ) -> MediaFile | None:
        """Public: the current best file for an item (upgrade target)."""
        return await self._best_existing_file(media_item_guid)

    async def _best_existing_file(
        self, media_item_guid: uuid.UUID
    ) -> MediaFile | None:
        res = await self.db.execute(
            select(MediaFile).where(
                MediaFile.media_item_guid == media_item_guid
            )
        )
        files = list(res.scalars().all())
        if not files:
            return None

        def _key(mf: MediaFile) -> tuple:
            rank = mf.quality_rank if mf.quality_rank is not None else -1
            imported = mf.imported_at or mf.created_at
            return (rank, imported)

        return max(files, key=_key)

    # ----- decision primitives (the cross-subsystem contract) ----------- #

    async def cutoff_met(self, media_item: MediaItem) -> bool:
        """True when the current best file already meets/exceeds the cutoff
        of the item's effective profile (no upgrade should be attempted)."""
        profile = await self.resolve_profile(media_item)
        if profile.cutoff is None:
            return True
        cur = await self._best_existing_file(media_item.guid)
        if cur is None:
            return False  # nothing yet -> acquisition, not an upgrade
        cur_q = self.parse_file_quality(cur, media_item.media_type)
        cur_pos = self.profile_position(profile, cur_q.id)
        cut_pos = self.profile_position(profile, profile.cutoff)
        if cur_pos is None or cut_pos is None:
            return False
        return cur_pos >= cut_pos

    async def is_upgrade_wanted(
        self,
        media_item: MediaItem,
        candidate_release: MediaRelease,
        *,
        current_file: MediaFile | None = None,
    ) -> bool:
        """True iff ``candidate_release`` is a strict improvement within the
        item's effective profile and the cutoff is not already met. A
        proper/repack of the same rung also counts as an upgrade."""
        profile = await self.resolve_profile(media_item)
        if not profile.upgrade_allowed:
            return False

        cand_q = await self.parse_release_quality(
            candidate_release, media_item.media_type
        )
        cand_pos = self.profile_position(profile, cand_q.id)
        if cand_pos is None:
            return False  # candidate not allowed by the profile

        cur = current_file or await self._best_existing_file(media_item.guid)
        if cur is None:
            return False  # no existing file -> first acquisition, not upgrade

        cur_q = self.parse_file_quality(cur, media_item.media_type)
        cur_pos = self.profile_position(profile, cur_q.id)
        if cur_pos is None:
            return True  # current quality not allowed -> any allowed is better

        cut_pos = self.profile_position(profile, profile.cutoff) if profile.cutoff else None

        if cand_pos > cur_pos:
            # Strictly better rung; only if cutoff not already met.
            if cut_pos is not None and cur_pos >= cut_pos:
                return False
            return True
        if cand_pos == cur_pos and cand_q.revision > cur_q.revision:
            # Same rung, newer revision (proper/repack) -> upgrade even at cutoff.
            return True
        return False

    # ----- linkage / persistence ---------------------------------------- #

    async def link_media_file_to_release(
        self, media_file: MediaFile, release: MediaRelease, media_type: Any
    ) -> None:
        """Persist which release a file came from + its parsed quality, so
        future cutoff/upgrade checks are cheap and stable. Caller commits."""
        info = await self.parse_release_quality(release, media_type)
        media_file.source_release_guid = release.guid
        media_file.quality = info.id
        media_file.quality_rank = info.rank
        try:
            media_file.quality_score = float(release.score or 0)
        except (TypeError, ValueError):
            media_file.quality_score = 0.0
        await self.db.flush()
