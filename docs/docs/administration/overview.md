# Administration Overview

This section covers the administration features of streamarr.media. The admin area lives at `/admin` and is reachable via the **user menu (top right) → Administration**.

!!! note "Who can access the admin area?"
    Only users with **superuser privileges** can open `/admin`. Regular permissions and groups control what users can see and play — they never grant admin access. See [Users & Groups](user-management.md).

## First Steps as Admin

After [installation](../getting-started/installation.md), the setup wizard at `/install` creates your admin account. From there, a typical setup order is:

1. **Configure metadata providers** — TMDB/TVDB for movies and shows, IGDB for games, MusicBrainz/Spotify for music, OpenLibrary for books → [Plugins](plugins.md)
2. **Create libraries** — at least one library per media type you want to serve → [Libraries](libraries.md)
3. **Add indexers** — Newznab/Torznab sources for automated release searching → [Indexers](indexers.md)
4. **Set up download clients** — SABnzbd, Deluge, or the built-in torrent/usenet/Spotify downloaders → [Download Clients](downloaders.md)
5. **Review transcoding** — containerized FFmpeg settings and playback profiles → [Transcoding](transcoding.md)
6. **Invite users** — create accounts, groups, permissions, and parental controls → [Users & Groups](user-management.md)
7. **Customize the experience** — home page layouts, banners, curated content → [Page Layouts](page-layouts.md)

## Admin Areas

The tables below follow the four sections of the admin sidebar.

### Monitoring & Queues

| Menu item | What it does | Documentation |
|-----------|--------------|---------------|
| **Dashboard** | System health, active streams, downloads, user stats, library sizes, storage | [Dashboard](dashboard.md) |
| **Downloads** | Live download queue with progress and speed | [Download Clients](downloaders.md) |
| **Active Sessions** | Running transcoding/streaming sessions | [Monitoring](monitoring.md) |

### Libraries

Each library type (Movies, Shows, Games, Music, Books) has its own settings page, covering paths, metadata, quality profiles, and release scoring. New libraries are created via **Create Library**. See [Libraries](libraries.md).

### Users & Curation

| Menu item | What it does | Documentation |
|-----------|--------------|---------------|
| **Users** / **Groups** | Accounts, groups, permissions, parental controls | [Users & Groups](user-management.md) |
| **Invites** | Invitation-based registration | [Users & Groups](user-management.md) |
| **Devices** | Registered devices across all users | [Users & Groups](user-management.md); user side: [Devices, Casting & Offline](../user-guide/devices.md) |
| **Lists** | Browse and manage all user and system lists by type, visibility, and owner | [Smart Collections & Overlays](smart-collections.md) |
| **Smart Collections** | Rule-based lists populated automatically from external sources (Trakt, IMDb, Letterboxd, …) on a cron schedule | [Smart Collections & Overlays](smart-collections.md) |
| **Poster Overlays** | Composite badges (4K, HDR, streaming logos, …) onto posters via conditional templates | [Smart Collections & Overlays](smart-collections.md) |
| **Mass Operations** | Rule-based bulk metadata edits (genres, studios, sort titles, …) | [Smart Collections & Overlays](smart-collections.md) |
| **Page Layouts** | Configure home and library page sections | [Page Layouts](page-layouts.md) |

### System

| Menu item | What it does | Documentation |
|-----------|--------------|---------------|
| **Banners** | System-wide announcements shown to users | [Banners](banners.md) |
| **Subscription Packages** | Plans users can subscribe to via Stripe, with group assignments | [Membership & Vouchers](membership.md) |
| **Vouchers** | Redeemable membership codes, batch creation and CSV export | [Membership & Vouchers](membership.md) |
| **Settings** | Site name, OIDC SSO, subscription/invite/friends toggles, library toggles, favorites automation, global permission defaults, backup & restore | [System Settings](system-configuration.md) |
| **Transcoding** | FFmpeg transcoding configuration | [Transcoding](transcoding.md) |
| **Downloaders** | Download client connections | [Download Clients](downloaders.md) |
| **Indexers** | Newznab/Torznab indexer management | [Indexers](indexers.md) |
| **Metadata** | Metadata provider configuration | [Plugins](plugins.md) |
| **Game Runtimes** | Container images and environments that cloud-gaming sessions launch in | [System Settings](system-configuration.md); hosting: [Deployment](../deployment/overview.md) |
| **Tasks** | Manually trigger background tasks and inspect run history | [Maintenance & Backups](maintenance.md) |
| **Logs** | Transcoding session logs and filterable activity logs (event type, severity, entity, date) | [Monitoring](monitoring.md) |
| **Parties** | Overview of active watch parties and connected users | [Monitoring](monitoring.md); user side: [Watch Parties](../user-guide/watch-parties.md) |

!!! tip "Some entries are conditional"
    **Subscription Packages** and **Vouchers** only appear in the sidebar while subscriptions are enabled under **Settings → Subscriptions & Payments**. When disabled, all users have unrestricted access and subscription UI is hidden.

!!! warning "Back up before bulk changes"
    Mass operations, overlay re-renders, and database restores affect many items at once. Export a settings or database backup first — see [Maintenance & Backups](maintenance.md).
