# Admin Dashboard

The admin dashboard provides a real-time overview of your Pyrate.Media instance.

## Access

The admin area is only accessible to users with **superuser privileges**. Access it via:

- **User Menu** (top right) -> **Admin Panel**
- Or directly at `/admin`

## Status Cards

Four status cards at the top show key metrics:

| Card | Description | Click Action |
|------|-------------|--------------|
| **System Health** | Green (Healthy) or Red (Unhealthy) - checks if the backend is reachable | - |
| **Active Streams** | Number of running transcoding sessions | Opens Sessions page |
| **Active Downloads** | Number of active downloads | Opens Downloads page |
| **Users** | Total users / active users | Opens User Management |

## Library Overview

A compact overview of all libraries showing item counts:

- Movies (purple), Shows (teal), Music (pink), Games (green), Books (amber)
- Only libraries with content are displayed

## Active Streams

Shows the last 5 active streaming sessions with:

- **Media title** and type icon (movie/TV)
- **User** currently streaming
- **Codec info**: video/audio codec and resolution
- **Duration**: How long the stream has been running
- **"View All"** button for the full sessions overview

## Recent Downloads

Shows current downloads with:

- **Title** of the media
- **Started by**: Which user triggered the download
- **Timestamp**: When the download started (relative: "5m", "2h", "1d")
- **Status badge**: downloading (blue), completed (green), failed (red), queued (grey), importing (amber)
- **Progress bar** for active downloads

## Storage Overview (Sidebar)

Shows disk usage:

- **Per library**: Disk space consumed with progress bar
- **Downloads**: Space used in the download directory with disk usage percentage
- **Transcodes**: Temporary files in the transcode directory

## System Information (Sidebar)

- **Active Indexers**: Number of configured and active indexers
- **Active Downloaders**: Number of configured download clients
- **Libraries**: Number of created libraries

## Quick Actions (Sidebar)

Shortcut buttons for common admin tasks:

- Add Library
- Manage Users
- Manage Sessions
- Manage Plugins
- System Settings

## Admin Navigation

The sidebar in the admin area provides access to all management areas:

**Main:**

- Dashboard, Downloads, Active Sessions, Back to Home

**Libraries:**

- Dynamic list of all enabled libraries (clickable for settings)
- "Create New Library" button

**Users & Social:**

- Users, Groups, Invites, Devices, Lists

**System:**

- Banners, Settings, Transcoding, Downloaders, Indexers, Plugins, Tasks, Logs, Watch Parties, Page Layouts
