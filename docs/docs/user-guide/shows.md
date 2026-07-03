# Shows in Detail

This page describes the show-specific features. For basic usage (detail page, actions, etc.), see [Movies & Shows](movies.md).

## Show Navigation

### From Show to Episode

1. **Open library**: Select the shows library in the menu
2. **Select show**: Click on a show poster
3. **Select season**: Click on a season card
4. **Select episode**: Click on an episode or the play button

### Season 0 (Specials)

Many shows have a "Season 0" for special episodes. The admin can hide this in the library settings.

## Playing Episodes

### Resume Function

When you press **Play** on the show detail page, the system automatically tries to:

1. First find the episode where you left off (resume point)
2. If no resume point exists: The first episode of the first season

### Episode Navigation in the Player

During playback of an episode, the player shows additional controls:

- **Previous Episode**: Jumps to the previous episode
- **Next Episode**: Jumps to the next episode
- **Title Display**: Shows the show name and episode (e.g., "S01E03 - Episode Title")

### Automatic Next Episode

After an episode ends, you can switch directly to the next episode.

## Metadata

Show metadata comes from TMDB and includes:

- **Show**: Title, description, poster, backdrop, genres, status (ongoing/ended), start year
- **Seasons**: Season poster, episode count
- **Episodes**: Title, description, still image, original air date, runtime, episode number

### External Links

Shows can be linked to:

- **TMDB** (The Movie Database)
- **TVDB** (The TV Database)
- **IMDB** (Internet Movie Database)

## Release Search for Episodes

The release search for episodes automatically takes into account:

- Show title
- Season number (S01, S02, ...)
- Episode number (E01, E02, ...)
- Quality settings from the download rules

The search is automatically triggered every 24 hours or when you want to play an episode for which no file is available.

## Next Steps

- [Games](games.md) — The games library
- [Streaming](streaming.md) — Player details
- [Watch Parties](watch-parties.md) — Watch episodes together
