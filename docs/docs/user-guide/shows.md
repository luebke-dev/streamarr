# Shows in Detail

Shows use the same detail page, Smart Play, and player as everything else — this page covers what is special about them: seasons and episodes, smart resume, binge playback, and how new episodes can arrive on their own. For the basics (detail page, actions, files), see [Movies & Shows](movies.md).

## Shows, seasons, and episodes

A show contains seasons, and a season contains episodes. All three levels open as a detail page:

| Level | What you see |
|-------|--------------|
| **Show** | Overview, cast, similar shows, and a **Seasons** row — one poster card per season with its episode count |
| **Season** | Titled "Show · Season", with an **Episodes** list: still image, episode number, title, air date, runtime, and description |
| **Episode** | Titled "Show · S1E3", with the episode overview and its own play button |

Episodes that already have a file show a play button directly in the episodes list, so you can start any episode without opening it first.

!!! note "Season 0 (Specials)"
    Bonus content and special episodes are grouped into a "Season 0". Administrators can hide specials for everyone with the **Hide Season 0 (Specials)** switch in the show library settings.

## Watch — smart resume

Pressing **Watch** on a show always picks the right episode for you:

1. **Resume** — an episode you started but did not finish continues where you left off
2. **Next** — otherwise, the episode after the last one you completed
3. **Start** — if you have not watched anything yet, the first episode
4. **Replay** — if you finished everything, the show starts over from the first episode

On a season page the same logic applies, limited to that season.

Shows you are in the middle of also appear in **Continue Watching** on the home page — see [Viewing History](history.md).

## Binge-friendly playback

While an episode plays, the top bar shows the show name, season/episode number, and episode title. The player adds **Previous Episode** / **Next Episode** buttons with a small preview, and when an episode ends the next one starts automatically. Where markers exist, **Skip Intro**, **Skip Outro**, and **Skip Credits** buttons appear at the right moments — see [Streaming & Playback](streaming.md) for all player features.

!!! tip "Prefetch"
    Administrators can enable **Prefetch Downloads** in the show library settings. The server then downloads the next episode in the background while you are still watching the current one, so it is ready the moment you need it.

## When an episode isn't there yet

- **Smart Play** handles missing files: press play, and the episode is searched on the configured indexers, downloaded, and streamed as soon as it is ready ([Streaming & Playback](streaming.md)).
- Opening a show, season, or episode with nothing to play quietly triggers a release search in the background — repeated at most once per day per item.
- If nothing playable is found, the play button turns into a bell: **Notify when available**. Click it and you will be notified once the title becomes watchable (the button then reads **Watching**).

## Auto-download for favorite shows

Marking a show as a favorite (heart icon) does more than bookmark it — the show with all of its seasons and episodes becomes **monitored**:

- Missing episodes are searched and downloaded automatically
- Newly aired episodes are picked up as they appear (the server re-checks every few hours)
- Existing files can be upgraded when better-quality releases show up

On the [Favorites](favorites.md) page, monitored shows carry a badge with the tooltip *"Monitored — auto-downloading & upgrading"*. Removing the favorite stops the monitoring — files that were already downloaded are never deleted.

!!! note
    Automatic downloading for favorites is a server-wide option that your administrator has to enable. Until then, favoriting a show only marks it as monitored without starting downloads.

## Metadata & external links

Show, season, and episode metadata — titles, descriptions, artwork, air dates, runtimes — comes primarily from TMDB. When a show has been matched, the **External Links** section on its detail page links to the entry on TMDB, TVDB, or IMDb.

## Next Steps

- [Streaming & Playback](streaming.md) — Smart Play and all player controls
- [Viewing History](history.md) — Continue Watching and your watch history
- [Favorites](favorites.md) — managing favorites
- [Watch Parties](watch-parties.md) — watch episodes together
