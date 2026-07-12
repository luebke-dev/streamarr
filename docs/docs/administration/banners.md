# Banner Management

Banners are system-wide announcements shown to every signed-in user. They appear as a full-width bar at the top of the page content — on the regular app pages and in the admin area alike. Use them for maintenance announcements, feature news, or anything the whole server should know about.

Banners are managed under **Admin** → **Banners** (the page is titled **System Banners**). Only administrators can create, edit, or delete banners.

## The banner list

The list shows all banners — active, inactive, and scheduled — with the following columns:

| Column | Description |
|--------|-------------|
| **Title** | The banner headline |
| **Type** | Information, Warning, Error, or Success |
| **Active** | Inline toggle — flip it to show or hide the banner without opening the editor |
| **Created At** | When the banner was created |
| **Actions** | Edit and Delete buttons |

!!! warning "Deleting is permanent"
    Deleting a banner asks for confirmation and cannot be undone. If you just want to retire a banner temporarily, switch off its **Active** toggle instead.

## Creating a banner

1. Go to **Admin** → **Banners** and click **Create Banner**.
2. Fill in the form:

| Field | Description |
|-------|-------------|
| **Title** | Required headline, up to 200 characters |
| **Message** | Required body text, up to 2000 characters. URLs in the message are automatically turned into clickable links that open in a new tab |
| **Type** | Visual style — see the table below |
| **Active** | Whether the banner is currently shown |
| **Start Date** | Optional — the banner is shown from this time (empty = immediately) |
| **End Date** | Optional — the banner is shown until this time (empty = unlimited) |

3. Check the live **Preview** at the bottom of the form — it renders the banner exactly as users will see it.
4. Click **Save**.

## Banner types

| Type | Color | Use case |
|------|-------|----------|
| **Information** | Blue | General announcements, new features |
| **Warning** | Amber | Upcoming maintenance, known issues |
| **Error** | Red | Service disruptions, critical issues |
| **Success** | Green | Resolved issues, positive updates |

Each type also gets a matching icon in front of the title.

## Visibility and scheduling

A banner is visible to users when **all** of the following hold:

- Its **Active** toggle is on,
- The current time is after the **Start Date** (or none is set),
- The current time is before the **End Date** (or none is set).

Leave both dates empty for a banner that stays up until you deactivate or delete it. Combining a start and end date lets you prepare announcements ahead of time — for example, schedule a maintenance warning for the weekend and it will appear and disappear on its own. See [Maintenance & Backups](maintenance.md) for planning maintenance windows.

## Dismissal

Every banner has a close button. When a user dismisses a banner:

- The dismissal is stored on the server per user, so the banner stays gone for that user on all of their devices and sessions.
- Other users continue to see the banner until they dismiss it themselves.

!!! tip "Re-announcing something"
    Editing an existing banner does **not** reset dismissals — users who already closed it will not see the updated text. If the change matters, create a new banner instead.

## Targeting and placement

Banners are deliberately simple:

- **Audience**: all signed-in users. There is no per-user, per-group, or per-library targeting.
- **Placement**: always the full-width bar at the top of the page, on every page. There are no placement options.

## Banners vs. page layouts

Banners are not part of the page layout system. [Page Layouts](page-layouts.md) control *content* — which sections (hero carousel, continue watching, genres, and so on) appear on the home and browse pages and in what order. Banners sit *above* whatever layout is active and are meant for transient announcements, not curation. If you want to promote media items visually, use a hero section in a page layout; if you want to tell users something, use a banner.
