# streamarr-wine

Image #1 of the **streamarr game-container** library: a lean, self-built
Wine + gamescope runtime for streaming Windows games through
[lightrays](../../lightrays). Deliberately **not** based on
games-on-whales — no s6 supervision, no `/opt/gow` launch scaffolding, no
desktop. Just gamescope, Wine, DXVK and the Intel Vulkan/GL userspace, with
one small entrypoint script.

Tag: `ghcr.io/luebke-dev/streamarr-wine:latest` (built locally; **not pushed** —
the `ghcr.io` prefix only exists to satisfy lightrays' registry allowlist).

## Why Arch Linux

gamescope, multilib Wine (needed for 32-bit games like WoW 3.3.5) and the
Intel Vulkan/GL userspace are all in the official Arch repos at current
versions, so the whole stack assembles with one `pacman -S` on a rolling
base. Only DXVK isn't packaged — it's baked from the upstream release.

## The streamarr game-container contract

lightrays runs a headless Wayland compositor (`gst-wayland-display`)
**outside** the container and captures/encodes/streams its output over
WebRTC. This image is a Wayland **client** of that compositor.

### What lightrays provides (this image only READS these)

| Injected | Value / meaning |
| --- | --- |
| `WAYLAND_DISPLAY` | parent compositor socket name, e.g. `wayland-1` |
| `XDG_RUNTIME_DIR` | `/tmp/sockets` — holds the parent wayland + pulse sockets |
| `PULSE_SERVER` | `unix:/tmp/sockets/pulse/native` |
| `GAMESCOPE_WIDTH` / `GAMESCOPE_HEIGHT` / `GAMESCOPE_REFRESH` | session geometry |
| `/dev/dri` (Intel render node), `/dev/uinput` | passed through as devices |
| bind mount at `/home/retro` | persistent per-session state (holds the WINEPREFIX) |
| GOW-legacy env (`RUN_GAMESCOPE=1`, `GOW_REQUIRED_DEVICES`, `XKB_DEFAULT_LAYOUT`, `PUID`/`PGID`) | ignored except the `GAMESCOPE_*` geometry above |

### What this image does

1. Creates/repairs the `WINEPREFIX` idempotently (`wineboot --init`).
2. Installs DXVK into the prefix on first run (`setup_dxvk install`),
   tolerant of re-runs.
3. Runs the game nested in gamescope, which connects to the parent
   compositor via `$WAYLAND_DISPLAY` and provides XWayland for the Wine
   game:
   ```sh
   exec gamescope -W "$W" -H "$H" -r "$R" -- wine "$GAME_EXE" $GAME_ARGS
   ```
   Audio routes to `PULSE_SERVER`; input comes from `/dev/uinput`.

### Launch env (set by lightrays `app_env` / admin profile)

| Var | Req | Default | Meaning |
| --- | --- | --- | --- |
| `GAME_EXE` | yes | — | absolute path to the `.exe` to run under Wine |
| `GAME_ARGS` | no | — | extra args for the game (word-split) |
| `WINEPREFIX` | no | `/home/retro/.wine` | persisted via the mounted state dir |
| `WINEARCH` | no | `win64` | runs 32-bit apps (e.g. WoW 3.3.5) via WoW64. **`win32` is not supported** by this new-WoW64 Wine build (no `i386-unix`) and is coerced to `win64` by the entrypoint |
| `GAMESCOPE_ARGS` | no | — | extra flags appended to gamescope (word-split) |
| `STREAMARR_SKIP_DXVK` | no | `0` | `1` = keep built-in wined3d instead of DXVK |
| `STREAMARR_INIT_ONLY` | no | `0` | `1` = build prefix + install DXVK, then exit (warmup) |

The game directory itself is **not** baked into the image — lightrays
bind-mounts it read-write at launch and points `GAME_EXE` at it.

## Files

- `Dockerfile` — Arch base + multilib packages + baked DXVK.
- `run.sh` — the ENTRYPOINT (`/opt/streamarr/run.sh`); implements the contract above.
- `setup_dxvk` — dependency-free DXVK installer (`/usr/local/bin/setup_dxvk`);
  copies the baked DLLs into the prefix and registers native DLL overrides.
  Auto-detects a win32 vs win64 (WoW64) prefix.

## Build

```sh
docker build -t ghcr.io/luebke-dev/streamarr-wine:latest containers/wine/
```

Do **not** push — a local image with the `ghcr.io` tag satisfies lightrays'
registry allowlist and is never pulled.

## Smoke check

The build sandbox has no GPU and no parent compositor, so the actual stream
and game launch can't be exercised here — only tool presence + prefix/DXVK
setup:

```sh
docker run --rm --entrypoint bash ghcr.io/luebke-dev/streamarr-wine:latest -c '
  wine --version; wine64 --version; gamescope --version;
  Xwayland -version 2>&1 | head -1; winetricks --version;
  command -v setup_dxvk; vulkaninfo --summary 2>&1 | head'
```

## Needs real-launch verification (can't be tested here)

- gamescope actually connecting to the parent compositor via `$WAYLAND_DISPLAY`
  and presenting a surface (needs lightrays' `gst-wayland-display`).
- Vulkan on the real Intel render node (`vulkaninfo` can't create an instance
  without `/dev/dri`; the Intel ICD manifest is present but unexercised).
- Audio reaching `PULSE_SERVER`, and input via `/dev/uinput`.
- DXVK D3D9 rendering WoW 3.3.5 end-to-end (prefix creation + DLL install are
  verified; on-GPU rendering is not).
- Whether running Wine as root (current default) is acceptable in production
  or a drop to an unprivileged uid is preferred (device access relies on the
  container being privileged).
