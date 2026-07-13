# Page Layouts

Page layouts control which content sections appear on the home page and on the library browse pages (Movies, Shows, Games, Music, Books): which sections are shown, in what order, and with what configuration. Layouts are managed by administrators and apply to **all users** — there is no per-user layout.

Navigate to **Admin** -> **Page Layouts** to see all configured layouts with their name, slug, active state, and section count.

## Layout properties

| Field | Description |
|-------|-------------|
| **Name** | Descriptive name shown in the admin list (e.g. "Home", "Movies") |
| **Slug** | Unique URL identifier; `home` = default layout |
| **Library** | Optional — binds this layout to a specific library's browse page |
| **Active** | Only active layouts are ever used; inactive ones are skipped |

## How a page picks its layout

- The **home page** (`/`) always uses the layout with slug `home`.
- A **browse page** (e.g. `/movies`) uses the layout whose **Library** field points to the library of that media type. If no such layout exists (or it is inactive), the page falls back to the `home` layout.

!!! warning "Bind browse-page layouts via the Library field"
    Only the `home` slug is special. Giving a layout the slug `movies` does **not** attach it to the Movies page by itself — set the **Library** field so the layout is picked up.

!!! note
    Slugs are unique: creating a layout with a slug that is already taken is rejected with a conflict error. The `home` layout cannot be deleted from the list.

## Section types

Each section is one content block on the page. When adding a section you pick a **Section Type**, an optional **Title** (displayed as the section header), and type-specific settings:

| Section type | What it shows | Configuration |
|--------------|---------------|---------------|
| **Hero Carousel** | Large featured carousel with backdrops at the top of the page | Data source: **Trending** (default), a **specific list**, or a **dynamic search** with filters |
| **Continue Watching** | The user's in-progress items with resume | Content type filter (Movies, Shows, Games, Music, Books) |
| **Favorites** | The user's favorited items | — |
| **Specific Genre** | One poster row for a single genre | Genre (required), max items (1–50), optional filters |
| **All Genres** | One row per genre that has items | Max items per genre (1–50), optional filters |
| **Latest Items** | Most recently added media | Media type filter, max items |
| **Trailers** | Browsable trailer row | Media type filter, trailer search term, max items |
| **Platforms** | Game platforms for browsing | — |
| **List** | Items from a curated or system list | List selection, max items; alternatively a per-user list source or a prefix that renders multiple rows (e.g. recommendation rows) |
| **Dynamic Search** | Results of a saved search query | Filters + max items |

**Dynamic search filters** cover media type, genre, platform, availability (local files / has releases / neither), has-poster/has-description, release-year range, sort field (title, release date, date added, date updated), sort order, and a free-text query.

## Managing sections

1. Create the layout and click **Save** first — sections can only be added to a saved layout.
2. **Add Section**, choose the type, set the optional title and configuration, and save.
3. Reorder with the **up/down arrows**; the order is the display order on the page.
4. Use the **toggle** to disable a section without deleting it (disabled sections are hidden from users), the **pencil** to edit, and the **trash icon** to delete.

## Inline edit mode

Administrators do not have to use the admin area at all: on the home page and every browse page, admins see a **pencil button** in the top toolbar (**Edit Layout** / **Exit Edit Mode**). In edit mode you can add a section at any position, edit, reorder, enable/disable, and delete sections directly on the live page. If a page has no layout of its own yet, streamarr.media offers to create one on the spot.

!!! note "Admin-only"
    The pencil only appears for administrators, and inline edits change the shared layout for everyone — it is not per-user personalization. Regular users never see edit controls; they only browse the result (see [Dashboard & Home](../user-guide/dashboard.md)).

## What users actually see

- Sections that produce **no content for a user** (e.g. Continue Watching with nothing in progress, an empty Favorites row) are automatically hidden for that user.
- Section content respects each user's **library permissions and parental controls** — two users can see different items in the same section.
- Rendered layouts are cached; your changes take effect immediately for you, but other users may see the previous layout for a few minutes.

## Example

=== "Home"

    1. **Hero Carousel** — trending items
    2. **Continue Watching** — all media types
    3. **Favorites**
    4. **Latest Items** — recently added
    5. **All Genres** — 10 items per genre

=== "Movies browse page"

    A layout with **Library** set to the movie library:

    1. **Hero Carousel** — dynamic search: recent releases
    2. **Continue Watching** — content type: Movies
    3. **Specific Genre** — Action
    4. **List** — a curated list (see [Lists & Collections](../user-guide/lists.md), or feed it automatically with [Smart Collections](smart-collections.md))
    5. **Trailers** — media type: Movies

See also [Banners](banners.md) for site-wide announcement bars, which are configured separately from page layouts.
