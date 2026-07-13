# Search

streamarr.media has one search for everything: your movies, shows, music, games, books, and lists — and, for text searches, media that is not in your library yet.

## Opening the Search

You can open the search in three ways:

1. **Magnifying glass icon** in the toolbar at the top
2. **Keyboard shortcut** `/` (forward slash), as long as you are not typing in a text field
3. **Direct URL** `/search?q=searchterm`

Type at least 2 characters. After a short typing pause the results page opens automatically and keeps updating as you type. Press `Escape` to close the search.

### Typed Autocomplete

While you type, a suggestion list appears below the search field. Each suggestion is labeled with what it is — **Media**, **Genre**, **Person**, **Studio**, or **Year** — so you can jump straight to the right place:

- A **Media** suggestion opens the item's detail page directly.
- **Person**, **Studio**, and **Year** suggestions open the results page pre-filtered accordingly.

## Search Results

The results page groups matches into sections by type: Movies, Shows, Music, Artists, Games, Books — plus a **Lists** section when lists match your query. The header shows the total result count, the number of active filters, and where the results came from (provider or local index).

### The Filter Bar

A filter bar sits above the results. Active filters appear as removable chips, with a **Clear all** button next to them.

=== "Standard filters"

    | Filter | Description |
    |--------|-------------|
    | Type | Movies, shows, games, music, books |
    | Genres | One or more genres |
    | Platforms | Game platforms |
    | Availability | Local file, releases found, or nothing found |
    | Sort by / Order | Relevance, title, release date, added, updated — ascending or descending |
    | Year from / to | A release-year range |

=== "Advanced filters"

    Expand **Advanced filters** for: studio, person, container, age rating, specific years, and whether items have a poster, backdrop, or description, are favorites, or have been played.

=== "Exclude filters"

    Expand **Exclude filters** to hide items instead: exclude genres, platforms, a person, containers, age ratings, or years.

!!! tip "Bookmark your searches"
    The query and every filter are stored in the page URL. Bookmark or share the URL to return to exactly the same filtered view later.

### Browsing Without a Query

If you set filters without typing a search term, the page switches to browse mode and lists matching items from your library. That is also how genre and platform browsing works:

- **Genre tiles** on the home and library pages open the results page filtered by that genre.
- **Platform tiles** (games) open the results page filtered by that platform.

### People

Click a cast member on any detail page to open their **person page**, with photo, biography, and full filmography split into movies and TV shows. If the filmography is not complete yet, it is imported in the background — use the **Refresh** button to reload it.

## Finding Media You Don't Have Yet

Text searches ask the metadata providers first — TMDB for movies and shows, IGDB for games, Spotify for music, OpenLibrary for books — so results include titles that are not in your library yet. If the provider cannot be reached, the search automatically falls back to your local index.

Newly discovered items are queued for import automatically, and the results update live as soon as an item has been added to the library. Clicking a result that is already in the library opens its detail page right away.

!!! note "Importing on click"
    Opening a result that has not been imported yet fetches its metadata on the fly — this instant import requires administrator rights. Other users can open discovered items as soon as the automatic background import has picked them up.

!!! info "Search index"
    Local results are served by a fast full-text index with typo-tolerant matching and relevance ranking, kept in sync in the background.

## Next Steps

- [Movies & Shows](movies.md) — what you'll find on the detail pages
- [Music](music.md) and [Books](books.md) — the other library types in your results
- [Lists & Collections](lists.md) — organize what you found
- [Dashboard & Home](dashboard.md) — genre and platform sections on the home page
