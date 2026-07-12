# Smart Collections & Overlays

pyrate.media ships a Kometa-style automation toolkit for keeping your catalogue curated without manual work: **Smart Collections** populate lists from external charts or your own library on a schedule, **Poster Overlays** stamp conditional badges (4K, HEVC, …) onto artwork, and **Mass Operations** apply rule-based bulk edits to metadata. All three live in the admin area and run as background worker tasks.

## Smart Collections

Navigate to **Admin** -> **Smart Collections**. Each rule fetches items from a *builder*, filters them, and syncs the result into a **public system list** (created automatically on the first run). Those lists show up like any other list — browseable by users (see [Lists & Collections](../user-guide/lists.md)) and usable as **List** sections in [Page Layouts](page-layouts.md).

### Rule anatomy

| Field | Description |
|-------|-------------|
| **Media type** | `MOVIE` or `SHOW` |
| **Builder** | The item source (see below) |
| **Builder config** | Source-specific settings, e.g. which chart or list to pull |
| **Filters** | Post-fetch filtering: min/max rating, year range, parental-age range, availability, original language, genre include/exclude, `require_files` |
| **Sync mode** | `SYNC` mirrors the source exactly (removes items that dropped out); `APPEND` only ever adds new items |
| **Max items** | Cap on list size (default 80, up to 2000) |
| **Cron** | Standard cron expression, e.g. `0 6 * * *`; due rules are picked up within a minute |

### Builders

| Builder | Pulls from | API key |
|---------|-----------|---------|
| `tmdb` | TMDB charts (popular, trending, top rated, now playing, upcoming) and full `discover` queries | Required |
| `trakt` | Trakt charts (trending, popular, watched, anticipated) | Required (client ID) |
| `mdblist` | MDBList lists | Required |
| `imdb` | IMDb charts (Top 250, MovieMeter, …) and public lists by list ID | None |
| `letterboxd` | Letterboxd user lists, a user's watched films, popular this week | None |
| `mal` / `anilist` | MyAnimeList / AniList anime charts, seasonal and genre listings | None |
| `library_filter` | Your own catalogue (year/decade ranges, genre, sorting) — no external calls | None |

!!! note "API keys"
    The builder picker tells you whether a source needs a key. Keys are stored in the server settings table under `smart_collections.api_keys`, keyed by builder slug (e.g. `tmdb`, `trakt`, `mdblist`) — there is no dedicated settings form for this yet. Keyless sources work out of the box.

Fetched items are matched against your catalogue by external IDs (with a title+year fallback). Items you don't have locally are counted as **unresolved** and skipped — the per-rule **History** dialog shows added/removed/unresolved counts and errors for each run. **Run now** queues an immediate run; results also appear in the activity log (see [Maintenance & Backups](maintenance.md)).

### Bundled default rules

A fresh install seeds dozens of ready-made rules — TMDB/Trakt/IMDb movie and show charts, per-streaming-service collections (Netflix, Disney+, …) via TMDB discover, and by-decade library collections. All ship **disabled** so a new server doesn't hammer external APIs; toggle on the ones you want.

!!! tip "Check the region on streaming collections"
    The streaming-service defaults query TMDB with `watch_region: US`. Edit the builder config if your server serves another region.

!!! warning "System rules are protected"
    Rules marked as system (the bundled defaults) can't be deleted, and only their cron and enabled toggle are editable.

## Poster Overlays

Navigate to **Admin** -> **Poster Overlays**. A template composites text or image **elements** onto poster or backdrop artwork for movies, shows, or both. Multiple matching templates stack by **z-order**.

An optional **condition** decides per item whether the overlay renders — a tree of *all*/*any* groups over fields like `resolution.height`, `resolution.label`, `media_type`, `year`, `title`, `availability`, `min_age`, `genres`, and `codecs.video`/`codecs.audio`. Without a condition, the overlay applies to every in-scope item. The edit dialog includes a **live preview**: paste a media item GUID to see the rendered result.

Rendering happens entirely in the background — after import and file probing, via a periodic sweep for missing renders, and on demand. The app serves posters through an overlay-aware route that falls back to the original artwork until a render is cached, so overlays never slow browsing down. After editing a template, use **Re-render all items** to queue a bulk re-render.

Bundled (disabled) defaults include 4K/1080p/720p resolution badges, an HEVC badge, a "downloadable" marker, and a family-safe badge.

## Mass Operations

Navigate to **Admin** -> **Mass Operations** for rule-based bulk metadata edits. A rule pairs a **target filter** (same style as smart-collection filters: media type, year/age ranges, availability, genres, `require_files`) with one **action**:

| Action | Effect |
|--------|--------|
| Set genres | Add to or replace an item's genres |
| Set parental rating | Override `min_age` |
| Set availability | Override availability status |
| Set description / poster URL | Override the field |
| Clear a field | Blank description, tagline, artwork paths, content rating, or `min_age` |

Rules can run on a cron schedule (leave it empty for manual-only) or immediately via **Run now**.

!!! tip "Always dry-run first"
    The **Dry run** action reports how many items would match, be updated, or be skipped — plus a sample of affected item GUIDs — without changing anything. You can apply directly from the dry-run result.

## All Lists

**Admin** -> **Lists** gives an overview of every list on the server — system and user lists alike — filterable by type and visibility, with item/like counts. From here you can open any list or delete it; the target lists created by smart collections are managed here too.
