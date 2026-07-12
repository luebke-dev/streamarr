# Viewing History

Your viewing history shows everything you have watched, listened to, played, or read — with progress indicators and one-click resume, so you can continue exactly where you left off.

## Opening the History

- **Side menu** → **History**
- Or navigate directly to `/history`

## What Gets Tracked

History is not limited to video. pyrate.media records progress for:

| Media | Example |
|-------|---------|
| **Movies** | Playback position and completion |
| **Episodes** | Shown as "Show - S02E05: Episode Title" |
| **Songs** | Listening progress from the audio player |
| **Games** | Cloud gaming sessions you launched |
| **Books** | Your reading position in the EPUB reader |

Each entry carries a small colored icon badge indicating its media type.

!!! note "Progress is saved automatically"
    While you watch, your position is reported to the server every few seconds and again when you close the player — there is nothing to save manually. An item counts as **Completed** once you have watched roughly 90% of it. If you start something you had nearly finished, playback restarts from the beginning instead of resuming in the credits.

## The History Table

| Column | Description |
|--------|-------------|
| **Title** | Title with thumbnail; episodes include the show name and episode code |
| **Progress** | A green **Completed** badge, or a progress bar with percentage and watched/total time |
| **Last Watched** | Relative time (e.g. "3 hours ago", "Yesterday", "5 days ago") |
| Actions | **Continue** / **Watch Again** and **Remove** |

Twenty entries are shown at a time — use **Load more** at the bottom for older ones.

## Continue or Watch Again

The play button next to each entry adapts to your progress:

- **Continue** — the item is unfinished; playback resumes at your last position
- **Watch Again** — the item is completed; playback starts from the beginning

## Removing an Entry

1. Click the **trash icon** next to an entry
2. Confirm in the **"Remove entry?"** dialog

The entry disappears from your history and from Continue Watching.

## Continue Watching on the Home Page

If your server's page layout includes a **Continue Watching** section, your unfinished items appear as a horizontal card row with progress bars:

- Clicking the **play icon** on a card resumes playback immediately
- Clicking anywhere else on the card opens the media detail page
- For TV shows, only your most recently watched episode per show is listed

Depending on the configured layout, you may also see media-specific variants: **Continue Listening** (music), **Continue Playing** (games), and **Continue Reading** (books). See [Dashboard & Home](dashboard.md) for how home page sections work.

## Marking Items Watched or Unwatched

On the detail page of a movie, episode, song, game, or book you will find a **Mark Watched** button next to the play controls:

- **Mark Watched** sets the item to 100% — it shows as Completed in your history and leaves Continue Watching
- **Mark Unwatched** resets your progress to zero

!!! tip
    Use **Mark Unwatched** if you want a completed movie or episode to behave like something you have never seen — the next play starts fresh from the beginning.

!!! note "History is personal"
    Viewing history and played states are tracked per user account. Removing entries or marking items unwatched only affects you.

## Next Steps

- [Streaming & Playback](streaming.md) — how playback and resume work
- [Music](music.md) — the audio player and Continue Listening
- [Books](books.md) — the EPUB reader and Continue Reading
- [Favorites](favorites.md) — your favorite media
- [Watch Parties](watch-parties.md) — in a party, playback follows the party's position, not your personal history
