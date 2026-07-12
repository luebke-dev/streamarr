# Movies & Shows

pyrate.media manages movies and shows as **media libraries**. Each library is created by an admin and can have its own page layout, release scoring rules, and storage paths. This page covers browsing, the media detail page, and how new content gets into your library — including Smart Play, which downloads what you press play on.

## Browsing a Library

Open a library from the **Libraries** section of the sidebar (e.g. *Movies* or *Shows*). Like the home page, a library page is built from configurable sections:

- **Hero Carousel** with highlighted titles and a direct play button
- **Genre rows** (a single genre or all genres)
- **Latest Items**, **Continue Watching**, **Favorites**
- **Lists**, **Platforms**, and **Dynamic Search** sections
- **Trailers** — titles that have trailers in their metadata, with year and trailer count

Media appear as **poster cards** showing the artwork, title, an age-rating badge where set, and — in recommendation rows — which of your friends watched it. Click a card to open the detail page.

!!! note
    Admins choose which sections appear and in what order (see [Page Layouts](../administration/page-layouts.md)) and can edit the layout inline right on the page. Parental controls may hide titles above your age rating.

## The Media Detail Page

The detail page opens with a hero section: backdrop, poster, title and original title, tagline, and meta chips for year, status (e.g. released, *Returning Series*, *Ended*), runtime, age rating, and genres.

### Actions

| Button | What it does |
|--------|--------------|
| **Watch** | Starts Smart Play (see below) |
| **Notify when available** | Shown instead of *Watch* when the title has no playable source yet — marks the title as *Watching* so it is tracked for you |
| **Add to List** | Opens a dialog to pick one of your [lists](lists.md) |
| **Favorite** | Heart icon — adds the title to your [favorites](favorites.md) |
| **Like** / **Mark played** | Feed your recommendations and viewing state |
| **Instant Mix** | Starts playback of a mix of similar items |
| **Refresh Metadata** | Admin only — fetches fresh metadata from the providers |

!!! tip "Monitored favorites"
    A favorite can be **monitored** (shown by a badge on the heart button: "Monitored — auto-downloading & upgrading"). Monitored titles are downloaded automatically when releases appear and upgraded when better-quality releases show up.

### Below the hero

- **Overview** — the plot summary
- **External Links** — buttons that open the title on external sites in a new tab
- **Cast** — actor cards; click one to open the person page with photo, department ("known for"), and their filmography, which is imported automatically on first visit
- **Similar to …** — a row of related movies and shows

Shows add a season/episode browser on top of this — see [Shows in Detail](shows.md).

!!! note
    Admins additionally see a management panel with the media files (codec info, probing), scored releases, active downloads, and repair tools for subtitles and artwork. Regular users don't see this section.

## Adding & Requesting Media

You are not limited to what is already in the library. The [search](search.md) queries the metadata providers too, so results include titles the server doesn't have yet. Opening such a result imports it — with full metadata — and takes you straight to its detail page. From there you can:

1. mark it with **Notify when available**,
2. **favorite it** and let monitoring auto-download it, or
3. just press **Watch** and let Smart Play get it now.

## Smart Play

Pressing **Watch** on something that isn't on disk yet doesn't fail — it triggers the acquisition chain:

1. **File available** → streaming starts immediately.
2. **Download already running** → you land on a status screen with progress, speed, and remaining time.
3. **Releases known** → the best-scored release is downloaded; if it fails, another release is tried automatically.
4. **Nothing known** → your indexers are searched first.

Once the download finishes and is imported, playback starts automatically. If no release can be found at all, you can retry the search manually or go back.

!!! tip
    Leaving the status screen does not cancel anything — the download keeps running on the server, and the title becomes playable once it is imported.

## Next Steps

- [Shows in Detail](shows.md) — seasons, episodes, and show resume
- [Streaming & Playback](streaming.md) — how the player works
- [Lists & Collections](lists.md) — organize media into lists
- [Watch Parties](watch-parties.md) — watch together
