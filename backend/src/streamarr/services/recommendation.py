"""Recommendation service.

Produces per-user personalised content rows as **System Lists** keyed by
`update_source` values like `rec:for_you:movies`, `rec:top_picks:shows`,
`rec:because:<anchor>:movies`, `rec:friends_watching:movies`. Read consumers
use the existing `/api/lists` endpoints — nothing new to query.

Pipeline per (user, media_type):
    1. Build/refresh UserProfileVector (genre / cast / language / friends).
    2. Retrieve ~200 candidates from TMDB similar/recommendations + SQL
       content-based + friend activity + trending fallback.
    3. Score and rank via weighted feature sum.
    4. Bulk-replace into the user's system list.
"""

from __future__ import annotations

import json
import logging
import math
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import redis.asyncio as redis
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamarr.config import settings
from streamarr.metadata.tmdb import TMDB as TmdbClient
from streamarr.models.friendship import Friendship, FriendshipStatus
from streamarr.models.list import (
    List,
    ListItem,
    ListItemType,
    ListType,
    ListVisibility,
)
from streamarr.models.media import (
    MediaExternalId,
    MediaItem,
    MediaType,
    media_genre_table,
)
from streamarr.models.person import MediaCast
from streamarr.models.recommendation import UserProfileVector
from streamarr.models.user import User
from streamarr.models.viewing_history import ViewingHistory
from streamarr.services.list import ListService

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Ranker weights — tunable via settings.recommendations.* at runtime.
DEFAULT_WEIGHTS = {
    "genre_affinity": 0.30,
    "content_similarity": 0.18,
    "external_rank": 0.12,
    "friend_signal": 0.12,
    "popularity_decay": 0.08,
    "cast_overlap": 0.07,
    "language_match": 0.05,
    "quality_match": 0.05,
    "recency_bonus": 0.03,
}

TMDB_SIMILAR_CACHE_TTL = 7 * 24 * 3600  # 7 days
ONDEMAND_REBUILD_DEBOUNCE = 5 * 60  # 5 min

# Map streamarr MediaType → (tmdb_segment, list_item_type)
MEDIA_TYPE_MAP = {
    "MOVIES": ("movie", ListItemType.MOVIE),
    "SHOWS": ("tv", ListItemType.SHOW),
}


@dataclass
class _Candidate:
    """Scored candidate."""

    guid: uuid.UUID
    score: float
    anchor_guid: uuid.UUID | None = None


def _u(value: str | uuid.UUID) -> uuid.UUID:
    return uuid.UUID(value) if isinstance(value, str) else value


