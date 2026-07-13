# Devices, Casting & Offline

Every browser, desktop app, or Android app you sign in with is registered as a **device** on your account. Devices are more than a login list: they are the targets for remote control and casting, and each one keeps its own set of offline downloads.

## My Devices

Open **Settings → My Devices** (see [User Settings](settings.md)) to manage the devices tied to your account. Each device card shows:

- The device **name** — automatically the browser/app name, or a custom name you set
- **Platform** and **Last Seen** timestamp, plus the last IP address it connected from
- A green **Current Device** badge on the device you are using right now

From the card you can:

| Action | What it does |
|--------|--------------|
| **Edit** | Give the device a custom name for easier identification (e.g. "Living-room TV") |
| **Delete** | Removes the device — you are logged out on that device |

!!! warning "Removing the current device"
    Deleting the device you are currently using signs you out immediately.

## Remote control

You can control playback on any of your other signed-in devices. Click the **remote icon** in the top toolbar to open the **Remote Control** menu. It lists:

- Your other devices that are currently connected — including what they are playing right now
- **Cast targets** on the network: Chromecast, AirPlay, and DLNA devices

Select a target and a **Casting to** entry appears at the bottom of the menu. While a target is selected, pressing **Play** on a media page — a movie, an episode, an album — starts playback *on that device* instead of locally, confirmed by a "Playback started on …" message. Click the **X** next to the target to go back to local playback.

The menu doubles as a remote:

=== "streamarr devices"

    - **Play/Pause**, **skip ±10 seconds**, and **Previous/Next** when the target supports a play queue
    - **Volume** slider and **mute** where the target supports it
    - **Send message** — pop up a short text message on the target's screen
    - A status line shows the current title, position, and duration

=== "Cast targets (Chromecast / AirPlay / DLNA)"

    - **Play**, **Pause**, and **Stop**
    - A status line with the transport state and position, plus a refresh button
    - The server automatically prepares the stream in a format the cast device can play

!!! tip "No targets found?"
    Open streamarr on another device — it appears in the list as soon as it is connected. Cast targets are discovered by the *server* on its network, so the server must be able to reach your Chromecast/TV; your administrator can also register cast targets manually.

## Offline downloads

streamarr can prepare **offline copies per device**, so a device can play an item without streaming — subtitles included. Whether offline downloads are available to you, and how many items you can keep, depends on your permissions or [membership plan](membership.md) (look for the *Offline downloads* feature).

Each item on a device moves through these statuses:

| Status | Meaning |
|--------|---------|
| **Queued** | Requested, waiting to be prepared |
| **Downloading** | Being transferred — a progress bar shows the percentage |
| **Ready** | Available for offline playback on that device |
| **Failed** | Something went wrong — the error message is shown on the item |

### Managing offline items

Everything lives in **Settings → My Devices**: every device card has an **Offline sync** panel with status counters and the full item list — progress while downloading, an expiry date if the copy is time-limited, and how many subtitle tracks are bundled. Use the refresh button to update the state.

Once an item is **Ready**, the player falls back to the offline copy automatically when the device has no network connection. Items with an expiry date stop being playable offline once they expire.

!!! note "Per device, not per account"
    Offline items belong to one specific device. Downloading a movie on your phone does not make it offline on your laptop.

## Related pages

- [Streaming & Playback](streaming.md) — the player itself, quality, subtitles
- [Watch Parties](watch-parties.md) — synchronized playback with friends
- [User Settings](settings.md) — everything else on the settings page
- [Membership](membership.md) — plans and the features they unlock
