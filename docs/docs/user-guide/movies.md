# Movies & Shows

Pyrate.Media manages movies and shows as **media libraries**. Each library is created by the admin and can have its own page layout, download rules, and storage paths.

## Browsing Libraries

Select a library from the sidebar menu (e.g., "Movies" or "Shows"). You will land on the library page, which — like the home page — consists of configurable sections:

- **Hero Carousel** with selected highlights
- **Genre Overviews** (Action, Drama, Comedy, etc.)
- **Trending Lists** with currently popular content
- **Continue Watching** for content you've started

### Poster Cards

Media are displayed as poster cards with:

- **Poster image** from TMDB/IGDB
- **Title** of the movie/show
- On hover: Quick actions to play or open

## Media Detail Page

Click on a media item to open the detail page. It shows:

### Hero Section

- **Backdrop image**: Large background image from TMDB
- **Poster**: Movie poster on the left
- **Title & Original Title**: Name in your language and original
- **Tagline**: Movie tagline (if available)
- **Meta chips**: Year, status, runtime, genres

### Actions

- **Play**: Starts Smart Play (see [Streaming](streaming.md))
- **Add to List**: Opens a dialog to select your lists
- **Favorite**: Marks the media as a favorite (heart icon)
- **Refresh Metadata**: Admin only — fetches fresh data from TMDB/IGDB
- **Notify**: For unavailable media, you can be notified when it becomes available

### Description

Below the hero section, you will find the plot summary and additional details.

## Show Hierarchy

Shows have a three-level structure:

```
Show
 +-- Season 1
 |    +-- Episode 1
 |    +-- Episode 2
 |    +-- ...
 +-- Season 2
 |    +-- Episode 1
 |    +-- ...
 +-- ...
```

### Viewing a Show

On the show detail page, you will see:

- All **seasons** as poster cards with episode counts
- Click on a season to see its episodes

### Viewing a Season

The season page shows all **episodes** as cards with:

- **Thumbnail/still image** of the episode
- **Episode number** as overlay
- **Title** and **original air date**
- **Runtime** (if available)
- **Description** of the episode
- **Play button** on hover (if file is available)

### Playing an Episode

Click on an episode or the play button to play it. The Smart Play system automatically decides:

1. **File available** -> Streaming starts immediately
2. **Releases available** -> Download is started
3. **No releases** -> Search is initiated at indexers

For shows, the system first tries to use the **resume function**: If you have already watched an episode, it will automatically continue where you left off.

## People

On detail pages of movies and shows, you will find links to **people** (actors, directors, etc.). Click on a person to open their page:

- **Profile picture** from TMDB
- **Name** and **Known for** (e.g., "Acting", "Directing")
- **Filmography**: All media in your library that the person was involved in

## Files & Releases

### Available Files

When a media item has been downloaded, the detail page shows the file information:

- File name and size
- Video and audio codec information
- Available audio tracks and subtitles

### Releases

Admins additionally see a release table with:

- **Release name**: Full name with quality info
- **Size**: File size
- **Score**: Rating based on the configured download rules
- **Release date**
- **Download button**: Manual download start

## Next Steps

- [Streaming](streaming.md) — How Smart Play and the player work
- [Lists](lists.md) — Organize media into lists
- [Watch Parties](watch-parties.md) — Watch together
