# Indexers

Indexers are the search services streamarr.media queries to find **releases** — downloadable copies of movies, episodes, music, games, and books. Every automation feature that acquires media (Smart Play, [favorites](../user-guide/favorites.md) auto-download, quality upgrades, RSS sync) searches through the indexers configured here. The releases they return are downloaded by a [download client](downloaders.md).

## Supported types

| Type | Protocol | Typical use |
|------|----------|-------------|
| **Newznab** | Usenet indexer API | NZB indexers |
| **Torznab** | Newznab-compatible API for torrents | Jackett, Prowlarr, native Torznab trackers |

## Adding an indexer

Navigate to **Admin → Indexers** and click **Add Indexer**. A two-step wizard opens.

### Step 1: Connection

| Field | Description |
|-------|-------------|
| **Name** | A descriptive label |
| **Type** | Newznab (Usenet) or Torznab (Torrent) |
| **Host / URL** | e.g. `https://indexer.example.com` |
| **API Key** | Your personal API key from the indexer |
| **Use SSL** / **Verify SSL certificate** | Connection security options |
| **Enabled** | Whether the indexer participates in searches |
| **RSS sync** | Opt this indexer into the periodic RSS poll (see below) |
| **Priority** | Lower numbers are queried first (default `25`) |

Click **Test Connection**. The test contacts the indexer, validates the URL and API key, and fetches its capabilities; on success you see *"Connection successful — N categories found"* and the wizard advances.

### Step 2: Categories

Select the categories you want to search from the tree the indexer reported. For each selected category you assign:

- **Media Type** — Movies, Series, Music, Games, Books, Audiobooks, or Other. Pre-filled from the standard Newznab ID ranges (2000s → Movies, 3000s → Music, 5000s → Series, 6000s → Games, 7000s → Books).
- **Languages** and **Resolutions** (optional) — hints describing what this category contains.

!!! tip "Category hints improve scoring"
    Language and resolution hints are used as fallbacks: when a release title itself doesn't reveal its language or resolution, the category's hints are applied before scoring. This helps a lot with single-language indexer categories (e.g. a "Movies/German" category).

## Editing an indexer

**Edit** on the indexer list reopens the wizard. Notes:

- The API key is never sent back to the browser — leave the field empty to keep the existing key.
- **Continue without test** skips the connection test; **Reload categories** re-fetches the capability tree while keeping your saved category assignments.
- The last RSS sync time is shown on the connection step.

## How a search works

Searches fan out concurrently to every enabled indexer whose categories match the media type, using a tiered, ID-first strategy (Sonarr/Radarr-style):

=== "Movies"
    1. **Tier 0** — IMDb-ID search, no query text
    2. **Tier 1** — title search, only if tier 0 returned nothing

=== "TV shows"
    1. **Tier 0** — TVDB/IMDb-ID search with season/episode parameters
    2. **Tier 1** — title search fallback

=== "Music / Books"
    1. **Tier 0** — structured search (artist + album / author + title)
    2. **Tier 1** — combined text query fallback

Results are de-duplicated across tiers and indexers. Transient network errors are retried; a rate-limited indexer (HTTP 429) fails that search rather than hammering the service.

## Release matching and scoring

Returned releases go through a strict pipeline before anything is grabbed:

1. **Rejection filters** — video releases under 50 MB (samples), raw disc images (ISO/BDMV/VIDEO_TS), multi-season packs when a single episode is wanted, and releases published before the media's release date are dropped.
2. **Title matching** — releases are matched against the media item by external ID first, then exact, normalized, title+year, and finally fuzzy title similarity.
3. **Quality/language scoring** — each surviving release is scored using the library's **Download Scoring Rules** (per-library, under [Libraries](libraries.md) → library settings): weights for resolution, source, video and audio codec, trusted release groups (bonus) and blocked release groups (always scored 0), plus a language match bonus. Releases whose language is outside the library's allowed languages are rejected. Fresh releases get a small age bonus, very old ones a penalty.
4. The highest-scoring release is dispatched to a matching [download client](downloaders.md) and imported after completion.

## RSS sync

RSS sync periodically polls the latest-releases feed of every indexer with the **RSS sync** toggle enabled, so new releases of monitored favorites are grabbed minutes after they appear instead of waiting for the next scheduled search.

- Enable it globally in **Admin → Settings** under **Favorites Automation** (*"RSS sync (poll indexers for new releases)"*), and set the poll interval (default 15 minutes).
- Enable it per indexer in the indexer's connection step. Indexers are polled in priority order.
- Feed items are matched against monitored favorites by title. A match only *triggers* the normal search-match-score pipeline above — raw feed items are never downloaded directly, so a noisy feed cannot cause a false grab.

!!! note
    RSS sync only results in downloads when favorites auto-download is also enabled in **Favorites Automation**. See [System Settings](system-configuration.md) for the surrounding automation switches.
