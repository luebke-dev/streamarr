# Banner Management

Banners are system-wide notifications displayed at the top of every page. Use them for maintenance announcements, feature updates, or important messages.

## Overview

Navigate to **Admin** -> **Banners** to manage banners.

The banner list shows:

- **Title** and **message**
- **Type**: Info, Warning, Error, Success
- **Status**: Active/Inactive
- **Schedule**: Start and end dates (if configured)
- **Actions**: Edit, Delete

## Creating a Banner

1. Navigate to **Admin** -> **Banners** -> **Create Banner**
2. Fill in the form:

| Field | Description |
|-------|-------------|
| **Title** | Short headline for the banner |
| **Message** | The full message text |
| **Type** | Visual style: Info (blue), Warning (amber), Error (red), Success (green) |
| **Active** | Whether the banner is currently shown |
| **Dismissible** | Whether users can close the banner |
| **Start Date** | Optional: When the banner should start showing |
| **End Date** | Optional: When the banner should stop showing |

3. Click **Save**

## Banner Types

| Type | Color | Use Case |
|------|-------|----------|
| **Info** | Blue | General announcements, new features |
| **Warning** | Amber | Upcoming maintenance, known issues |
| **Error** | Red | Service disruptions, critical issues |
| **Success** | Green | Resolved issues, positive updates |

## Dismissible Banners

When **Dismissible** is enabled:

- Users see a close button on the banner
- Dismissing sends a request to the server
- The banner won't appear again for that user
- Other users still see it until they dismiss it too

When **Dismissible** is disabled:

- The banner has no close button
- It stays visible for all users until the admin deactivates or deletes it

## Scheduling

Use **Start Date** and **End Date** to schedule banners:

- A banner with a future start date won't show until that date
- A banner with a past end date won't show anymore
- Both fields are optional - leave empty for a permanent banner

## Editing and Deleting

- Click the **Edit** button to modify a banner's content, type, or schedule
- Click the **Delete** button and confirm to permanently remove a banner
