# Dashboard & Home Page

The home page is the central entry point into Pyrate.Media. It shows personalized content, recommendations, and quick access to all features.

## The Home Page

When you log in, you land on the home page. It is fully configurable by the administrator and consists of various **sections** that are dynamically assembled.

### Typical Sections

Depending on the admin's configuration, the following sections may be displayed:

- **Hero Carousel**: Large, animated preview of selected media with backdrop images, titles, and quick actions (play, details)
- **Continue Watching**: Shows movies and episodes you started but haven't finished yet — with progress bars
- **Favorites**: Your favorited media as a poster carousel
- **Genre Sections**: Media grouped by genre (Action, Comedy, Drama, etc.)
- **List Sections**: Content from specific lists (e.g., trending lists)
- **Dynamic Search**: Sections based on search terms

### Page Layout

Each library (Movies, Shows, Games, etc.) can have its own page layout. The home page has a separate "Home" layout that works across all libraries.

## Navigation

### Main Menu (Sidebar)

Open the menu via the hamburger icon in the top left. The menu contains:

- **Home**: Back to the home page
- **Favorites**: All your favorited media
- **History**: Your playback history
- **Libraries**: Dynamically based on the libraries created by the admin (e.g., Movies, Shows, Games, Music, Books)
- **My Lists**: All your personal lists with the option to create new lists directly

### Header (Toolbar)

The toolbar at the top contains:

- **Menu Button**: Opens the sidebar
- **Site Name**: The name of your Pyrate.Media instance
- **Watch Party Button**: Shows active watch parties
- **Remote Control**: Allows controlling other devices
- **User Menu**: Profile, settings, admin area, log out
- **Search**: Opens the global search

### Global Search

Click the magnifying glass icon in the toolbar or press `/` on the keyboard to open the search. The search works with live results:

1. Type at least 2 characters
2. After a 200ms typing pause, results are automatically displayed
3. The search uses Elasticsearch for fast full-text search across all libraries
4. Results show poster, title, and media type
5. Press `Escape` to close the search

### Global Banners

Admins can display system-wide banners that appear at the top of every page — e.g., for maintenance announcements or news.

## Audio Player

A persistent audio player can appear at the bottom of the screen when you play music. The player remains visible while navigating between pages.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `/` | Open global search |
| `Escape` | Close search/modal |
| `Space` | Video play/pause (in player) |
| `F` | Fullscreen (in player) |

## Next Steps

- [Movies & Shows](movies.md) — Discover and play media
- [Lists](lists.md) — Create collections
- [Streaming](streaming.md) — How playback works
