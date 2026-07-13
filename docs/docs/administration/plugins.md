# Plugins & Metadata Providers

"Plugins" in streamarr.media covers two things today:

1. **Metadata providers** — external services (TMDB, TheTVDB, IGDB, Spotify, MusicBrainz, Shazam) that supply titles, artwork, descriptions, and identification. These are configured in the admin UI.
2. **The plugin package registry** — a metadata-only record of plugin repositories and package lifecycle state, managed via the API and displayed read-only in the admin UI.

!!! warning "No executable plugins"
    streamarr.media does **not** download or execute plugin code. The plugin registry stores repository, lifecycle, capability, and notification metadata only. Library types (movies, shows, music, games, books, photos) are built into the server and cannot be installed or removed.

## Metadata Providers

Navigate to **Admin** → **Metadata Providers**. Each provider appears as an expandable entry with a status chip: **Configured**, **Not Configured**, or **No Config Needed**.

| Provider | Supplies metadata for | Credentials required |
|----------|----------------------|----------------------|
| **TMDB** | Movies & TV shows | API Key (Bearer token) |
| **TheTVDB** | TV shows | API Key, optional Subscriber PIN |
| **IGDB** | Games | Twitch Client ID + Client Secret |
| **Spotify** | Music (artists, albums, tracks) | Client ID + Client Secret |
| **MusicBrainz** | Music | None |
| **Shazam** | Song identification from audio | None |

!!! note "Books"
    Book metadata comes from OpenLibrary, which needs no API key and therefore does not appear on this page. See [Books](../user-guide/books.md) for the reader experience.

### Getting credentials

=== "TMDB"

    Create an API key at [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) and paste it into the **API Key** field. TMDB powers movie and show metadata, including translations and trending lists.

=== "TheTVDB"

    Get an API key from your [TheTVDB dashboard](https://thetvdb.com/dashboard/account/apikey). The **Subscriber PIN** is optional and only needed for subscriber features.

=== "IGDB"

    IGDB authenticates through Twitch. Create an application at [dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps) and enter its **Client ID** and **Client Secret**.

=== "Spotify"

    Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and enter its **Client ID** and **Client Secret**. This is metadata only — it is separate from the Spotify downloader service.

### Configuring and testing

1. Expand the provider and fill in its fields (secrets are masked; use the eye icon to reveal them).
2. Click **Test Connection** to verify the credentials.
3. Click **Save**.

!!! tip
    **Test Connection** uses the values currently in the form, so you can verify credentials before saving. With an empty form it tests the stored configuration instead.

When you create a library, you choose a metadata provider compatible with its media type; providers that are not yet configured are flagged in the selection, so set up your providers first. See [Libraries](libraries.md).

## Plugin Package Registry

Superusers can record plugin repositories and package metadata through the REST API under `/api/plugins`. The admin UI shows this data in the **Plugin Runtime Metadata** section of **Admin** → **Packages** (shared with [subscription packages](membership.md)): installed/enabled counts, the runtime scope, configured repositories with a per-repository **sync** action, and a table of packages with status, version, runtime kind, capabilities, and notification events.

Package statuses are: Installed, Disabled, Update available, Restart required, Failed, Uninstalled.

Key endpoints (superuser only):

| Endpoint | Purpose |
|----------|---------|
| `GET/PUT /api/plugins/repositories` | List or replace repository entries |
| `POST /api/plugins/repositories/{id}/sync` | Queue a repository metadata refresh |
| `GET/PUT /api/plugins/installed` | List or replace package metadata |
| `POST /api/plugins/installed/{id}` | Create/replace one package's metadata (plus `/enable`, `/disable`, `/update`) |
| `GET /api/plugins/runtime-policy` | The server's runtime contract (metadata-only) |
| `GET /api/plugins/validation` | Validate stored metadata |

Validation enforces that plugin-advertised notification event types use the `plugin.` prefix, don't collide with the core notification catalog or other plugins, and that capability tokens are lowercase. All registry changes are recorded in the activity log.

## What is *not* a plugin

Indexers and download clients have their own configuration pages — see [Indexers](indexers.md) and [Download Clients](downloaders.md).
