# streamarr.media — Backend

FastAPI REST API and async task worker for the streamarr.media self-hosted media server.

## Stack

- **Python 3.11+** with FastAPI and async/await throughout
- **PostgreSQL** (asyncpg) — primary database
- **Redis** — task queue, caching, WebSocket pub/sub
- **Taskiq** — distributed background workers
- **SQLAlchemy 2.0** — async ORM with Alembic migrations
- **Docker** — FFmpeg transcoding containers launched on demand

## Architecture

```
API (FastAPI)
  ├── Auth         JWT + OIDC, invite system, user groups
  ├── Media        Unified model for movies, shows, games, music, books
  ├── Libraries    Plugin-based: each type has its own scoring, naming, import logic
  ├── Search       Provider-first (TMDB, IGDB, Spotify) with local Elasticsearch fallback
  ├── Play         On-demand transcoding (HLS), codec negotiation, trickplay sprites
  ├── Stream       HLS segment serving with token auth
  ├── Downloads    SABnzbd, Deluge, spotdl — routed by media type
  ├── Indexers     Newznab/Torznab with tier-based search (ID → title fallback)
  ├── Lists        User & system lists, trending, favorites, soft-delete
  ├── Watch Party  Synchronized playback via WebSocket
  └── WebSocket    Real-time events, remote control, device tracking

Worker (Taskiq)
  ├── Metadata import    TMDB, IGDB, Spotify → unified media items
  ├── Release search     Sonarr-inspired matching, quality scoring, language filtering
  ├── Download handling  Queue, monitor, import completed downloads
  ├── Trending           Periodic list updates with release availability checks
  └── Transcoding        FFmpeg container lifecycle, trickplay generation
```

## Quick Start

```bash
uv sync
cp .env.example .env  # configure SECRET_KEY, DATABASE_URL, REDIS_URL

# Dev server
uv run uvicorn streamarr.web:app --reload --port 8000

# Worker
uv run taskiq worker streamarr.worker:broker

# Migrations
uv run alembic upgrade head
```

## Testing

```bash
uv run pytest                              # all tests (SQLite in-memory)
uv run pytest tests/test_release_parser.py # single file
uv run pytest -k "search" -v              # by keyword
uv run pytest --cov=streamarr                 # with coverage
```

## Key Design Decisions

- **Unified media model** — movies, shows, episodes, games, albums, songs share one `MediaItem` table with `media_type` enum and parent/child hierarchy
- **Plugin system** — library types (movies, shows, music, games, books) register via plugins that define media types, scoring rules, naming templates, and import logic
- **Release scoring** — configurable per-library weights for resolution, source, codec, language, release groups. Releases with disallowed languages are hard-rejected (score 0)
- **Tier-based indexer search** — ID-first (TVDB/IMDB), title fallback if no results, with year mismatch rejection and pagination limits (max 1000 results)
- **On-demand everything** — media files are downloaded and transcoded only when a user hits play, not eagerly

## License

Proprietary. All rights reserved.
