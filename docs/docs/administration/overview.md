# Administration Overview

This section covers all administration features of Pyrate.Media. Only users with **superuser privileges** can access the admin area.

## Getting Started as Admin

After installation, the first steps as administrator are:

1. **Configure Plugins**: Set up TMDB (for movies/shows) and optionally IGDB (for games)
2. **Create Libraries**: At least one library for your preferred media type
3. **Add Indexers**: For automatic release searching (Newznab/Torznab)
4. **Set Up Download Clients**: SABnzbd (Usenet) or Deluge (Torrents)
5. **Configure Transcoding**: Enable streaming and set quality preferences
6. **Customize Page Layouts**: Configure what users see on the home page

## Admin Areas

### Content Management

- [Libraries](libraries.md) - Create and configure media libraries, download rules, naming schemas
- [Page Layouts](page-layouts.md) - Customize the home page and library pages with configurable sections
- [Banners](banners.md) - Display system-wide announcements to users

### Integration & Automation

- [Plugins](plugins.md) - Install and configure metadata providers, download clients, and more
- [Indexers](indexers.md) - Set up Newznab/Torznab indexers for release searching
- [Download Clients](downloaders.md) - Configure SABnzbd and Deluge for automated downloads
- [Transcoding](transcoding.md) - Configure FFmpeg-based streaming settings

### User Management

- [Users & Groups](user-management.md) - Create, edit, and manage user accounts and groups
- [Devices](devices.md) - View registered devices and active sessions
- [Invites](invites.md) - Manage the invitation system

### Monitoring

- [Dashboard](dashboard.md) - Real-time system overview with status cards, active streams, downloads, and storage
- [Active Sessions](sessions.md) - Monitor and manage running transcoding sessions
- [Tasks](tasks.md) - View background task queue and status
- [Logs](logs.md) - System log viewer

### System

- [Settings](system-configuration.md) - Site name, subscription system, invite system toggles
