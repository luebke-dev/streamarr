# Plugin Management

Pyrate.Media uses a plugin system for metadata providers, download clients, and more. Plugins can be installed, configured, and enabled/disabled.

## Plugin Overview

Navigate to **Admin** -> **Plugins** to see all installed plugins.

Each plugin shows:

- **Name** and **description**
- **Plugin type** as colored badge:
    - **Metadata** (blue): Provides metadata (titles, images, descriptions)
    - **Downloader** (green): Download client integration
    - **Indexer** (orange): Search indexers for releases
    - **Library** (purple): Library plugin (e.g. movies, shows, games)
    - **Computing** (teal): Compute resources (Docker, Kubernetes)
- **Version** (e.g. v1.0.0)
- **Status**: Active, Disabled, or Built-in
- **Enable/Disable toggle** (not for built-in plugins)
- **Configure button** (not for library plugins)

### Built-in Plugins

Built-in plugins are integrated into Pyrate.Media and cannot be disabled. These typically include the library plugins (movies, shows, games, music, books).

## Installing a Plugin

1. Click **Install Plugin**
2. A dialog shows available plugins from configured repositories
3. Browse or filter the list
4. Each plugin shows name, description, type, version, author, and license
5. Click **Install**
6. The plugin appears in the configured plugins list

## Plugin Repositories

Repositories are sources from which plugins can be installed.

1. Click **Add Repository**
2. Enter a **name** and **URL** (HTTP/HTTPS)
3. The repository is validated and added
4. You can also **delete** or **refresh** repositories

## Configuring Plugins

Click the **gear icon** or the plugin name to open the configuration page.

### TMDB Plugin

Required configuration:

- **API Key**: Your TMDB API key ([create one here](https://www.themoviedb.org/settings/api))

TMDB provides metadata for movies and shows (titles, descriptions, posters, backdrops, cast, genres, etc.).

### IGDB Plugin

Required configuration:

- **Client ID**: From [Twitch Developers](https://dev.twitch.tv/)
- **Client Secret**: From Twitch Developers

IGDB provides metadata for games (titles, covers, descriptions, platforms, genres, etc.).

### Spotify Plugin

Required configuration:

- **Client ID**: From [Spotify Developer](https://developer.spotify.com/)
- **Client Secret**: From Spotify Developer

Spotify provides metadata for music (artists, albums, tracks, artwork, etc.).

## Enabling/Disabling Plugins

Use the **toggle switch** next to a plugin to enable or disable it.

!!! info "Note"
    Disabled plugins are not used in any operations. For example, disabling the TMDB plugin means no metadata can be loaded for movies and shows.
