"""Kometa-style default smart-collection rules & overlay templates.

These ship as ``is_system=True, enabled=False`` so a fresh install
doesn't immediately start hammering external APIs — admins flip the
ones they want in the Vue admin UI.

Each entry carries a deterministic UUID derived from its ``slug`` so
re-running the seed migration is idempotent: a second pass sees the
row already exists and skips it. The same UUID can be cited by tests.

All structured config (builder/filter shapes) is plain JSON-safe data
so the migration can shove it straight into JSONB without any Python
references to model code.
"""

from __future__ import annotations

import uuid
from typing import Any

# Stable namespace for default UUIDs. Don't change this — every row's
# identity depends on it.
_NAMESPACE = uuid.UUID("c0f1e2d3-aaaa-4bbb-9ccc-100000000001")


def _smart_guid(slug: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"smart_collection:{slug}"))


def _overlay_guid(slug: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"overlay_template:{slug}"))


def _chart_rule(
    slug: str,
    *,
    name: str,
    description: str,
    media_type: str,
    builder_type: str,
    builder_config: dict[str, Any],
    cron: str,
    item_limit: int = 80,
) -> dict[str, Any]:
    return {
        "guid": _smart_guid(slug),
        "slug": slug,
        "name": name,
        "description": description,
        "media_type": media_type,
        "builder_type": builder_type,
        "builder_config": builder_config,
        "filters": {},
        "sync_mode": "SYNC",
        "item_limit": item_limit,
        "schedule_cron": cron,
    }


def _library_rule(
    slug: str,
    *,
    name: str,
    description: str,
    media_type: str,
    config: dict[str, Any],
    cron: str = "30 4 * * *",
    item_limit: int = 200,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "guid": _smart_guid(slug),
        "slug": slug,
        "name": name,
        "description": description,
        "media_type": media_type,
        "builder_type": "library_filter",
        "builder_config": config,
        "filters": filters or {},
        "sync_mode": "SYNC",
        "item_limit": item_limit,
        "schedule_cron": cron,
    }


# ---------------------------------------------------------------------------
# Smart-collection defaults
# ---------------------------------------------------------------------------


