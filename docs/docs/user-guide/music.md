# Music

streamarr.media includes a full music library alongside movies, shows, games, and books. Music is organized in a hierarchy of **artists → albums → songs**, with metadata pulled from **Spotify** and **MusicBrainz** (including cover art), and plays in a persistent audio player that keeps running while you browse the rest of the app.

## Browsing the Music Library

Open **Music** from the Libraries section of the sidebar. Like every library page, it is built from configurable sections — typically **Trending Now** (kept up to date automatically from Spotify's charts), genre rows, latest additions, and your favorites. Click any card to open its detail page.

=== "Artist"

    The artist page shows the artist's photo, overview, and a **Discography** section with a card for each album. Click an album to drill down.

=== "Album"

    The album page shows the cover art, a track count chip, and a **Tracks** list with track numbers and durations — multi-disc albums are grouped by disc. Pressing **Play** on the album queues all tracks; clicking a single track starts there, with the rest of the album queued behind it.

=== "Song"

    A song has its own detail page too, with the album art and the usual actions. Pressing play starts it in the audio player.

All the familiar actions work on music as well: **Add to List** (see [Lists & Collections](lists.md)), the heart button for [favorites](favorites.md), and **Instant Mix**, which fills the queue with a mix of similar tracks and starts playing.

## Adding Music

The [search](search.md) is not limited to what your server already has — it also returns artists, albums, and songs from Spotify. Opening such a result imports it into the library automatically: importing an album brings its track list along, and importing an artist queues their albums for import in the background.

!!! note
    Importing adds **metadata only** — no audio files yet. The files arrive when you press play (see below) or when an admin downloads them.

## The Audio Player

Playing any track opens a player bar pinned to the bottom of the screen. It stays there while you navigate — browse other libraries, open detail pages, even manage settings, and the music keeps playing. The bar shows the album art, title, and clickable artist and album links that jump to the matching detail pages.

| Control | What it does |
|---------|--------------|
| **Play/Pause, Previous, Next** | Standard transport controls |
| **Shuffle** | Picks the next track randomly from the queue |
| **Repeat** | Cycles through off → repeat all → repeat one |
| **Progress bar** | Click or drag the thin bar on top to seek |
| **Volume** | Slider and mute toggle |
| **Queue** | Opens the current queue — jump to any track or remove tracks |
| **Lyrics** | Opens the lyrics panel for the current track |
| **Close** | Hides the player and stops playback |

Shuffle and repeat settings are remembered across sessions.

!!! tip "Play it elsewhere"
    If you have another device signed in, you can send music playback there instead of playing locally — see [Devices, Casting & Offline](devices.md).

### Lyrics

The lyrics button in the player opens a panel with the words to the current track, fetched automatically from an online lyrics provider. A badge tells you whether they are **Synced lyrics** or **Plain lyrics**, and a refresh button re-fetches them.

### Playing songs you don't have yet

Music gets the same Smart Play treatment as [movies and shows](movies.md): pressing play on a track whose file isn't on the server yet triggers a download through the built-in Spotify downloader. The player shows the download status and starts playback automatically once the file is ready.

!!! warning "Admin setup required"
    On-demand music downloads only work if your admin has configured the Spotify downloader, which requires a **Spotify Premium** account (see [Download Clients](../administration/downloaders.md)). Without it, only music that already has files on the server is playable.

## What's That Song?

When you're watching a movie or show and want to know what's playing in the background, open the video player's **Identify Song** action (on small screens it's in the **⋮** menu). The server analyzes the audio at your current playback position with Shazam and shows you the matched title, artist, and album — no microphone needed.

## Next Steps

- [Search](search.md) — find and import new music
- [Streaming & Playback](streaming.md) — the video player and Smart Play in detail
- [Favorites](favorites.md) — heart what you love
- [Lists & Collections](lists.md) — build your own playlists
