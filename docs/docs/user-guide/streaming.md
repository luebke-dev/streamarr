# Streaming & Playback

streamarr.media plays movies, shows, and more directly in your browser or app. Pressing **Play** always does the right thing — whether the file is already on the server or still has to be fetched first.

## Smart Play

When you press Play, the server checks availability and reacts automatically:

| What you see | What is happening |
|--------------|-------------------|
| "Checking availability..." | The server looks for a playable file |
| Progress bar with **Speed** and **Remaining** | No file yet — the best matching release is being downloaded |
| "Download complete, importing…" | The download finished and is being added to the library |
| "No release found" | Nothing suitable was found — use **Search Releases** to pick one manually |
| Error message | Something went wrong — **Retry** or **Go Back** |

The waiting screen shows the poster and title of what you picked, and playback starts by itself as soon as the file is ready. You can press **Cancel** at any time.

## Direct play or transcode

The player detects which video and audio formats your device can play. Compatible files are **direct played** in original quality; everything else is **transcoded** on the server in real time. This is fully automatic — you never have to choose.

!!! note "Seeking"
    Jumping to a part of the video that has not been transcoded yet can take a few seconds while the stream restarts at the new position. Positions you already buffered are instant.

## Player controls

The top bar shows a back button, the title (for episodes: show name, season/episode number, and episode title) and the time the video will end ("Ends at …"). The bottom bar contains:

- **Play/Pause** — also by clicking the video, plus 10-second skip buttons in both directions
- **Previous / Next Episode** — for shows and playlists, with a small preview of the episode
- **Volume** — slider and mute button (on phones, use the hardware volume keys)
- **Timeline** — click or drag to seek; hovering shows the target time, and where the server has generated trickplay previews you also get thumbnail images while scrubbing
- **Audio Track**, **Subtitles**, **Quality** — see below
- **Picture-in-Picture** — keep watching in a floating window (if your browser supports it)
- **Fullscreen**

A heart button marks the title as a favorite; on small screens the secondary actions move into a **⋮** menu.

### Quality

The **Quality** menu lists every version the server knows about: the file you are watching, other **Downloaded** files, lower **Transcode** resolutions generated on the fly, and better releases that are not on disk yet (greyed out, badged **Download required**).

### Audio tracks & subtitles

Pick any embedded audio track from the **Audio Track** menu — switching may briefly restart the stream. The **Subtitles** menu lists all available subtitle tracks plus **Off**. Your audio and subtitle choices are remembered per title and reused the next time you play it.

### Skip intro, outro & credits

When a title has markers, **Skip Intro**, **Skip Outro**, and **Skip Credits** buttons appear at the right moments. Under [User Settings](settings.md) → Playback Preferences you can choose per marker type whether to *show a skip button*, *skip automatically*, or disable skipping.

## Next episode & playlists

For episodes, the previous/next buttons walk through the show, and when an episode ends the next one starts automatically. Playing from a playlist works the same way, following the playlist order.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| ++space++ / ++k++ | Play / pause |
| ++arrow-left++ / ++arrow-right++ | Back / forward 10 seconds |
| ++arrow-up++ / ++arrow-down++ | Volume up / down |
| ++m++ | Mute |
| ++f++ | Fullscreen |
| ++esc++ | Exit fullscreen |

!!! tip
    Scrolling the mouse wheel over the player also adjusts the volume.

## Resume

Your position is saved automatically while you watch. Unfinished titles appear in **Continue Watching** on the home page and resume exactly where you left off; if you stopped right at the end, the title counts as watched and starts from the beginning next time. See [Viewing History](history.md).

## Reporting a problem

If the file itself is bad — wrong content, wrong language, poor video or audio, or a broken file — click the flag icon and submit **Report & Request New Download**. The file is flagged and a replacement is requested automatically.

!!! note "Stream Info"
    Administrators additionally see a **Stream Info** button with technical details: source file, codecs, resolution, and why (or whether) the stream is being transcoded.

## Watching somewhere else

- [Devices, Casting & Offline](devices.md) — cast to Chromecast, AirPlay, or DLNA devices, remote-control your other signed-in devices, and download titles for offline playback
- [Watch Parties](watch-parties.md) — watch together in sync with friends
