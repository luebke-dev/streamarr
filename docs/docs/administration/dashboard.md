# Admin Dashboard

The admin dashboard is the landing page of the admin area and gives you an at-a-glance overview of your pyrate.media instance: system health, active streams, downloads, users, library sizes, and storage.

## Access

The admin area is only accessible to users with **superuser privileges**. Open it via:

- **User Menu** (top right) → **Administration**
- Or directly at `/admin`

!!! note
    Dashboard figures are loaded when you open the page. Reload the page to refresh them.

## Status Cards

Four status cards at the top show key metrics:

| Card | Description | Click Action |
|------|-------------|--------------|
| **System Health** | Green (Healthy) or red (Unhealthy) — checks whether the backend API responds | — |
| **Active Streams** | Number of running streaming sessions | Opens Active Sessions |
| **Active Downloads** | Downloads currently queued or in progress | Opens Downloads |
| **Active Users** | Total users / users currently online | Opens [User Management](user-management.md) |

## Library Overview

A compact row of chips showing the item count per library type: Movies, Shows, Music (song count), Games, and Books. Only library types that contain items are displayed. See [Libraries](libraries.md) for creating and configuring libraries.

## Active Streams

Lists up to five current streaming sessions (the card is hidden when nothing is playing):

- **Media title** and type icon (movie/TV)
- **User** who is streaming
- **Codec info**: video/audio codec and, if known, resolution
- **Duration** the stream has been running
- **View All** opens the full Active Sessions page

## Recent Downloads

Shows the five most recent downloads, newest first:

- **Title** of the release
- **Started by**: which user triggered the download
- **Timestamp**: relative start time ("Just now", "5m", "2h", "1d")
- **Status badge**: downloading (blue), completed (green), failed (red), queued (grey), importing (amber)
- **Progress bar** while a download is actively downloading

**View All** opens the Downloads page. Indexers and download clients are configured under [Indexers](indexers.md) and [Download Clients](downloaders.md).

## Storage (Sidebar)

Disk usage overview:

- **Per library**: space consumed by each library directory, with bars showing the relative share
- **Downloads**: size of the download directory, plus the usage percentage of the underlying disk
- **Transcodes**: temporary transcode files, plus the usage percentage of the underlying disk

!!! tip
    If the transcode directory keeps growing, review your session cleanup settings under [Transcoding](transcoding.md) and the storage-cleanup task in [Maintenance & Backups](maintenance.md).

## System Information (Sidebar)

- **Indexers**: number of configured indexers
- **Active Downloaders**: number of configured download clients
- **Libraries**: number of created libraries (including disabled ones)

## Quick Actions (Sidebar)

Shortcut buttons for common admin tasks:

- Add Library
- Manage Users
- Manage Sessions
- Metadata Providers
- System Settings

## Admin Navigation

The sidebar of the admin area links to all management pages, grouped as follows:

=== "Menu"

    Dashboard, Downloads, Active Sessions, and Home (back to the main app).

=== "Libraries"

    Direct links to the per-type library settings: Movies, Shows, Games, Music, Books.

=== "Users"

    Users, Groups, Invites, Devices, Lists, [Smart Collections](smart-collections.md), Poster Overlays, Mass Operations, [Page Layouts](page-layouts.md).

=== "System"

    [Banners](banners.md), Settings, Transcoding, Downloaders, Indexers, Metadata, Game Runtimes, Tasks, Logs, Parties. If subscriptions are enabled in the server settings, **Subscription Packages** and **Vouchers** also appear here — see [Membership & Vouchers](membership.md).

For server-level metrics beyond the dashboard (Prometheus/Grafana), see [Monitoring](monitoring.md).
