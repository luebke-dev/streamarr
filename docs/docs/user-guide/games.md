# Games

streamarr.media includes a full games library with IGDB metadata — and you don't install anything to play: games run on the server and stream directly to your browser via **Lightrays**, streamarr.media's cloud-gaming service.

## The Games Library

Open **Games** in the navigation. Like the home page, the games page is built from configurable sections — for example a hero carousel, **Trending Now**, genre rows with a **See All** option, favorites, and platform sections. Trending games come from IGDB and are refreshed automatically.

Games also show up in the global [search](search.md) with their own results section, and can be added to [lists](lists.md) and marked as [favorites](favorites.md) just like movies and shows.

### Metadata

Game metadata comes from the **Internet Game Database (IGDB)** and includes:

- Title and description
- Cover art and screenshots
- Release date
- Genres and platforms (shown as chips with platform logos on the detail page)
- Developers and publishers
- Ratings and game modes

## Playing a Game

1. Open a game's detail page and press **Play**.
2. If the game exists for more than one platform (for example an N64 ROM and a PC port), a **"Choose a version to play"** picker appears. Each version is labeled either **Play** (already on the server) or **Download & play**.
3. The server launches a game session — you'll briefly see *"Launching game session…"* — and the stream appears in your browser.

!!! note "Download & play"
    If the version you picked isn't stored on the server yet, streamarr.media starts downloading it and shows the same waiting screen used for movies and episodes: *"The game is downloading — this can take a moment."* The game launches automatically once the download finishes.

!!! tip "Steam games"
    Games that run on the Steam runtime open in Steam's Big Picture interface inside the stream. You only need to sign in to Steam once — your login and game data are kept per user and shared across all your Steam game sessions.

Your saves and in-game settings are stored on the server, so you can disconnect and pick up where you left off in a later session.

## Controls During a Session

Your mouse and keyboard input is forwarded to the game. Clicking the video captures your mouse; a toolbar above the stream offers:

| Button | What it does |
|--------|--------------|
| **Fullscreen** | Switches the stream to fullscreen |
| **Match resolution** | Adjusts the remote resolution to your current window size |
| **Lock Mouse** | Captures the mouse pointer for the game (press ``Esc`` to release) |
| **Disconnect** | Ends the streaming session |

The toolbar also shows live stream statistics (bitrate, frame rate, and latency).

!!! tip
    For first-person or mouse-driven games, use **Lock Mouse** together with **Fullscreen** — the game then receives raw mouse movement, just like playing locally.

## Gaming Settings

Under [User Settings](settings.md) you'll find two sections that only affect game streaming:

- **Cloud Gaming** — choose your **Keyboard Layout** and **Mouse Speed** for streaming sessions.
- **Controller** — gamepad behaviour for retro game sessions: **Analog stick deadzone** and **D-Pad mode** (D-Pad, left analog stick, or right analog stick).

Changes apply to your next session.

## Availability & Limits

!!! warning "Server-side feature"
    Cloud gaming has to be set up by your administrator (it needs a GPU-equipped streaming service). Administrators can also limit how many game streams your account may run at once, or disable game streaming for an account entirely — and on servers with paid plans it may be part of a specific [membership](membership.md) tier. If **Play** fails with a permission error, contact your admin.

## Next Steps

- [Streaming & Playback](streaming.md) — how video streaming works
- [Lists & Collections](lists.md) — organize games into lists
- [User Settings](settings.md) — all per-user preferences