def _movie_chart_defaults() -> list[dict[str, Any]]:
    cron_6h = "0 */6 * * *"
    return [
        _chart_rule(
            "tmdb-popular-movies",
            name="TMDb Popular Movies",
            description="The current TMDb 'popular' chart for movies.",
            media_type="MOVIE",
            builder_type="tmdb",
            builder_config={"mode": "chart", "chart": "popular"},
            cron=cron_6h,
        ),
        _chart_rule(
            "tmdb-trending-movies-week",
            name="TMDb Trending Movies (Week)",
            description="Movies trending across TMDb this week.",
            media_type="MOVIE",
            builder_type="tmdb",
            builder_config={"mode": "chart", "chart": "trending_week"},
            cron=cron_6h,
        ),
        _chart_rule(
            "tmdb-top-rated-movies",
            name="TMDb Top Rated Movies",
            description="Highest-rated movies on TMDb.",
            media_type="MOVIE",
            builder_type="tmdb",
            builder_config={"mode": "chart", "chart": "top_rated"},
            cron="0 5 * * *",
            item_limit=100,
        ),
        _chart_rule(
            "tmdb-now-playing-movies",
            name="TMDb In Theaters",
            description="Movies currently playing in theaters (per TMDb).",
            media_type="MOVIE",
            builder_type="tmdb",
            builder_config={"mode": "chart", "chart": "now_playing"},
            cron=cron_6h,
        ),
        _chart_rule(
            "tmdb-upcoming-movies",
            name="TMDb Upcoming Movies",
            description="Movies releasing soon according to TMDb.",
            media_type="MOVIE",
            builder_type="tmdb",
            builder_config={"mode": "chart", "chart": "upcoming"},
            cron=cron_6h,
        ),
        _chart_rule(
            "trakt-trending-movies",
            name="Trakt Trending Movies",
            description="Movies trending on Trakt right now.",
            media_type="MOVIE",
            builder_type="trakt",
            builder_config={"mode": "chart", "chart": "trending"},
            cron=cron_6h,
        ),
        _chart_rule(
            "trakt-popular-movies",
            name="Trakt Popular Movies",
            description="Trakt's overall popular movies list.",
            media_type="MOVIE",
            builder_type="trakt",
            builder_config={"mode": "chart", "chart": "popular"},
            cron="0 4 * * *",
        ),
        _chart_rule(
            "trakt-watched-movies-week",
            name="Trakt Most Watched Movies (Week)",
            description="Most-watched movies on Trakt this week.",
            media_type="MOVIE",
            builder_type="trakt",
            builder_config={"mode": "chart", "chart": "watched"},
            cron="0 4 * * *",
        ),
        _chart_rule(
            "trakt-anticipated-movies",
            name="Trakt Anticipated Movies",
            description="Most-anticipated unreleased movies on Trakt.",
            media_type="MOVIE",
            builder_type="trakt",
            builder_config={"mode": "chart", "chart": "anticipated"},
            cron="0 4 * * *",
        ),
        _chart_rule(
            "imdb-top-250-movies",
            name="IMDb Top 250 Movies",
            description="The IMDb Top 250 movies chart.",
            media_type="MOVIE",
            builder_type="imdb",
            builder_config={"mode": "chart", "chart": "top_movies"},
            cron="0 3 * * *",
            item_limit=250,
        ),
        _chart_rule(
            "imdb-popular-movies",
            name="IMDb Most Popular Movies",
            description="IMDb's MovieMeter weekly popularity chart.",
            media_type="MOVIE",
            builder_type="imdb",
            builder_config={"mode": "chart", "chart": "popular_movies"},
            cron=cron_6h,
            item_limit=100,
        ),
    ]


def _show_chart_defaults() -> list[dict[str, Any]]:
    cron_6h = "0 */6 * * *"
    return [
        _chart_rule(
            "tmdb-popular-shows",
            name="TMDb Popular Shows",
            description="TMDb's currently popular TV shows.",
            media_type="SHOW",
            builder_type="tmdb",
            builder_config={"mode": "chart", "chart": "popular"},
            cron=cron_6h,
        ),
        _chart_rule(
            "tmdb-trending-shows-week",
            name="TMDb Trending Shows (Week)",
            description="Shows trending across TMDb this week.",
            media_type="SHOW",
            builder_type="tmdb",
            builder_config={"mode": "chart", "chart": "trending_week"},
            cron=cron_6h,
        ),
        _chart_rule(
            "tmdb-top-rated-shows",
            name="TMDb Top Rated Shows",
            description="Highest-rated TV shows on TMDb.",
            media_type="SHOW",
            builder_type="tmdb",
            builder_config={"mode": "chart", "chart": "top_rated"},
            cron="0 5 * * *",
            item_limit=100,
        ),
        _chart_rule(
            "tmdb-on-the-air",
            name="TMDb Shows On The Air",
            description="Shows with an episode airing in the next 7 days.",
            media_type="SHOW",
            builder_type="tmdb",
            builder_config={"mode": "chart", "chart": "on_the_air"},
            cron=cron_6h,
        ),
        _chart_rule(
            "trakt-trending-shows",
            name="Trakt Trending Shows",
            description="Shows trending on Trakt right now.",
            media_type="SHOW",
            builder_type="trakt",
            builder_config={"mode": "chart", "chart": "trending"},
            cron=cron_6h,
        ),
        _chart_rule(
            "trakt-popular-shows",
            name="Trakt Popular Shows",
            description="Trakt's overall popular shows list.",
            media_type="SHOW",
            builder_type="trakt",
            builder_config={"mode": "chart", "chart": "popular"},
            cron="0 4 * * *",
        ),
        _chart_rule(
            "trakt-watched-shows-week",
            name="Trakt Most Watched Shows (Week)",
            description="Most-watched shows on Trakt this week.",
            media_type="SHOW",
            builder_type="trakt",
            builder_config={"mode": "chart", "chart": "watched"},
            cron="0 4 * * *",
        ),
        _chart_rule(
            "trakt-anticipated-shows",
            name="Trakt Anticipated Shows",
            description="Most-anticipated unreleased shows on Trakt.",
            media_type="SHOW",
            builder_type="trakt",
            builder_config={"mode": "chart", "chart": "anticipated"},
            cron="0 4 * * *",
        ),
        _chart_rule(
            "imdb-top-shows",
            name="IMDb Top TV Shows",
            description="The IMDb top-rated TV chart.",
            media_type="SHOW",
            builder_type="imdb",
            builder_config={"mode": "chart", "chart": "top_shows"},
            cron="0 3 * * *",
            item_limit=250,
        ),
        _chart_rule(
            "imdb-popular-shows",
            name="IMDb Most Popular Shows",
            description="IMDb's TVMeter popularity chart.",
            media_type="SHOW",
            builder_type="imdb",
            builder_config={"mode": "chart", "chart": "popular_shows"},
            cron=cron_6h,
            item_limit=100,
        ),
    ]


