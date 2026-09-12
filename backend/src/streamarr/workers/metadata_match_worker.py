"""Resolve library items the scanner could not tie to a TMDB id.

The scanner only records provider ids it can read straight off disk: an NFO
file, or a Sonarr/Radarr-style ``[tvdbid-...]`` folder name. Everything else
lands in the database as a bare filename-derived title, and
``refresh_media_item_metadata`` bails out on it ("No external ID for media
item"), so the item keeps its filename as its title and never gets a poster.

This closes that gap the way Sonarr and Radarr do it:

1. An id embedded in the path wins outright. TMDB's ``find`` endpoint maps a
   tvdb/imdb id onto its TMDB entry exactly, so there is nothing to guess.
2. Only when no such id exists do we fall back to a title+year search, and
   then accept a hit solely if the normalised title matches and the year
   lines up. Anything ambiguous is reported rather than written — a wrong id
   is worse than no id at all, because every later metadata refresh would
   faithfully keep overwriting the item with someone else's film.

The default is a dry run: it reports what it *would* attach and changes
nothing.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import exists, select

from streamarr.database import sessionmanager
from streamarr.metadata.local import provider_ids_from_name
from streamarr.metadata.tmdb import TMDB
from streamarr.models.media import MediaExternalId, MediaFile, MediaItem, MediaType
from streamarr.services.system_settings import get_tmdb_api_key

logger = logging.getLogger(__name__)

Enqueue = Callable[..., Awaitable[object]]

# Radarr tolerates a year that is one off, because a film's release year
# differs between regions often enough to matter. Same reasoning here.
_YEAR_SLACK = 1

# A trailing "(2015)" is part of the title only because the scanner derived
# the title from a folder name that carried the year.
_TRAILING_YEAR_RE = re.compile(r"\s*\((?P<year>(19|20)\d{2})\)\s*$")

# English only, and only at the start. German articles are left alone because
# "Die Hard" is not a German title and stripping "Die" from it would be wrong
# in a way that is hard to see later.
_LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+")

# TMDB external_source values, in the order we trust them.
_FIND_SOURCES = (("tvdb", "tvdb_id"), ("imdb", "imdb_id"))

# Each alternative-title lookup is its own request, so only the handful of
# candidates whose year already fits are worth asking about.
_ALTERNATIVE_TITLE_LOOKUPS = 5


def _normalise(title: str) -> str:
    """Reduce a title to what two spellings of it have in common.

    Case, punctuation, diacritics and spacing all vary between a release
    name and a TMDB entry ("Top Gun Maverick" vs "Top Gun: Maverick"), and
    none of that variation carries meaning for matching.
    """
    decomposed = unicodedata.normalize("NFKD", title)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    # "21 & Over" and "21 and Over" are the same film, and dropping the
    # ampersand as punctuation would leave "21over" against "21andover".
    # Radarr folds it the same way.
    folded = stripped.casefold().replace("&", " and ")
    # A leading article is decoration that catalogues disagree about: TMDB
    # files the film the folder calls "Bicycle Thieves" as "The Bicycle
    # Thieves". Dropping it on both sides keeps the comparison symmetric.
    folded = _LEADING_ARTICLE_RE.sub("", folded.strip())
    return re.sub(r"[^a-z0-9]+", "", folded)


def _title_and_year(item: MediaItem) -> tuple[str, int | None]:
    """Split the stored title into a searchable title and a year."""
    title = item.title or ""
    year = item.release_date.year if item.release_date else None
    match = _TRAILING_YEAR_RE.search(title)
    if match:
        title = title[: match.start()].strip()
        year = year or int(match.group("year"))
    return title, year


def _candidate_years(entry: dict[str, Any]) -> set[int]:
    years = set()
    for key in ("release_date", "first_air_date"):
        raw = (entry.get(key) or "")[:4]
        if raw.isdigit():
            years.add(int(raw))
    return years


def _candidate_titles(entry: dict[str, Any]) -> set[str]:
    """Every spelling TMDB offers for one entry.

    The client requests ``language=de-DE``, so ``title``/``name`` come back
    localised while ``original_title``/``original_name`` stay in the source
    language. A German library legitimately matches either one.
    """
    # A title in a non-Latin script normalises to nothing; keeping the empty
    # string would make it look like a spelling we can compare against.
    return {
        normalised
        for key in ("title", "original_title", "name", "original_name")
        if entry.get(key)
        for normalised in [_normalise(str(entry.get(key)))]
        if normalised
    }


async def _accept_via_alternative_titles(
    tmdb: TMDB, candidates: list[dict[str, Any]], wanted: str, media_type: MediaType
) -> list[dict[str, Any]]:
    """Second look at candidates whose year fits but whose titles did not.

    Search hands back one localised and one original title per entry, and a
    library regularly uses neither — an English release name against a German
    catalogue, or a Japanese original that carries no Latin spelling at all.
    TMDB keeps the rest in its alternative titles, which is the same list
    Sonarr and Radarr consult before giving up.
    """
    segment = "movie" if media_type == MediaType.MOVIES else "tv"
    key = "titles" if media_type == MediaType.MOVIES else "results"
    accepted = []
    for entry in candidates[:_ALTERNATIVE_TITLE_LOOKUPS]:
        payload = await tmdb.alternative_titles(entry.get("id"), segment)
        names = {
            _normalise(str(row.get("title")))
            for row in (payload or {}).get(key) or []
            if row.get("title")
        }
        if wanted in names:
            accepted.append(entry)
    return accepted


@dataclass(slots=True)
class MatchOutcome:
    media_item_guid: str
    title: str
    year: int | None
    media_type: str
    # matched | ambiguous | not_found | taken | no_title | no_id_on_disk
    status: str
    tmdb_id: str | None = None
    source: str | None = None  # "find:tvdb" | "search"
    matched_title: str | None = None
    matched_year: int | None = None
    detail: str | None = None


@dataclass(slots=True)
class MatchReport:
    dry_run: bool = True
    considered: int = 0
    matched: int = 0
    ambiguous: int = 0
    not_found: int = 0
    skipped: int = 0
    outcomes: list[MatchOutcome] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "considered": self.considered,
            "matched": self.matched,
            "ambiguous": self.ambiguous,
            "not_found": self.not_found,
            "skipped": self.skipped,
            "outcomes": [asdict(o) for o in self.outcomes],
        }


async def _representative_path(db, item: MediaItem) -> str | None:
    """One file path belonging to this item, directly or via its children.

    A movie owns its file. A show owns nothing itself — the path lives two
    levels down on an episode — but the ``[tvdbid-...]`` marker sits in the
    series folder, which is a prefix of every episode path underneath it.
    """
    direct = await db.scalar(
        select(MediaFile.file_path)
        .where(MediaFile.media_item_guid == item.guid)
        .limit(1)
    )
    if direct:
        return direct

    child = MediaItem.__table__.alias("child")
    grandchild = MediaItem.__table__.alias("grandchild")
    return await db.scalar(
        select(MediaFile.file_path)
        .select_from(child)
        .join(grandchild, grandchild.c.parent_guid == child.c.guid)
        .join(MediaFile, MediaFile.media_item_guid == grandchild.c.guid)
        .where(child.c.parent_guid == item.guid)
        .limit(1)
    )


async def _tmdb_id_is_free(db, tmdb_id: str) -> bool:
    """``(provider, external_id)`` is globally unique, so a taken id is fatal."""
    return not await db.scalar(
        select(
            exists().where(
                MediaExternalId.provider == "tmdb",
                MediaExternalId.external_id == str(tmdb_id),
            )
        )
    )


def _find_result_for(payload: dict[str, Any], media_type: MediaType) -> dict | None:
    key = "movie_results" if media_type == MediaType.MOVIES else "tv_results"
    results = (payload or {}).get(key) or []
    return results[0] if len(results) == 1 else None


async def _match_via_path_id(
    tmdb: TMDB, item: MediaItem, path: str | None, media_type: MediaType
) -> MatchOutcome | None:
    """Exact resolution from an id already present in the file path."""
    if not path:
        return None
    ids = provider_ids_from_name(path)
    title, year = _title_and_year(item)

    if tmdb_id := ids.get("tmdb"):
        return MatchOutcome(
            media_item_guid=str(item.guid), title=title, year=year,
            media_type=media_type.value, status="matched",
            tmdb_id=str(tmdb_id), source="path:tmdb",
        )

    for provider, external_source in _FIND_SOURCES:
        external_id = ids.get(provider)
        if not external_id:
            continue
        payload = await tmdb.find_by_external_id(external_id, external_source)
        entry = _find_result_for(payload, media_type)
        if entry is None:
            continue
        return MatchOutcome(
            media_item_guid=str(item.guid), title=title, year=year,
            media_type=media_type.value, status="matched",
            tmdb_id=str(entry.get("id")), source=f"find:{provider}",
            matched_title=entry.get("title") or entry.get("name"),
            matched_year=next(iter(sorted(_candidate_years(entry))), None),
        )
    return None


async def _match_via_search(
    tmdb: TMDB, item: MediaItem, media_type: MediaType
) -> MatchOutcome:
    """Title+year search, accepted only on an unambiguous exact-title hit."""
    title, year = _title_and_year(item)
    base = MatchOutcome(
        media_item_guid=str(item.guid), title=title, year=year,
        media_type=media_type.value, status="not_found", source="search",
    )
    if not title:
        base.status = "no_title"
        return base
    if year is None:
        base.status = "ambiguous"
        base.detail = "kein Jahr bekannt — Titelsuche allein ist nicht eindeutig genug"
        return base

    if media_type == MediaType.MOVIES:
        payload = await tmdb.search_movies(query=title, year=year)
    else:
        payload = await tmdb.search_shows(query=title, year=year)

    results = (payload or {}).get("results") or []
    wanted = _normalise(title)
    # The year is the cheap discriminator, so narrow on it first and only
    # then argue about spelling.
    right_year = [
        entry
        for entry in results
        if any(abs(y - year) <= _YEAR_SLACK for y in _candidate_years(entry))
    ]
    accepted = [entry for entry in right_year if wanted in _candidate_titles(entry)]
    if not accepted and right_year:
        accepted = await _accept_via_alternative_titles(
            tmdb, right_year, wanted, media_type
        )
        if accepted:
            base.source = "search+alt"

    if not accepted:
        base.detail = f"{len(results)} Treffer, keiner mit passendem Titel und Jahr"
        return base
    if len({entry.get("id") for entry in accepted}) > 1:
        base.status = "ambiguous"
        base.detail = (
            f"{len(accepted)} gleichwertige Treffer: "
            + ", ".join(str(entry.get("id")) for entry in accepted[:5])
        )
        return base

    entry = accepted[0]
    base.status = "matched"
    base.tmdb_id = str(entry.get("id"))
    base.matched_title = entry.get("title") or entry.get("name")
    base.matched_year = next(iter(sorted(_candidate_years(entry))), None)
    return base


async def match_media_items_impl(
    *,
    dry_run: bool = True,
    limit: int = 200,
    media_types: tuple[MediaType, ...] = (MediaType.MOVIES, MediaType.SHOWS),
    allow_search: bool = True,
    enqueue_metadata: Enqueue | None = None,
) -> dict[str, Any]:
    """Attach TMDB ids to top-level items that do not have one yet.

    ``allow_search=False`` restricts the run to ids that are already on
    disk, which is the only mode safe to run unattended: it resolves an id
    the library itself supplied instead of picking a candidate out of a
    search. An item with no such id is passed over without costing a
    request.
    """
    report = MatchReport(dry_run=dry_run)

    async with sessionmanager.session() as db:
        api_key = await get_tmdb_api_key(db)
        if not api_key:
            logger.warning("TMDB API key not configured; skipping match run")
            return {"status": "tmdb_not_configured", **report.as_dict()}

        items = (
            await db.execute(
                select(MediaItem)
                .where(
                    MediaItem.media_type.in_(media_types),
                    MediaItem.parent_guid.is_(None),
                    ~exists().where(
                        MediaExternalId.media_item_guid == MediaItem.guid,
                        MediaExternalId.provider == "tmdb",
                    ),
                )
                .order_by(MediaItem.created_at.asc())
                .limit(limit)
            )
        ).scalars().all()

        tmdb = TMDB(api_key=api_key)
        try:
            for item in items:
                report.considered += 1
                path = await _representative_path(db, item)
                outcome = await _match_via_path_id(tmdb, item, path, item.media_type)
                if outcome is None and allow_search:
                    outcome = await _match_via_search(tmdb, item, item.media_type)
                if outcome is None:
                    title, year = _title_and_year(item)
                    outcome = MatchOutcome(
                        media_item_guid=str(item.guid), title=title, year=year,
                        media_type=item.media_type.value, status="no_id_on_disk",
                        detail="keine Provider-ID im Pfad; Titelsuche ist hier "
                               "abgeschaltet",
                    )

                if outcome.status == "matched" and not await _tmdb_id_is_free(
                    db, outcome.tmdb_id
                ):
                    outcome.status = "taken"
                    outcome.detail = (
                        f"TMDB-ID {outcome.tmdb_id} haengt bereits an einem "
                        "anderen Item"
                    )

                report.outcomes.append(outcome)
                if outcome.status == "matched":
                    report.matched += 1
                elif outcome.status == "ambiguous":
                    report.ambiguous += 1
                elif outcome.status == "not_found":
                    report.not_found += 1
                else:
                    report.skipped += 1

                if outcome.status == "matched" and not dry_run:
                    db.add(
                        MediaExternalId(
                            media_item_guid=item.guid,
                            provider="tmdb",
                            external_id=str(outcome.tmdb_id),
                        )
                    )
                    await db.flush()
        finally:
            if hasattr(tmdb, "close"):
                await tmdb.close()

        if not dry_run:
            await db.commit()

    if not dry_run and enqueue_metadata:
        for outcome in report.outcomes:
            if outcome.status == "matched":
                await enqueue_metadata(outcome.media_item_guid)

    logger.info(
        "Match run finished: considered=%s matched=%s ambiguous=%s not_found=%s "
        "skipped=%s dry_run=%s",
        report.considered, report.matched, report.ambiguous,
        report.not_found, report.skipped, dry_run,
    )
    return {"status": "completed", **report.as_dict()}
