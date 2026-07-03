# Search

Pyrate.Media offers a powerful search that lets you find media in your library and import new content from external sources.

## Global Search

### Opening the Search

You can open the search in three ways:

1. **Magnifying glass icon** in the toolbar at the top right
2. **Keyboard shortcut** `/` (forward slash) on the keyboard
3. **Direct URL** `/search?q=searchterm`

### Using the Search

1. Type at least 2 characters
2. After a 200ms typing pause, results are automatically loaded
3. Results are displayed as a poster grid
4. Click a result to open the detail page
5. Press `Escape` to close the search

## Search Results

The results page shows matches from your local library, grouped by media type.

### Filters

You can filter the results by:

- **Media type**: Movies, Shows, Games, Music, Books
- **Genre**: From the list of available genres
- **Year**: Narrow down to specific release years
- **Library**: Search only within a specific library

### In-Library Badge

Results that are already in your library are marked with a badge. This way you can see at a glance what you already have.

## Importing Media

A special feature of the search: You can import media directly from external sources.

### Import from TMDB (Movies & Shows)

1. Search for a movie or show
2. If the title is not yet in your library, an **Import button** appears
3. Click the button — the media will be imported with all metadata from TMDB
4. It appears immediately in your library

### Import from IGDB (Games)

Same process as with TMDB, but using the Internet Game Database as the source.

### Import from Spotify (Music)

If music is enabled, you can import albums and artists from Spotify.

## Elasticsearch

Pyrate.Media optionally uses Elasticsearch for search. This means:

- **Fast full-text search** even with very large libraries
- **Fuzzy matching**: Finds results even with typos
- **Relevance sorting**: The best matches first

!!! info "Note"
    Elasticsearch is optional. Without Elasticsearch, the search works via the database — but with very large libraries, this may be slower.

## Next Steps

- [Movies & Shows](movies.md) — View media in detail
- [Lists](lists.md) — Organize found media into lists
- [Dashboard](dashboard.md) — Back to the home page