# Streaming-service collections use TMDb's ``discover`` with
# ``with_watch_providers``. Provider IDs are TMDb's well-known integer
# constants; ``watch_region`` defaults to US — admins should adjust.
_STREAMING_PROVIDERS = {
    "netflix": (8, "Netflix"),
    "disney-plus": (337, "Disney+"),
    "apple-tv-plus": (350, "Apple TV+"),
    "amazon-prime": (9, "Amazon Prime Video"),
    "hbo-max": (1899, "HBO Max"),
    "paramount-plus": (531, "Paramount+"),
    "hulu": (15, "Hulu"),
}


def _streaming_defaults() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for slug, (provider_id, label) in _STREAMING_PROVIDERS.items():
        for media_type, type_token in (("MOVIE", "movies"), ("SHOW", "shows")):
            out.append(
                _chart_rule(
                    f"streaming-{slug}-{type_token}",
                    name=f"{label} {type_token.title()}",
                    description=f"Titles available on {label} via TMDb discover.",
                    media_type=media_type,
                    builder_type="tmdb",
                    builder_config={
                        "mode": "discover",
                        "params": {
                            "with_watch_providers": str(provider_id),
                            "watch_region": "US",
                            "sort_by": "popularity.desc",
                        },
                    },
                    cron="0 5 * * *",
                    item_limit=80,
                )
            )
    return out


def _decade_defaults() -> list[dict[str, Any]]:
    cron = "15 3 * * 0"  # Weekly on Sunday — local query, cheap.
    out: list[dict[str, Any]] = []
    for decade in (1920, 1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020):
        out.append(
            _library_rule(
                f"decade-movies-{decade}s",
                name=f"Movies — {decade}s",
                description=f"All movies in pyrate's catalogue released in the {decade}s.",
                media_type="MOVIE",
                config={
                    "decade": decade,
                    "sort": "release_date",
                    "sort_dir": "desc",
                },
                cron=cron,
                item_limit=500,
            )
        )
    for decade in (1980, 1990, 2000, 2010, 2020):
        out.append(
            _library_rule(
                f"decade-shows-{decade}s",
                name=f"Shows — {decade}s",
                description=f"All shows released in the {decade}s.",
                media_type="SHOW",
                config={
                    "decade": decade,
                    "sort": "release_date",
                    "sort_dir": "desc",
                },
                cron=cron,
                item_limit=300,
            )
        )
    return out


SMART_COLLECTION_DEFAULTS: list[dict[str, Any]] = [
    *_movie_chart_defaults(),
    *_show_chart_defaults(),
    *_streaming_defaults(),
    *_decade_defaults(),
]