class RecommendationService:
    """Per-user recommendation builder. Writes to SYSTEM lists."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._redis: redis.Redis | None = None
        self._list_service = ListService(db)
        self._tmdb: TmdbClient | None = None

    # ------------------------------------------------------------------
    # Redis + external caching
    # ------------------------------------------------------------------
    async def _get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
        return self._redis

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._redis = None

    async def _get_tmdb(self) -> TmdbClient:
        if self._tmdb is None:
            from streamarr.services import get_tmdb_api_key

            api_key = await get_tmdb_api_key(self.db)
            self._tmdb = TmdbClient(api_key=api_key)
        return self._tmdb

    async def tmdb_similar_cached(
        self, tmdb_id: str, media_type_segment: str
    ) -> list[str]:
        """Fetch & cache TMDB similar + recommendations merged (max 40 ids)."""
        rds = await self._get_redis()
        key = f"recs:external_similar:tmdb:{media_type_segment}:{tmdb_id}"
        cached = await rds.get(key)
        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                pass

        tmdb = await self._get_tmdb()
        ids: list[str] = []
        try:
            if media_type_segment == "movie":
                sim = await tmdb.get_movie_similar(tmdb_id) or {}
                rec = await tmdb.get_movie_recommendations(tmdb_id) or {}
            else:
                sim = await tmdb.get_show_similar(tmdb_id) or {}
                rec = await tmdb.get_show_recommendations(tmdb_id) or {}
            for page in (sim, rec):
                for r in (page.get("results") or [])[:20]:
                    if r.get("id") and str(r["id"]) not in ids:
                        ids.append(str(r["id"]))
        except Exception as e:
            logger.warning(
                "TMDB similar fetch failed for %s/%s: %s", media_type_segment, tmdb_id, e
            )

        await rds.setex(key, TMDB_SIMILAR_CACHE_TTL, json.dumps(ids))
        return ids

    # ------------------------------------------------------------------
    # Profile building
    # ------------------------------------------------------------------
    async def build_user_profile(
        self, user_guid: str | uuid.UUID, media_type: str
    ) -> UserProfileVector:
        """Rebuild UserProfileVector for one (user, media_type) pair."""
        user_uuid = _u(user_guid)
        mt = media_type.upper()

        # Genre histogram from viewing history + favorites + user-added list items
        # Episodes resolve to parent show before genre lookup (episodes have no genres).
        from streamarr.models.list import ListType as LT

        genre_counts: dict[int, float] = defaultdict(float)
        cast_counts: dict[str, float] = defaultdict(float)
        language_counts: dict[str, float] = defaultdict(float)
        now = datetime.now(UTC)

        async def _weight_for(when: datetime | None, base: float) -> float:
            if when is None:
                return base
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            age_days = max(0.0, (now - when).total_seconds() / 86400.0)
            decay = math.exp(-age_days / 180.0)
            return base * decay

        # Resolve episode → parent show for genre lookup. Parents are loaded in
        # bulk (a couple of queries per hop for the whole batch) rather than a
        # per-item, per-hop SELECT, which for 200 history rows + favorites would
        # otherwise fan out into several hundred sequential single-row queries.
        async def _load_parent_chain(
            items: list[MediaItem],
        ) -> dict[uuid.UUID, MediaItem]:
            by_guid: dict[uuid.UUID, MediaItem] = {it.guid: it for it in items}
            frontier = {
                it.parent_guid for it in items if it.parent_guid
            } - set(by_guid)
            hops = 0
            while frontier and hops < 3:
                res = await self.db.execute(
                    select(MediaItem)
                    .where(MediaItem.guid.in_(frontier))
                    .options(selectinload(MediaItem.genres))
                )
                next_frontier: set[uuid.UUID] = set()
                for parent in res.scalars().unique().all():
                    by_guid[parent.guid] = parent
                    if parent.parent_guid and parent.parent_guid not in by_guid:
                        next_frontier.add(parent.parent_guid)
                frontier = next_frontier
                hops += 1
            return by_guid

        def _resolve_root(
            item: MediaItem, by_guid: dict[uuid.UUID, MediaItem]
        ) -> MediaItem:
            cur = item
            safety = 0
            while cur.parent_guid and safety < 3:
                parent = by_guid.get(cur.parent_guid)
                if parent is None:
                    break
                cur = parent
                safety += 1
            return cur

        # Viewing history events
        vh_res = await self.db.execute(
            select(ViewingHistory, MediaItem)
            .join(MediaItem, MediaItem.guid == ViewingHistory.media_item_guid)
            .where(ViewingHistory.user_guid == user_uuid)
            .order_by(ViewingHistory.last_watched_at.desc())
            .limit(200)
            .options(selectinload(MediaItem.genres))
        )
        vh_rows = vh_res.all()
        vh_parents = await _load_parent_chain([item for _vh, item in vh_rows])
        for vh, item in vh_rows:
            root = _resolve_root(item, vh_parents)
            if mt == "MOVIES" and root.media_type.value != "MOVIES":
                continue
            if mt == "SHOWS" and root.media_type.value not in ("SHOWS",):
                continue
            w = await _weight_for(vh.last_watched_at, 1.0)
            for g in root.genres or []:
                genre_counts[g.id] += w

        # Favorites (items in user's favorites list)
        fav_res = await self.db.execute(
            select(List).where(
                List.owner_guid == user_uuid,
                List.list_type == LT.FAVORITES,
                List.deleted_at.is_(None),
            )
        )
        fav_list = fav_res.scalar_one_or_none()
        if fav_list:
            fav_items = await self.db.execute(
                select(ListItem, MediaItem)
                .join(MediaItem, MediaItem.guid == ListItem.item_guid)
                .where(ListItem.list_guid == fav_list.guid)
                .options(selectinload(MediaItem.genres))
            )
            fav_rows = fav_items.all()
            fav_parents = await _load_parent_chain(
                [item for _li, item in fav_rows]
            )
            for li, item in fav_rows:
                root = _resolve_root(item, fav_parents)
                if mt == "MOVIES" and root.media_type.value != "MOVIES":
                    continue
                if mt == "SHOWS" and root.media_type.value != "SHOWS":
                    continue
                w = await _weight_for(li.created_at, 0.7 * 1.5)
                for g in root.genres or []:
                    genre_counts[g.id] += w

        # Top cast (persons) from viewing history items
        top_media_q = (
            select(MediaCast.person_guid, func.count().label("c"))
            .join(MediaItem, MediaItem.guid == MediaCast.media_item_guid)
            .join(ViewingHistory, ViewingHistory.media_item_guid == MediaItem.guid)
            .where(
                ViewingHistory.user_guid == user_uuid,
                MediaItem.media_type == mt,
                or_(MediaCast.cast_order.is_(None), MediaCast.cast_order < 10),
            )
            .group_by(MediaCast.person_guid)
            .order_by(func.count().desc())
            .limit(30)
        )
        top_cast_rows = await self.db.execute(top_media_q)
        top_cast_guids = [
            {"guid": str(pg), "weight": float(c)}
            for pg, c in top_cast_rows.all()
            if pg
        ]

        # Audio language preferences from user record
        u_res = await self.db.execute(select(User).where(User.guid == user_uuid))
        u = u_res.scalar_one_or_none()
        if u and u.audio_languages:
            for i, lang in enumerate(u.audio_languages):
                language_counts[lang] = 1.0 / (i + 1)

        # Accepted-friend guids for fast retrieval join
        friend_rows = await self.db.execute(
            select(
                case(
                    (Friendship.requester_id == user_uuid, Friendship.addressee_id),
                    else_=Friendship.requester_id,
                ).label("friend_guid")
            ).where(
                Friendship.status == FriendshipStatus.accepted,
                or_(
                    Friendship.requester_id == user_uuid,
                    Friendship.addressee_id == user_uuid,
                ),
            )
        )
        friend_guids = [str(r[0]) for r in friend_rows.all()]

        # Normalise genre counts to weights summing ~1
        total = sum(genre_counts.values())
        genre_weights = (
            {str(gid): round(v / total, 4) for gid, v in genre_counts.items()}
            if total > 0
            else {}
        )

        upv_res = await self.db.execute(
            select(UserProfileVector).where(
                UserProfileVector.user_guid == user_uuid,
                UserProfileVector.media_type == mt,
            )
        )
        upv = upv_res.scalar_one_or_none()
        if upv is None:
            upv = UserProfileVector(
                user_guid=user_uuid,
                media_type=mt,
                genre_weights=genre_weights,
                top_cast_guids=top_cast_guids,
                language_weights=dict(language_counts),
                friend_guids=friend_guids,
                updated_at=datetime.now(UTC),
            )
            self.db.add(upv)
        else:
            upv.genre_weights = genre_weights
            upv.top_cast_guids = top_cast_guids
            upv.language_weights = dict(language_counts)
            upv.friend_guids = friend_guids
            upv.updated_at = datetime.now(UTC)

        await self.db.commit()
        return upv

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    async def _watched_guids(
        self, user_uuid: uuid.UUID, mt: str
    ) -> set[uuid.UUID]:
        """Items the user has already watched (at any progress > 0)."""
        res = await self.db.execute(
            select(ViewingHistory.media_item_guid)
            .join(MediaItem, MediaItem.guid == ViewingHistory.media_item_guid)
            .where(
                ViewingHistory.user_guid == user_uuid,
                MediaItem.media_type == mt,
            )
        )
        return {row[0] for row in res.all()}

    async def _recent_anchors(
        self, user_uuid: uuid.UUID, mt: str, limit: int = 5
    ) -> list[MediaItem]:
        """Recent completions + top favorites as anchor seeds for retrieval."""
        res = await self.db.execute(
            select(MediaItem)
            .join(ViewingHistory, ViewingHistory.media_item_guid == MediaItem.guid)
            .where(
                ViewingHistory.user_guid == user_uuid,
                MediaItem.media_type == mt,
            )
            .order_by(ViewingHistory.last_watched_at.desc())
            .limit(limit)
            .options(
                selectinload(MediaItem.external_ids),
                selectinload(MediaItem.genres),
                selectinload(MediaItem.cast),
            )
        )
        return list(res.scalars().unique().all())

    async def _tmdb_id_of(self, item: MediaItem) -> str | None:
        # external_ids may not be eager-loaded; look up explicitly.
        res = await self.db.execute(
            select(MediaExternalId.external_id).where(
                MediaExternalId.media_item_guid == item.guid,
                MediaExternalId.provider == "tmdb",
            )
        )
        row = res.first()
        return row[0] if row else None

    async def _owned_guids_from_tmdb_ids(
        self, tmdb_ids: list[str], mt: str
    ) -> list[uuid.UUID]:
        if not tmdb_ids:
            return []
        res = await self.db.execute(
            select(MediaExternalId.media_item_guid)
            .join(MediaItem, MediaItem.guid == MediaExternalId.media_item_guid)
            .where(
                MediaExternalId.provider == "tmdb",
                MediaExternalId.external_id.in_(tmdb_ids),
                MediaItem.media_type == mt,
            )
        )
        return [row[0] for row in res.all()]

    async def retrieve_by_anchor(
        self, anchor: MediaItem, mt: str, limit: int = 100
    ) -> list[uuid.UUID]:
        tmdb_id = await self._tmdb_id_of(anchor)
        if not tmdb_id:
            return []
        segment = MEDIA_TYPE_MAP[mt][0]
        ids = await self.tmdb_similar_cached(tmdb_id, segment)
        owned = await self._owned_guids_from_tmdb_ids(ids[:40], mt)
        return owned[:limit]

    async def retrieve_content_based(
        self, upv: UserProfileVector, mt: str, limit: int = 200
    ) -> list[uuid.UUID]:
        """Fallback: pick items sharing genres with the user's top genres."""
        weights = upv.genre_weights or {}
        if not weights:
            return []
        top_genre_ids = [
            int(gid)
            for gid, _ in sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:5]
        ]
        if not top_genre_ids:
            return []
        res = await self.db.execute(
            select(MediaItem.guid, func.count().label("matches"))
            .join(media_genre_table, media_genre_table.c.media_item_guid == MediaItem.guid)
            .where(
                MediaItem.media_type == mt,
                media_genre_table.c.genre_id.in_(top_genre_ids),
            )
            .group_by(MediaItem.guid)
            .order_by(func.count().desc(), MediaItem.release_date.desc().nullslast())
            .limit(limit)
        )
        return [row[0] for row in res.all()]

    async def retrieve_friend_activity(
        self,
        user_uuid: uuid.UUID,
        friend_guids: list[str],
        mt: str,
        since_days: int = 30,
        limit: int = 150,
    ) -> list[tuple[uuid.UUID, list[str]]]:
        """Items friends watched/favorited recently; dedup with friend guid list."""
        if not friend_guids:
            return []
        since = datetime.now(UTC) - timedelta(days=since_days)
        friend_uuids = [uuid.UUID(g) for g in friend_guids]

        q = (
            select(
                ViewingHistory.media_item_guid,
                func.array_agg(func.distinct(ViewingHistory.user_guid)).label("friends"),
            )
            .join(MediaItem, MediaItem.guid == ViewingHistory.media_item_guid)
            .where(
                ViewingHistory.user_guid.in_(friend_uuids),
                ViewingHistory.last_watched_at >= since,
                MediaItem.media_type == mt,
            )
            .group_by(ViewingHistory.media_item_guid)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = await self.db.execute(q)
        out: list[tuple[uuid.UUID, list[str]]] = []
        watched = await self._watched_guids(user_uuid, mt)
        for media_guid, friends in rows.all():
            if media_guid in watched:
                continue
            out.append((media_guid, [str(f) for f in (friends or [])]))
        return out

    async def retrieve_similar_item(
        self, item: MediaItem, limit: int = 30
    ) -> list[uuid.UUID]:
        """Detail-page on-demand similar items."""
        mt = item.media_type.value
        if mt not in MEDIA_TYPE_MAP:
            return []
        # TMDB first, then content-based fallback.
        tmdb_id = await self._tmdb_id_of(item)
        owned: list[uuid.UUID] = []
        if tmdb_id:
            segment = MEDIA_TYPE_MAP[mt][0]
            ids = await self.tmdb_similar_cached(tmdb_id, segment)
            owned = await self._owned_guids_from_tmdb_ids(ids[:40], mt)
        if len(owned) < limit:
            res = await self.db.execute(
                select(MediaItem.guid)
                .join(
                    media_genre_table,
                    media_genre_table.c.media_item_guid == MediaItem.guid,
                )
                .where(
                    MediaItem.media_type == mt,
                    MediaItem.guid != item.guid,
                    media_genre_table.c.genre_id.in_(
                        select(media_genre_table.c.genre_id).where(
                            media_genre_table.c.media_item_guid == item.guid
                        )
                    ),
                )
                .group_by(MediaItem.guid)
                .order_by(func.count().desc())
                .limit(limit * 2)
            )
            have = set(owned)
            for (g,) in res.all():
                if g in have or g == item.guid:
                    continue
                have.add(g)
                owned.append(g)
                if len(owned) >= limit:
                    break
        return owned[:limit]

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    def _friend_signal(self, friends_watched: int, friends_favorited: int = 0) -> float:
        effective = friends_watched + friends_favorited * 1.5
        if effective <= 0:
            return 0.0
        if effective >= 3:
            return 1.0
        if effective >= 2:
            return 0.7
        return 0.4

    async def _score_candidates(
        self,
        user_uuid: uuid.UUID,
        upv: UserProfileVector,
        candidates: list[uuid.UUID],
        mt: str,
        anchor: MediaItem | None = None,
        friend_hits: dict[uuid.UUID, int] | None = None,
    ) -> list[_Candidate]:
        """Score each candidate; returns sorted list (best first)."""
        if not candidates:
            return []

        # Load items + genres + cast (batch)
        item_res = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.guid.in_(candidates))
            .options(selectinload(MediaItem.genres), selectinload(MediaItem.cast))
        )
        items = {it.guid: it for it in item_res.scalars().unique().all()}

        genre_weights = upv.genre_weights or {}
        top_cast_set = {c["guid"] for c in (upv.top_cast_guids or [])}
        language_weights = upv.language_weights or {}
        w = DEFAULT_WEIGHTS
        now = datetime.now(UTC)
        collection_seen: dict[str, int] = defaultdict(int)
        scored: list[_Candidate] = []

        # Anchor features (genre + cast)
        anchor_genres = set()
        anchor_cast = set()
        if anchor is not None:
            anchor_genres = {g.id for g in (anchor.genres or [])}
            anchor_cast = {str(c.person_guid) for c in (anchor.cast or [])}

        for idx, guid in enumerate(candidates):
            item = items.get(guid)
            if item is None:
                continue

            # genre_affinity
            item_genres = {g.id for g in (item.genres or [])}
            if genre_weights and item_genres:
                genre_affinity = sum(
                    genre_weights.get(str(gid), 0.0) for gid in item_genres
                )
                genre_affinity = min(1.0, genre_affinity)
            else:
                genre_affinity = 0.0

            # content_similarity (Jaccard on anchor genres + cast)
            content_similarity = 0.0
            if anchor is not None:
                item_cast = {str(c.person_guid) for c in (item.cast or [])}
                union = anchor_genres | item_genres
                genre_jac = (
                    len(anchor_genres & item_genres) / len(union) if union else 0.0
                )
                cast_union = anchor_cast | item_cast
                cast_jac = (
                    len(anchor_cast & item_cast) / len(cast_union) if cast_union else 0.0
                )
                content_similarity = (genre_jac + cast_jac) / 2.0

            # external_rank (position in the candidate list, normalised)
            external_rank = max(0.0, 1.0 - idx / max(1, len(candidates)))

            # friend_signal
            friend_signal_val = 0.0
            if friend_hits:
                friend_signal_val = self._friend_signal(friend_hits.get(guid, 0))

            # popularity_decay (release_year)
            popularity_decay = 0.0
            if item.release_date:
                age_years = max(0.0, (now - item.release_date).days / 365.25)
                popularity_decay = math.exp(-age_years / 6.0)

            # cast_overlap
            cast_overlap = 0.0
            if top_cast_set:
                item_cast_set = {str(c.person_guid) for c in (item.cast or [])}
                overlap = len(top_cast_set & item_cast_set)
                cast_overlap = min(1.0, overlap / 3.0)

            # language_match (original_language comes from extra_data JSON)
            language_match = 0.0
            orig_lang = None
            if item.extra_data:
                try:
                    ed = json.loads(item.extra_data) if isinstance(item.extra_data, str) else item.extra_data
                    orig_lang = (ed or {}).get("original_language") if isinstance(ed, dict) else None
                except (json.JSONDecodeError, TypeError):
                    orig_lang = None
            if orig_lang and language_weights.get(orig_lang):
                language_match = language_weights[orig_lang]

            # quality_match: constant for v1 (no explicit release comparison)
            quality_match = 0.5

            # recency_bonus: when the first friend saw it (if within 30 d) — approximate
            # via item.created_at fallback.
            recency_bonus = 0.0
            if item.created_at:
                created = item.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                age_days = (now - created).days
                if age_days <= 30:
                    recency_bonus = 1.0 - age_days / 30.0

            score = (
                w["genre_affinity"] * genre_affinity
                + w["content_similarity"] * content_similarity
                + w["external_rank"] * external_rank
                + w["friend_signal"] * friend_signal_val
                + w["popularity_decay"] * popularity_decay
                + w["cast_overlap"] * cast_overlap
                + w["language_match"] * language_match
                + w["quality_match"] * quality_match
                + w["recency_bonus"] * recency_bonus
            )

            # Soft diversity: collection cap = 2 per row. v1 uses parent_guid as proxy.
            collection_key = str(item.parent_guid) if item.parent_guid else None
            if collection_key:
                collection_seen[collection_key] += 1
                if collection_seen[collection_key] > 2:
                    score *= 0.25  # downrank further siblings heavily

            scored.append(_Candidate(guid=guid, score=score))

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored

    # ------------------------------------------------------------------
    # Row builders — materialise system lists
    # ------------------------------------------------------------------
    NAME_TRANSLATIONS = {
        "for_you": {"en-US": "For you", "de-DE": "Für dich"},
        "for_you_cold": {"en-US": "Trending for you", "de-DE": "Trending für dich"},
        "top_picks": {"en-US": "Top picks for you", "de-DE": "Top-Auswahl für dich"},
        "friends_watching": {
            "en-US": "Friends are watching",
            "de-DE": "Freunde schauen gerade",
        },
    }

    def _mt_suffix(self, mt: str) -> str:
        return {"MOVIES": "movies", "SHOWS": "shows"}.get(mt, mt.lower())

    def _list_item_type(self, mt: str) -> ListItemType:
        return MEDIA_TYPE_MAP[mt][1]

    async def rebuild_for_you_list(
        self, user_uuid: uuid.UUID, mt: str
    ) -> List:
        upv = await self._get_or_build_profile(user_uuid, mt)
        source = f"rec:for_you:{self._mt_suffix(mt)}"

        watched = await self._watched_guids(user_uuid, mt)
        is_cold = not upv.genre_weights

        candidates: list[uuid.UUID] = []
        if not is_cold:
            for anchor in await self._recent_anchors(user_uuid, mt, limit=5):
                anchor_ids = await self.retrieve_by_anchor(anchor, mt, limit=40)
                for g in anchor_ids:
                    if g not in watched and g not in candidates:
                        candidates.append(g)
            # top up from content-based
            for g in await self.retrieve_content_based(upv, mt, limit=200):
                if g not in watched and g not in candidates:
                    candidates.append(g)

        if len(candidates) < 30:
            # trending fallback
            candidates.extend(
                await self._trending_candidates(
                    mt, exclude=watched | set(candidates), limit=60
                )
            )

        scored = await self._score_candidates(
            user_uuid, upv, candidates[:200], mt, anchor=None
        )
        ranked = [(c.guid, c.score) for c in scored][:30]

        name_translations = (
            self.NAME_TRANSLATIONS["for_you"]
            if not is_cold
            else self.NAME_TRANSLATIONS["for_you_cold"]
        )
        lst = await self._list_service.get_or_create_system_list(
            owner_guid=user_uuid,
            update_source=source,
            name=name_translations["en-US"],
            name_translations=name_translations,
        )
        await self._list_service.replace_items(
            lst.guid,
            [
                (g, self._list_item_type(mt), i)
                for i, (g, _s) in enumerate(ranked)
            ],
        )
        return lst

    async def rebuild_top_picks_list(
        self, user_uuid: uuid.UUID, mt: str
    ) -> List:
        source = f"rec:top_picks:{self._mt_suffix(mt)}"
        watched = await self._watched_guids(user_uuid, mt)
        trending = await self._trending_candidates(mt, exclude=watched, limit=60)
        upv = await self._get_or_build_profile(user_uuid, mt)
        scored = await self._score_candidates(user_uuid, upv, trending, mt)
        ranked = [(c.guid, c.score) for c in scored][:30]

        lst = await self._list_service.get_or_create_system_list(
            owner_guid=user_uuid,
            update_source=source,
            name=self.NAME_TRANSLATIONS["top_picks"]["en-US"],
            name_translations=self.NAME_TRANSLATIONS["top_picks"],
        )
        await self._list_service.replace_items(
            lst.guid,
            [(g, self._list_item_type(mt), i) for i, (g, _s) in enumerate(ranked)],
        )
        return lst

    async def rebuild_because_you_watched_lists(
        self, user_uuid: uuid.UUID, mt: str, max_anchors: int = 3
    ) -> list[List]:
        upv = await self._get_or_build_profile(user_uuid, mt)
        if not upv.genre_weights:
            return []

        anchors = await self._recent_anchors(user_uuid, mt, limit=max_anchors)
        watched = await self._watched_guids(user_uuid, mt)
        produced: list[List] = []
        kept_source_values: set[str] = set()

        for anchor in anchors:
            ids = await self.retrieve_by_anchor(anchor, mt, limit=60)
            candidates = [g for g in ids if g not in watched and g != anchor.guid]
            if not candidates:
                continue
            scored = await self._score_candidates(
                user_uuid, upv, candidates, mt, anchor=anchor
            )
            if not scored:
                continue
            ranked = [(c.guid, c.score) for c in scored][:20]

            suffix = self._mt_suffix(mt)
            source = f"rec:because:{anchor.guid}:{suffix}"
            kept_source_values.add(source)
            title_en = f"Because you watched {anchor.title}"
            title_de = f"Weil du {anchor.title} geschaut hast"
            lst = await self._list_service.get_or_create_system_list(
                owner_guid=user_uuid,
                update_source=source,
                name=title_en,
                name_translations={"en-US": title_en, "de-DE": title_de},
                context_item_guid=anchor.guid,
            )
            await self._list_service.replace_items(
                lst.guid,
                [
                    (g, self._list_item_type(mt), i)
                    for i, (g, _s) in enumerate(ranked)
                ],
            )
            produced.append(lst)

        # Soft-delete obsolete BYW lists for this user+mt whose source is no
        # longer in the kept set.
        suffix = self._mt_suffix(mt)
        stale_res = await self.db.execute(
            select(List).where(
                List.owner_guid == user_uuid,
                List.update_source.like(f"rec:because:%:{suffix}"),
                List.deleted_at.is_(None),
            )
        )
        for old in stale_res.scalars().all():
            if old.update_source not in kept_source_values:
                old.deleted_at = datetime.now(UTC)
        await self.db.commit()

        return produced

    async def rebuild_friends_watching_list(
        self, user_uuid: uuid.UUID, mt: str
    ) -> List:
        upv = await self._get_or_build_profile(user_uuid, mt)
        friend_guids = upv.friend_guids or []
        activity = await self.retrieve_friend_activity(
            user_uuid, friend_guids, mt, since_days=30, limit=150
        )
        friend_hits = {g: len(fs) for g, fs in activity}
        candidates = [g for g, _fs in activity]
        scored = await self._score_candidates(
            user_uuid, upv, candidates, mt, friend_hits=friend_hits
        )
        ranked = [(c.guid, c.score) for c in scored][:30]

        source = f"rec:friends_watching:{self._mt_suffix(mt)}"
        lst = await self._list_service.get_or_create_system_list(
            owner_guid=user_uuid,
            update_source=source,
            name=self.NAME_TRANSLATIONS["friends_watching"]["en-US"],
            name_translations=self.NAME_TRANSLATIONS["friends_watching"],
        )
        await self._list_service.replace_items(
            lst.guid,
            [(g, self._list_item_type(mt), i) for i, (g, _s) in enumerate(ranked)],
        )
        return lst

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _get_or_build_profile(
        self, user_uuid: uuid.UUID, mt: str
    ) -> UserProfileVector:
        res = await self.db.execute(
            select(UserProfileVector).where(
                UserProfileVector.user_guid == user_uuid,
                UserProfileVector.media_type == mt,
            )
        )
        upv = res.scalar_one_or_none()
        if upv is None:
            upv = await self.build_user_profile(user_uuid, mt)
        return upv

    async def _trending_candidates(
        self, mt: str, exclude: set[uuid.UUID], limit: int = 60
    ) -> list[uuid.UUID]:
        """Pull items from the corresponding SYSTEM trending list, if any."""
        suffix = {"MOVIES": "trending_movies", "SHOWS": "trending_shows"}.get(mt)
        if not suffix:
            return []
        lst_res = await self.db.execute(
            select(List).where(
                List.list_type == ListType.SYSTEM,
                List.update_source == suffix,
                List.deleted_at.is_(None),
            )
        )
        lst = lst_res.scalar_one_or_none()
        if lst is None:
            return []
        items_res = await self.db.execute(
            select(ListItem.item_guid)
            .where(ListItem.list_guid == lst.guid)
            .order_by(ListItem.order_index.asc().nulls_last())
            .limit(limit * 2)
        )
        out: list[uuid.UUID] = []
        for (g,) in items_res.all():
            if g in exclude:
                continue
            out.append(g)
            if len(out) >= limit:
                break
        return out

    async def get_similar_items(
        self, item: MediaItem, user_uuid: uuid.UUID | None = None, limit: int = 20
    ) -> list[MediaItem]:
        guids = await self.retrieve_similar_item(item, limit=limit)
        if not guids:
            return []
        res = await self.db.execute(
            select(MediaItem).where(MediaItem.guid.in_(guids))
        )
        by_guid = {it.guid: it for it in res.scalars().all()}
        return [by_guid[g] for g in guids if g in by_guid]
