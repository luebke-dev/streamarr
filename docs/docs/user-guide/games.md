# Games

Pyrate.Media offers a games library with IGDB integration and a unique feature: **game streaming via Lightrays**.

## Games Library

The games library works similarly to the movies and shows library:

- **Cover view**: Games are displayed with cover art from IGDB
- **Detail page**: Shows description, release date, genres, platforms, and additional metadata
- **List integration**: Games can be organized into lists
- **Favorites**: Games can be marked as favorites

### Metadata

Game metadata comes from the **Internet Game Database (IGDB)** and includes:

- Title and description
- Cover art and screenshots
- Release date
- Genres and platforms
- Developers and publishers
- Ratings and game modes

## Game Streaming with Lightrays

The special feature of the games library is the ability to stream games directly in the browser. This is realized through **Lightrays** — a Rust-based WebRTC streaming server.

### How does it work?

1. You click **Play** on a game
2. Lightrays starts a Docker container with the game
3. A virtual Wayland desktop is created
4. The game is encoded in real time as a WebRTC stream via GStreamer
5. You see and control the game directly in the browser

### Controls

In game streaming mode, you can:

- **Mouse**: Forwarded directly to the game
- **Keyboard**: Inputs are transmitted as Linux scancodes
- **Fullscreen**: For the best gaming experience

### Technical Details

- **Video codec**: H.264 for normal resolutions, H.265 for ultra-wide
- **Hardware acceleration**: VA-API GPU encoding for low latency
- **Latency**: Optimized for real-time interaction

!!! info "Prerequisite"
    Game streaming requires a running Lightrays instance with GPU access and Docker socket. The admin must set this up separately.

## Differences from Movies/Shows

- **No automatic download**: Games do not have an automatic download system like movies/shows
- **No indexer search**: There is no release search for games
- **Cataloging**: The library primarily serves for organization and overview
- **Game streaming**: Instead of local file playback, streaming is done via Lightrays

## Next Steps

- [Movies & Shows](movies.md) — Movie and show management
- [Lists](lists.md) — Organize games into lists
- [Streaming](streaming.md) — How video streaming works