# ---------------------------------------------------------------------------
# Overlay templates
# ---------------------------------------------------------------------------


def _resolution_overlay(
    slug: str, *, label: str, height_gte: int, z_order: int
) -> dict[str, Any]:
    return {
        "guid": _overlay_guid(slug),
        "slug": slug,
        "name": f"{label} badge",
        "description": f"Top-right '{label}' badge for {label} sources.",
        "media_scope": "BOTH",
        "target": "POSTER",
        "condition": {
            "all": [
                {"field": "resolution.height", "op": "gte", "value": height_gte},
            ]
        },
        "elements": [
            {
                "type": "text",
                "text": label,
                "x": "right",
                "y": "top",
                "padding": 16,
                "font_size": 44,
                "color": "#ffffff",
                "background": "#000000bb",
                "background_radius": 8,
                "stroke_width": 0,
            }
        ],
        "z_order": z_order,
    }


OVERLAY_DEFAULTS: list[dict[str, Any]] = [
    _resolution_overlay(
        "overlay-4k",
        label="4K",
        height_gte=2160,
        z_order=10,
    ),
    _resolution_overlay(
        "overlay-1080p",
        label="1080p",
        height_gte=1080,
        z_order=8,
    ),
    _resolution_overlay(
        "overlay-720p",
        label="720p",
        height_gte=720,
        z_order=6,
    ),
    {
        "guid": _overlay_guid("overlay-hevc"),
        "slug": "overlay-hevc",
        "name": "HEVC badge",
        "description": "Bottom-left HEVC/H.265 indicator.",
        "media_scope": "BOTH",
        "target": "POSTER",
        "condition": {
            "any": [
                {"field": "codecs.video", "op": "in", "value": ["hevc"]},
                {"field": "codecs.video", "op": "in", "value": ["h265"]},
                {"field": "codecs.video", "op": "in", "value": ["x265"]},
            ]
        },
        "elements": [
            {
                "type": "text",
                "text": "HEVC",
                "x": "left",
                "y": "bottom",
                "padding": 14,
                "font_size": 28,
                "color": "#ffffff",
                "background": "#0066aaee",
                "background_radius": 6,
            }
        ],
        "z_order": 4,
    },
    {
        "guid": _overlay_guid("overlay-downloadable"),
        "slug": "overlay-downloadable",
        "name": "Available to download",
        "description": "Bottom-right badge for downloadable-but-not-yet-local items.",
        "media_scope": "BOTH",
        "target": "POSTER",
        "condition": {
            "all": [
                {"field": "availability", "op": "eq", "value": "downloadable"},
            ]
        },
        "elements": [
            {
                "type": "text",
                "text": "↓",
                "x": "right",
                "y": "bottom",
                "padding": 14,
                "font_size": 36,
                "color": "#ffffff",
                "background": "#3aaa55ee",
                "background_radius": 999,
            }
        ],
        "z_order": 2,
    },
    {
        "guid": _overlay_guid("overlay-pg"),
        "slug": "overlay-pg",
        "name": "Family-safe badge",
        "description": "Bottom-left badge for items rated PG / FSK 6 or lower.",
        "media_scope": "BOTH",
        "target": "POSTER",
        "condition": {
            "all": [
                {"field": "min_age", "op": "lte", "value": 6},
                {"field": "min_age", "op": "gte", "value": 0},
            ]
        },
        "elements": [
            {
                "type": "text",
                "text": "FAMILY",
                "x": "center",
                "y": "bottom",
                "padding": 12,
                "font_size": 22,
                "color": "#ffffff",
                "background": "#3a55aaee",
                "background_radius": 4,
            }
        ],
        "z_order": 1,
    },
]


def all_default_slugs() -> list[str]:
    """Every slug across smart-collection and overlay defaults (for tests)."""
    return [entry["slug"] for entry in SMART_COLLECTION_DEFAULTS] + [
        entry["slug"] for entry in OVERLAY_DEFAULTS
    ]
