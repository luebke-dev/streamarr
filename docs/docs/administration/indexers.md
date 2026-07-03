# Indexer Management

Indexers are search services that Pyrate.Media uses to find releases (downloads) for movies and shows. Without configured indexers, the Smart Play system cannot search for releases.

## Supported Indexer Types

| Type | Description | Examples |
|------|-------------|----------|
| **Newznab** | Standard protocol for Usenet indexers | NZBgeek, DrunkenSlug, NZBFinder |
| **Torznab** | Torrent indexers with Newznab-compatible API | Jackett, Prowlarr |

## Adding an Indexer

1. Navigate to **Admin** -> **Indexers**
2. Click **Create Indexer**
3. Fill in the form:

| Field | Description |
|-------|-------------|
| **Name** | A descriptive name (e.g. "NZBgeek", "Jackett") |
| **URL** | The indexer's API URL (e.g. `https://api.nzbgeek.info`) |
| **API Key** | Your personal API key from the indexer |
| **Enabled** | Whether the indexer should be used |
| **Categories** | Which categories to search (e.g. 2000 for movies, 5000 for TV) |

4. Click **Test Connection** to verify settings
5. Click **Save**

## Indexer Overview

The indexers page shows all configured indexers as a table:

- **Name** and **URL**
- **Type** (Newznab/Torznab)
- **Status** (Active/Inactive)
- **Actions**: Edit, Test, Delete

## Testing an Indexer

The **Connection Test** verifies:

- Is the URL reachable?
- Is the API key valid?
- Are the configured categories available?

A green notification indicates success; errors show detailed messages.

## Newznab Categories

Common Newznab categories:

| Category | Code |
|----------|------|
| Movies | 2000 |
| Movies/HD | 2040 |
| Movies/UHD | 2045 |
| TV | 5000 |
| TV/HD | 5040 |
| TV/UHD | 5045 |

## How Indexers Work

1. A user clicks "Play" on media without a local file
2. Pyrate.Media sends a **search query** to all active indexers
3. Indexers return a list of **releases**
4. Each release is scored using the library's **download rules**
5. The best release is sent to the **download client**
6. After download, the file is imported into the library
