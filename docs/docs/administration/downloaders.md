# Download Clients

Download clients are external applications that Pyrate.Media uses to download media files. Currently supported clients are **SABnzbd** (Usenet) and **Deluge** (Torrents).

## Overview

Navigate to **Admin** -> **Downloaders** to see all configured download clients.

Each downloader shows:

- **Name** and connection details
- **Type** (SABnzbd or Deluge)
- **Status** (connected/disconnected)
- **Actions**: Edit, Test, Delete

## Adding a Download Client

1. Navigate to **Admin** -> **Downloaders**
2. Click **Add Downloader**
3. Select the client type

### SABnzbd Configuration

| Field | Description |
|-------|-------------|
| **Name** | A descriptive name (e.g. "My SABnzbd") |
| **Host** | IP address or hostname (e.g. `localhost` or `192.168.1.100`) |
| **Port** | SABnzbd web interface port (default: `8080`) |
| **API Key** | Found in SABnzbd under Config -> General -> API Key |
| **Use SSL** | Enable for HTTPS connections |

### Deluge Configuration

| Field | Description |
|-------|-------------|
| **Name** | A descriptive name (e.g. "My Deluge") |
| **Host** | IP address or hostname |
| **Port** | Deluge web interface port (default: `8112`) |
| **Password** | Deluge web interface password |

4. Click **Test Connection** to verify the settings
5. Click **Save**

## Testing Connection

The connection test verifies:

- The host is reachable
- The port is correct
- Authentication credentials are valid
- The client is responding

A green notification indicates success; error messages will describe what went wrong.

## Managing Downloads

Navigate to **Admin** -> **Downloads** to see all active and completed downloads.

The downloads page shows a table with:

| Column | Description |
|--------|-------------|
| **Title** | Name of the media being downloaded |
| **Status** | queued, downloading, importing, completed, failed |
| **Progress** | Progress bar for active downloads |
| **Size** | File size |
| **Speed** | Current download speed |
| **Started by** | Which user triggered the download |
| **Downloader** | Which client is handling the download |
| **Time** | When the download was started |

### Download Status Colors

| Status | Color | Meaning |
|--------|-------|---------|
| **queued** | Grey | Waiting to start |
| **downloading** | Blue | Currently downloading |
| **importing** | Amber | Download complete, importing to library |
| **completed** | Green | Successfully imported |
| **failed** | Red | Something went wrong |

### Actions

- **Delete**: Remove a download from the queue
- **Retry**: Retry a failed download

## How Downloads Work

1. Smart Play or manual release selection triggers a download
2. Pyrate.Media sends the release to the configured download client
3. The download client handles the actual download
4. Pyrate.Media monitors progress via the client's API
5. Once complete, the file is moved to the library path
6. FFprobe analyzes the file for metadata (codecs, resolution, duration)
7. The media item is updated with file information
