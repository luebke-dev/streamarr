# Streamarr Desktop

The Streamarr desktop app plays your media with a native player instead of a browser
video element, and streams games from the same server. It exists because the browser
cannot do two things the server can serve:

- **HDR and high-bitrate video.** Browsers restrict what they will decode and how they
  render it. The desktop app hands the file to [mpv](https://mpv.io/), which supports
  `gpu-next`, HDR passthrough and hardware decoding.
- **Game streaming over WebRTC.** Browser WebRTC imposes its own jitter buffer and
  decoder sandboxing and gives no access to hardware decoder interop.

The web interface is unchanged and still works in a browser. The desktop app embeds that
same interface, but the video and the game stream are decoded outside it.

!!! warning "Status"
    The app is under active development. Media playback, login and profile management
    work; game streaming is implemented but not yet verified against a live server.
    See [Limits](#limits) for what has and has not been tested.

## Installation

### Linux

Three formats are built. They are equivalent in content; pick by how you manage
software.

| Format | Use when | Command |
|---|---|---|
| `.deb` | Debian, Ubuntu, Linux Mint | `sudo apt install ./Streamarr_<version>_amd64.deb` |
| `.rpm` | Fedora, RHEL, openSUSE | `sudo dnf install ./Streamarr-<version>-1.x86_64.rpm` |
| AppImage | Any distribution, no install | `chmod +x Streamarr_<version>_amd64.AppImage && ./Streamarr_<version>_amd64.AppImage` |

The AppImage bundles its own libraries (about 113 MB) and needs FUSE. On a system
without FUSE, run it with `--appimage-extract-and-run`.

### Windows

NSIS and MSI installers are planned but **not yet built**; the build requires a Windows
host and none has run this code. There is no download link to give yet.

### mpv is required, and not bundled

The app needs `mpv` on your `PATH`. It is **not** installed as a package dependency,
because whether to bundle it or use the system's is still an open decision (plan task
4.2), and because distributions expect to provide their own.

=== "Debian / Ubuntu"

    ```bash
    sudo apt install mpv
    ```

=== "Fedora"

    ```bash
    sudo dnf install mpv
    ```

=== "Arch"

    ```bash
    sudo pacman -S mpv
    ```

If `mpv` is missing, playback fails with a message saying so rather than playing
silently into nothing.

## First start

1. **Start the app.** A configuration directory is created:
   `~/.config/media.streamarr.desktop/` on Linux.
2. **Enter your server address** on the login screen — for example
   `https://streamarr.example.com`. If your server is on a private network with its own
   DNS, see [Server address and the IP pin](#server-address-and-the-ip-pin).
3. **Log in.** Your session is stored in the operating system's keyring (Secret Service
   on Linux, Credential Manager on Windows), **not** in the app's own files.

## Profiles

A profile is one server plus one user. Profiles live in
`~/.config/media.streamarr.desktop/profiles.json`, one directory each under
`profiles/<id>/`.

`profiles/<id>/mpv.conf` is a normal mpv configuration file, and it is yours to edit.
Everything the app passes on the command line overrides it, so an entry there cannot
fight the app's own settings — but it is also not silently ignored.

```ini
# profiles/standard/mpv.conf
profile=gpu-hq
scale=ewa_lanczossharp
sub-font-size=42
```

### Preferences

| Setting | Default | Meaning |
|---|---|---|
| Start in fullscreen | on | Playback opens fullscreen. See [Window behaviour](#window-behaviour). |
| Ask before transcoding | on | A transcode costs the server far more than a direct play. |
| Audio language | — | An ISO code such as `de` or `en`. `ger` and `deu` are understood too. |
| Subtitle language | — | The same codes; `none` keeps subtitles off. |

Language matching uses an explicit ISO 639-1 ↔ 639-2 table rather than a prefix rule,
because the prefix idea is wrong for German (`ger`/`deu`), French (`fre`/`fra`) and
Spanish (`spa`) — and it silently merges Slovenian (`sl`) with Slovak (`slk`).

## Window behaviour

The player is a **separate window**, not an area inside the app's window, and on Wayland
that means it takes over the screen and the interface window is hidden while you watch.

This is not a preference; it is what Wayland allows. A Wayland client may not position
its own windows — `gtk_window_move()` is ignored by GNOME/Mutter, measured — and GNOME
ships no `layer-shell`, so a positioned overlay is impossible. A window that covered part
of the interface would therefore have to be placed by the compositor, somewhere
unpredictable.

On X11 and Windows, where clients may position their windows, the player appears as a
positioned overlay over the interface instead.

There is a practical consequence worth knowing: **the player window is a normal window**,
so it can be moved, resized or sent to another monitor or workspace with your usual
window controls, and closing it stops playback.

## Playing media

Open a film or episode and playback starts in a separate window. The interface becomes a
status screen: the video is in the player's window, not in the page.

| Key | Action |
|---|---|
| `Space` | Pause / resume |
| `F` | Fullscreen |
| `←` / `→` | Seek 5 seconds |
| `↑` / `↓` | Seek 60 seconds |
| `9` / `0` | Volume down / up |
| `m` | Mute |
| `j` / `J` | Cycle subtitle tracks |
| `#` | Cycle audio tracks |
| `q` | Quit playback |

These are mpv's own defaults; the profile's `mpv.conf` can rebind them.

### Direct Play and transcoding

When the server can send the original file, the app plays it unmodified — no server CPU
is spent and the picture is exactly what is on disk. This is called **Direct Play** and it
is the normal case.

The server transcodes only when it must, for example when the container or codec is one
the client did not claim. A transcode is reported before playback starts, because it can
make the server slow for everyone else sharing it.

The app tells the server what it can play, so the server does not transcode needlessly.
Those capabilities are sent as **query parameters**, not as a request body: the endpoint
ignores a body silently, and the result would be an unnecessary transcode with nothing in
any log to explain it.

### Resuming

Playback continues where you stopped, with three exceptions, because "start where the
user stopped" is wrong more often than it looks:

- **Under 30 seconds in** — those are studio logos, not a viewing position.
- **Inside the credits** — the last 120 seconds, or the last 2 % on a long film,
  whichever is larger. Without this, a film would appear to finish instantly.
- **Marked as played** — your explicit action wins over a leftover position.

If the status screen offers *Start from the beginning*, that override is available before
playback rather than after it.

## Games

Games stream from the server over WebRTC, decoded by GStreamer into a native window, with
keyboard, mouse and gamepad input forwarded to the game.

!!! warning "Not yet verified"
    This path is implemented but has not been run against a live session, because the
    test server's database was unavailable while it was written. Treat it as untested.

### Gamepads

Standard-layout pads (Xbox, DualShock, DualSense, 8BitDo, Stadia, Switch Pro, GameSir)
are recognised by name. Anything else is treated as **non-standard layout**, which swaps
the first four buttons. If your pad's A/B and X/Y are swapped, that is why — use the
manual override in the settings.

## Server address and the IP pin

If your server's hostname does not resolve to the address that actually answers — common
with internal DNS, split-horizon DNS or a VPN that advertises an address it cannot serve
— enter the real address under **IP address** in the profile.

This is deliberately *not* the same as typing the IP as the server address:

- Entering the IP as the address **breaks TLS**, because certificates are issued for
  names, not addresses. The connection is refused rather than silently downgraded.
- Entering the name plus the IP as a pin **keeps the name** for the TLS check and only
  changes where the connection goes. The certificate still has to match, and it still
  does.

Without a pin, a request to a dead address waits for the connection timeout and then
fails — the app reports this as a timeout with the advice to set the pin, rather than as
a generic network error.

## Troubleshooting

### "Playback failed" with no further detail

Check that `mpv` is installed and on your `PATH`:

```bash
mpv --version
```

### The film starts from the beginning every time

If it is under 30 seconds in, that is intended. Otherwise check that progress is reaching
the server: the app reports your position as you watch, and a position the server never
received cannot be resumed from.

### The video plays but the audio does not

Check the audio track, not the volume. Files often carry several tracks and the profile's
language preference decides which one is selected. Look in the player's own log file —
the app passes `--log-file`, so mpv's diagnostics are kept rather than discarded:

```
$XDG_RUNTIME_DIR/streamarr-mpv-<pid>-<n>.log
```

The line `AO: [<driver>]` names the output device mpv chose.

### Nothing loads at all, and the interface stays empty

The app's own log is at `~/.config/media.streamarr.desktop/` (and on stderr). Look for
`Konfiguration:` on startup, which reports where the configuration lives and where
credentials are stored.

### Credentials are not stored in the keyring

The app reports `Token-Ablage:` on startup. If the keyring is unavailable — a headless
session or a container without a Secret Service — the app falls back to a file with
restricted permissions and says so, rather than refusing to run.

## Updates

Streamarr Desktop updates itself from the project's release feed — **not** from your
server. That is deliberate, and the reason is worth knowing if you self-host.

The app is a client: your profiles say where *media and games* come from, and there can be
several. The update feed is a fixed address compiled into the bundle. If it pointed at your
instance, then whoever runs whatever server you typed in would decide which code your
computer runs — and with two profiles there would be no way to say which one should. Every
deployment would also have to carry and maintain desktop bundles. Measured: the server does
not check the client's version at all, so app and server versions are genuinely independent
— they happen to read the same number today, but nothing couples them.

The app follows one of two channels:

| Channel | Receives |
|---|---|
| `stable` | Released versions only. The default. |
| `beta` | Pre-releases as well. |

A build whose version carries a pre-release suffix (`2026.3.0-beta.1`) follows `beta`
automatically; everything else follows `stable`. A stable build is **never** offered a
pre-release, even when the pre-release carries the higher number — a channel is a promise,
and the check happens before the version comparison for exactly that reason. A beta build
receives both channels, so it is not stranded when it wants to come back to stable.

An update that is offered is verified against a public key compiled into the bundle; an
unsigned or wrongly signed update is refused. There is no setting to skip that check.

### "It says it is up to date"

The app writes the reason to its log for every check, so the answer does not have to be
guessed. The three possible answers are different and are not conflated:

- **An update is available.** The only case the app shows you anything.
- **There is none.** The log names both versions.
- **This build cannot check** — it was built without an update endpoint or without a
  signing key. That is a build problem, not a network problem, and retrying will not help.

Being offline is not treated as an error. An app that complains about a failed update check
on every start is an app whose messages people learn to ignore — and then a real one gets
ignored too.

## Limits

What has been **measured**, and what has not:

**Verified**

- The app starts on Wayland, creates its configuration, and stores credentials in the OS
  keyring.
- **Deep links.** `streamarr://` is registered with the desktop
  (`xdg-mime query default x-scheme-handler/streamarr` answers `streamarr-handler.desktop`),
  and a URL handed to a running app is received — verified with two processes, where the
  second exits and the first logs the link. A login link naming a foreign `server` is
  refused, with the reason in the log.
- **Update checks reach the release feed without any server.** The feed was fetched from a
  machine with no Streamarr instance, no profile and no token.
- Media playback: direct play from the server's file endpoint, resume at a stored
  position, HDR mode selection, and the address pin reaching a player that has no
  equivalent of `curl --resolve`.
- Bundles: `.deb` and AppImage contents inspected, with zero unresolved shared libraries;
  the `.deb` extracted and started.

**Not verified**

- **Playback against a live Streamarr server.** The test server's database was down for
  the whole of this work. The chain was verified against a stand-in server using the real
  media, profile, tunnel and player. **What exactly is missing, and how to restore it, is
  written down** — see the repository's
  `docs/plans/desktop-testserver-stand.md` (the server's database container was destroyed;
  a leftover Docker network endpoint holds the address the backend needs; the database
  files themselves are intact).
- **Game streaming.** Same reason, same page.
- **The OIDC/browser login end to end.** The test server has `oidc_enabled: false`, so a
  real browser login cannot be exercised. The link's shape is checked against the server's
  own callback endpoint, read from its sources.
- **Installing an update.** No release has been published, so no update has ever been
  downloaded and installed. The feed answers `HTTP 404` today, which the app treats as
  "no release yet" rather than as a failure.
- **Windows.** No bundle has been built and no Windows host has run this code.
- **AppImage execution.** The build container has no FUSE, so only the extracted contents
  could be checked.
- **macOS.** Out of scope for now.
