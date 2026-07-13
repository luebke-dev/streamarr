# Dashboard & Home Page

The home page is the central entry point into streamarr.media. It is assembled from configurable **sections** — rows and carousels that your administrator arranges into a page layout. The same section system also powers the library browse pages (Movies, Shows, Games, Music, Books).

## Home Page Sections

Depending on how your instance is configured, the home page can contain any combination of these sections, in any order:

| Section | What it shows |
|---------|---------------|
| **Hero Carousel** | Full-width rotating showcase with backdrop art, title, and a play button. Fed by trending titles, a specific list, or a dynamic search. Rotates automatically and pauses while you hover over it. |
| **Continue Watching** | Movies and episodes you started but haven't finished — with progress bars, so one click resumes playback. |
| **Specific Genre** | A row of media from a single genre (e.g. Action, Comedy). |
| **All Genres** | One row per genre, generated automatically from your libraries. |
| **List** | The contents of a curated list — for example a trending list or a [smart collection](../administration/smart-collections.md). |
| **Dynamic Search** | A row driven by a saved search query and filters (media type, genre, year range, availability, sort order, and more). |
| **Latest Items** | The most recently added items, newest first. |
| **Favorites** | Your [favorited media](favorites.md) as a poster row. |
| **Platforms** | Game platforms with their logos — click one to browse its games. |
| **Trailers** | Titles with trailers, ready to explore. |

Each section can carry a custom title, and most can be limited to a maximum number of items.

!!! note "Layouts are shared"
    Page layouts are managed by administrators and apply to everyone on the server. Sections like *Continue Watching* and *Favorites* still show **your** personal content — only the arrangement of sections is shared.

### Library Page Layouts

Every library page (Movies, Shows, Games, Music, Books) can have its own layout with its own sections. If a library has no layout of its own, it falls back to the **Home** layout.

## Editing Layouts (Administrators)

Administrators can rearrange any page directly in place:

1. Click the **pencil icon** in the toolbar (visible to admins only) — the tooltip reads **Edit Layout**.
2. In edit mode, every section gains a toolbar:
    - **Move up / Move down** — reorder sections with the arrow buttons
    - **Toggle** — temporarily disable a section without deleting it (it is marked *Disabled* and hidden for users)
    - **Pencil** — open the configuration dialog (section type, optional title, data source, filters, max items)
    - **Delete** — remove the section after a confirmation
3. Use the **Add Section** buttons between sections (and at the end of the page) to insert new ones exactly where you want them.
4. Click the pencil icon again (**Exit Edit Mode**) when you are done.

If a page has no layout yet, admins see a *"No layout configured for this page. Create one?"* prompt with a **Create Layout** button. Layouts can also be managed centrally under **Admin → Page Layouts** — see [Page Layouts](../administration/page-layouts.md).

## Navigation

### Sidebar (Main Menu)

Open the menu via the hamburger icon in the top left:

- **Home** — back to the home page
- **History** — your [viewing history](history.md)
- **Libraries** — the libraries enabled on your server that you have access to (e.g. Movies, Shows, Games, Music, Books)
- **My Lists** — your personal [lists](lists.md), with filter tabs by list type and a **+** button to create a new list

### Toolbar

The toolbar at the top contains:

- **Menu button** — opens the sidebar
- **Site name** — the name of your instance
- **Watch party button** — create or join [watch parties](watch-parties.md)
- **Remote control** — control playback on your other signed-in [devices](devices.md)
- **User menu** — settings, membership, friends, admin area, log out
- **Search** — opens the global search

!!! tip "Quick search"
    Press `/` anywhere to jump straight into the search. Type at least two characters to get live suggestions, and press `Escape` to close it again. See [Search](search.md) for details.

### Global Banners

Admins can display system-wide banners at the top of every page — for example for maintenance announcements or news.

## Audio Player

When you play music, a persistent audio player appears at the bottom of the screen and keeps playing while you browse. See [Music](music.md).

## Next Steps

- [Movies & Shows](movies.md) — discover and play media
- [Search](search.md) — find anything in your libraries
- [Lists & Collections](lists.md) — curate your own rows
- [Streaming & Playback](streaming.md) — how playback works
