# Overview

**Your media, your rules.** streamarr.media is a self-hosted, all-in-one platform for media management, streaming, and automation. It combines what usually takes half a dozen tools — a streaming media center, release automation, and cloud gaming — with one library, one user system, and one UI.

## What is streamarr.media?

With streamarr.media you can:

- **Discover** — find movies, shows, music, games, and books via rich metadata, trending lists, and recommendations
- **Organize** — manage everything in libraries, lists, playlists, and collections
- **Stream** — play directly in the browser, on desktop, or on Android, with on-the-fly transcoding
- **Automate** — search indexers and start downloads automatically, right from the play button
- **Play** — stream games from your server to your browser via cloud gaming
- **Share** — host watch parties, invite friends, and optionally sell memberships

## One library, six media types

Every library type shares the same unified media model, so browsing, search, favorites, and lists work the same everywhere.

| Media type | Metadata | Highlights |
|------------|----------|------------|
| 🎬 Movies | TMDB | Trailers, cast, collections, release automation — see [Movies & Shows](../user-guide/movies.md) |
| 📺 Shows | TVDB / TMDB | Seasons and episodes, next-up, per-episode automation — see [Shows in Detail](../user-guide/shows.md) |
| 🎵 Music | MusicBrainz, Spotify import | Artists, albums, songs; persistent player with queue and lyrics — see [Music](../user-guide/music.md) |
| 🎮 Games | IGDB, Steam import | Playable in the browser via cloud game streaming — see [Games](../user-guide/games.md) |
| 📖 Books | OpenLibrary | Authors and books with an in-app EPUB reader — see [Books](../user-guide/books.md) |
| 📷 Photos | Local files | Photo libraries using the same unified media model |

Admins create a library per media type and configure storage paths, metadata, and download rules — see [Libraries](../administration/libraries.md).

## Main capabilities

### Streaming & playback

Media plays directly in the client. When a file is compatible it direct-plays; otherwise the server transcodes it on demand and streams it as HLS. Playback includes subtitles, chapters, skip intro/outro markers, trickplay scrubbing thumbnails, and resume via continue watching. See [Streaming & Playback](../user-guide/streaming.md).

### Smart Play & automation

!!! tip "Press play on anything"
    You can start playback even for media you don't have a file for yet. streamarr.media searches your configured indexers, starts the download, and shows live status — *Searching for releases* → *Downloading* → *Ready to play*.

Behind the scenes, admins configure Newznab/Torznab [indexers](../administration/indexers.md) and [download clients](../administration/downloaders.md), including release scoring, auto-download of monitored favorites, and quality upgrades.

### Cloud gaming

Games in your library can be streamed straight to the browser: the server launches the game in an isolated container and streams video, audio, and input in real time. See [Games](../user-guide/games.md).

### Watch parties

Watch together with synchronized playback — create a party, share the party code, and everyone stays in sync. See [Watch Parties](../user-guide/watch-parties.md).

### Devices, casting & offline

Cast to Chromecast, AirPlay, and DLNA targets, remote-control playback on your other signed-in devices, and download media to a device for offline use. See [Devices, Casting & Offline](../user-guide/devices.md).

### Discovery & curation

Fast search with autocomplete and filters, genre and person browsing, trending and recommendations, plus [lists, playlists, and collections](../user-guide/lists.md). Admins can add rule-based [smart collections and poster overlays](../administration/smart-collections.md) and design the home page with [page layouts](../administration/page-layouts.md).

### Multi-user & memberships

Local accounts or SSO login, invite-based registration, groups with granular permissions, and parental controls — see [Users & Groups](../administration/user-management.md).

!!! note "Memberships are optional"
    Servers can offer paid subscription plans and vouchers. Users manage their plan under [Membership](../user-guide/membership.md); admins configure plans in [Membership & Vouchers](../administration/membership.md).

## Clients

| Platform | Delivery |
|----------|----------|
| Web | Runs in any modern browser |
| Desktop (Linux, macOS, Windows) | Native app (Tauri) |
| Android | Native app (Capacitor) |

The UI is available in English and German.

## Next steps

1. **[Installation](installation.md)** — deploy streamarr.media with Docker Compose, Kubernetes, or Podman
2. **[Quick Start](quick-start.md)** — first-run setup and your first library
3. **[Dashboard & Home](../user-guide/dashboard.md)** — get to know the interface
