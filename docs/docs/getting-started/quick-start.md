# Quick Start

This guide takes a freshly [installed](installation.md) pyrate.media server from an empty database to a working instance: create the first admin account, configure metadata providers, create libraries, wire up download automation, import some content, and invite your users.

## 1. Run the setup wizard

Open `http://<your-server>/install` in a browser. The wizard is only available while no user account exists — afterwards it reports "System already installed" and points you to the login page.

The wizard has three steps:

1. **Administrator Account** — first name, last name, email address, and a password (at least 8 characters, containing an uppercase letter, a lowercase letter, and a digit). The first account is automatically a full administrator.
2. **System Configuration** — the site name (shown as the name of your media collection) and the default system language (English or German).
3. **Confirmation** — review your entries and click **Complete Setup**.

You are redirected to the login page; sign in with the credentials you just created. Site name and language can be changed later under **Administration → Settings**.

## 2. Configure metadata providers

Go to **Administration → Metadata**. Each provider shows whether it is **Configured**, **Not Configured**, or needs no configuration at all. Expand a provider, enter its credentials, use **Test Connection**, and save.

| Provider | Used for | Credentials |
|----------|----------|-------------|
| TMDB | Movies & shows | API key (Bearer token) |
| TVDB | TV shows | API key, optional subscriber PIN |
| IGDB | Games | Twitch Client ID + Client Secret |
| Spotify | Music | Client ID + Client Secret |
| MusicBrainz | Music | none required |
| OpenLibrary | Books | none required |

!!! tip "Providers first, libraries second"
    Configure providers **before** creating libraries — the library form auto-selects a compatible metadata provider and warns you if none is configured for the chosen type.

See [Metadata Providers](../administration/plugins.md) for details.

## 3. Create your libraries

Go to **Administration → Libraries → Create Library** and create one library per media type you want to serve: **Movies**, **Shows**, **Music**, **Games**, **Books**, or **Photos**.

- **Library Type** — the media type; the matching library plugin and metadata provider are selected automatically.
- **Library Name** — a unique name.
- **Library Path** — where files are stored. The path must be an **existing directory** visible to the backend, e.g. `/data/library/movies`.

!!! warning "One library per type"
    Only one library of each type can be created.

Per-library settings — file naming templates, download rules, and quality/release scoring — are covered in [Libraries](../administration/libraries.md).

## 4. Wire up download automation (optional)

Skip this section if you only stream existing files. With at least one indexer and one download client configured, **Smart Play** works: pressing play on an item you don't have yet searches your indexers, downloads the best-scored release, and starts streaming.

=== "Indexers"

    **Administration → Indexers → Add Indexer.** Choose **Newznab** (Usenet) or **Torznab** (torrents), then enter a name, the host/URL, and your API key. The form tests the connection before saving (you can also continue without a test). Options include RSS sync and per-indexer priority. See [Indexers](../administration/indexers.md).

=== "Download clients"

    **Administration → Downloaders → Add Downloader.** Choose **SABnzbd** (Usenet), **Deluge** (torrents), or **SpotDL** (Spotify music), give it a label, and fill in the connection fields for that client type, including the SSL options. See [Download Clients](../administration/downloaders.md).

## 5. Import trending content (optional)

To fill empty libraries and the home page with popular titles, go to **Administration → Tasks** and run the trending refresh tasks in the **Metadata** category:

- **Trending Movies Refresh** and **Trending Shows Refresh** (from TMDB)
- **Trending Games Refresh** (from IGDB)
- **Trending Music Refresh** (from Spotify Charts)

Each task imports the current trending items into the matching library and keeps a trending list up to date. These tasks also run automatically on a schedule.

## 6. Invite your users

Registration requires an invite by default. Go to **Administration → Invites → Create Invite**, optionally set a description, expiry date, and maximum number of uses, then copy the invite link and share it. The link opens the registration page with the invite applied.

Alternatively, create accounts directly under **Administration → Users → Add User**. Organize users into groups with library access, streaming limits, and parental controls — see [Users & Groups](../administration/user-management.md).

## Next steps

- [Dashboard & Home](../user-guide/dashboard.md) — the home page and its configurable sections
- [Streaming & Playback](../user-guide/streaming.md) — direct play, transcoding, and the player
- [Administration Overview](../administration/overview.md) — everything else in the admin area
