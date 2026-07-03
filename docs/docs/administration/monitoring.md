# Monitoring

Pyrate.Media provides several monitoring tools for administrators to track system activity, debug issues, and manage resources.

## Active Sessions

Navigate to **Admin** -> **Active Sessions** to see all running transcoding sessions.

Each session shows:

- **User**: Who is streaming
- **Media**: Title of the content being watched
- **Video Codec**: Output codec (h264, h265, vp9)
- **Audio Codec**: Output audio codec (aac, opus)
- **Resolution**: Output resolution (1080p, 720p, etc.)
- **Duration**: How long the session has been running
- **Actions**: Stop session (kills the transcoding container)

!!! tip "Resource Management"
    Each active stream runs an FFmpeg Docker container. Monitor your server's CPU, RAM, and disk usage if you have many concurrent streams. Hardware acceleration (see [Transcoding](transcoding.md)) significantly reduces CPU load.

## Downloads

Navigate to **Admin** -> **Downloads** to monitor all download activity.

The downloads page shows a comprehensive table of all downloads (active, completed, and failed):

| Column | Description |
|--------|-------------|
| **Title** | Media name |
| **Status** | queued / downloading / importing / completed / failed |
| **Progress** | Visual progress bar with percentage |
| **Size** | Total file size |
| **Speed** | Current download speed |
| **Started by** | User who triggered the download |
| **Downloader** | Which client is handling it |
| **Time** | When the download started |

## Background Tasks

Navigate to **Admin** -> **Tasks** to see the TaskIQ worker queue.

The tasks page shows:

- **Running tasks**: Currently executing background jobs
- **Queued tasks**: Waiting to be processed
- **Completed tasks**: Recently finished jobs
- **Failed tasks**: Jobs that encountered errors

Common background tasks include:

- Metadata fetching from TMDB/IGDB
- Release searching on indexers
- Download monitoring and import
- Library scanning
- Trending list updates

## System Logs

Navigate to **Admin** -> **Logs** to view system logs.

The log viewer provides:

- **Log entries** with timestamps
- **Log levels**: DEBUG, INFO, WARNING, ERROR
- **Filtering** by log level
- **Search** through log messages
- **Auto-refresh** for live monitoring

## Watch Parties

Navigate to **Admin** -> **Watch Parties** to see all active watch parties across the system:

- **Party name** and **code**
- **Host**: Who created the party
- **Media**: What is being watched
- **Members**: Number of participants
- **Status**: Active/Ended
- **Actions**: End party (admin override)

## Lists (Admin View)

Navigate to **Admin** -> **Lists** to see all lists across all users:

- **System lists**: Trending lists created by the system
- **User lists**: Personal lists created by users
- **Visibility**: Public or Private
- **Item count**: Number of media items
- **Owner**: Who created the list
- **Actions**: View, Edit, Delete (for moderation)
