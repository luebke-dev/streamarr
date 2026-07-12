# Library Management

Libraries are the core of pyrate.media. Each library manages one media type and carries its own storage path, naming conventions, release scoring, and quality profiles. **Only one library per type can exist** — the type dropdown only offers types that do not already have an enabled library.

## Creating a Library

1. Open **Admin → Dashboard** and use the **Add Library** quick action (route `/admin/libraries/create`)
2. Fill in the form:

| Field | Description |
|-------|-------------|
| **Library Name** | A unique name for this library |
| **Library Type** | Movies, Shows, Music, Games, Books, or Photos |
| **Library Plugin** | Plugin that manages this library — auto-selected when only one exists |
| **Metadata Provider** | Optional provider for fetching metadata, filtered by media type; unconfigured providers are flagged **Not Configured** — see [Plugins](plugins.md) |
| **Library Path** | Existing directory where files are stored, e.g. `/data/library/movies` — validated by the backend |
| **Description** | Optional |
| **Library Enabled** | Whether the library is active |

!!! warning "Container paths"
    The library path is resolved *inside* the backend container and must already exist. Make sure the corresponding volume is mounted in your Docker/Kubernetes deployment.

After creation, each library appears in the admin sidebar under **Libraries** (Movies, Shows, Games, Music, Books) with its own settings page at `/admin/libraries/<type>`.

## Library Settings

### Library Configuration

| Setting | Description | Available for |
|---------|-------------|---------------|
| **Enable Library** | Toggles the library on/off | All |
| **Library Path** | Absolute path to media file storage | All |
| **Enable On-Demand Downloads** | Smart Play — pressing play on missing media triggers an automatic download | Movies, Shows, Music |
| **Enable Prefetch Downloads** | Auto-download the next episode when playing | Shows |
| **Hide Season 0 (Specials)** | Globally hides specials/extras | Shows |
| **Allowed Languages** | Only releases in these languages are scored positively; empty = all languages | Movies, Shows |
| **Allowed Platforms** | Only show games available on these platforms; empty = all | Games |

### Naming Conventions

Templates control how downloaded files and folders are named. The available template fields depend on the library type; click the help icon on any template field to open the **Available Variables** dialog with descriptions and examples (title, year, TMDB/TVDB/IMDb IDs, season/episode numbers, resolution, codecs, HDR format, source, release group, …).

=== "Movies (defaults)"

    - **Folder**: `{movie_title} ({movie_year})`
    - **File**: `{movie_title} ({movie_year})`

=== "Shows (defaults)"

    - **Series Folder**: `{series_title} ({series_year})`
    - **Season Folder**: `Season {season_number_2}`
    - **Episode File**: `{series_title} - S{season_number_2}E{episode_number_2} - {episode_title}`

Additional options: **Replace Illegal Characters** and **Colon Replacement** (space, dash with spaces, or delete). **Show Preview** renders an example folder, file, and full path before you save, and **Reset to Defaults** restores the built-in templates.

### Download Scoring Rules

*Movies and Shows only.* Controls how releases from your [indexers](indexers.md) are scored when selecting the best download — higher scores win.

- **Weights** per **Resolution**, **Source**, **Video Codec**, and **Audio Codec**
- **Bonus Points**: HDR, Dolby Vision, Remux, PROPER, REPACK, and a Trusted Group Bonus
- **Trusted Release Groups**: groups that receive the trusted bonus
- **Blocked Release Groups**: releases from these groups are always scored 0 and never downloaded
- **Language Scoring**: match bonus / mismatch penalty, evaluated against the library's allowed languages

**Reset to Defaults** restores the built-in scoring configuration.

### Quality Profile

*Movies, Shows, Music, Books, and Games.* A Sonarr-style ordered list of allowed qualities: releases are picked by the highest allowed quality, and upgrades continue until the **cutoff** is reached. Each library has two profiles:

- **Standard** — applies to everything
- **Favorites** — optional override for favorited items (used with the "keep favorites" automation in [System Settings](system-configuration.md)); if unset, the standard profile applies

The quality ladder depends on the media type — video ranges from CAM up to Bluray-2160p Remux, audio from MP3 to Lossless Hi-Res, books from Scan/OCR to Retail EPUB. Toggle **Allow upgrades to better releases** to enable quality-upgrade scans.

### Danger Zone

**Delete Library** removes the library after a confirmation dialog. This cannot be undone — all associated data is lost.

## Scanning and Metadata Refresh

- **Import existing files**: `POST /api/libraries/{guid}/scan` (superuser) scans the library path with the library's plugin and imports discovered media. There is currently no scan button in the admin UI.
- **Per-item refresh**: admins get a **Refresh Metadata** action on every media detail page.
- **Automatic refresh**: a nightly background job re-fetches metadata for items not updated in the last 30 days (up to 100 items per run).
- **Trending imports**: the **Trending … Refresh** tasks (movies/shows/games/music) can be triggered from **Admin → Tasks** — see [Maintenance & Backups](maintenance.md).

## Per-Library Access

Which libraries a user can see is controlled by permissions, not by the library itself: set **Library Access → Allowed Libraries** on a group, or override it per user, alongside parental controls and quality limits. See [Users & Groups](user-management.md).
