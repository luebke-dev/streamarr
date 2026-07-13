# streamarr-retro — libretro (RetroArch) kiosk container

One container for **many** retro systems (NES, SNES, N64, GB/GBC, GBA,
Genesis/MD, Master System, PC Engine, PSX, Arcade). RetroArch runs as a
**menu-less kiosk**: a core + ROM are passed on the command line so it boots
straight into the game, and `menu_driver = "null"` removes the launcher UI
entirely. RetroArch quits when the content closes — one game per container.

This is the libretro sibling of `containers/wine`: same gamescope +
nested-Wayland streaming contract, GOW-free, self-built.

## Launch contract

lightrays injects (read-only, never set by us):

| Var / device | Meaning |
| --- | --- |
| `WAYLAND_DISPLAY` | parent compositor socket (e.g. `wayland-1`) |
| `XDG_RUNTIME_DIR` | `/tmp/sockets` (wayland + pulse sockets) |
| `PULSE_SERVER` | `unix:/tmp/sockets/pulse/native` |
| `GAMESCOPE_WIDTH/HEIGHT/REFRESH` | session geometry |
| `/dev/dri`, `/dev/uinput` | render node + virtual input |

Per-game env (from the container profile + game `app_env`):

| Var | Required | Meaning |
| --- | --- | --- |
| `RETRO_CORE` | yes | core name (`snes9x`) or full `*_libretro.so` / path |
| `RETRO_ROM` | yes | absolute ROM path (the game's `app_ref`) |
| `RETRO_SYSTEM_DIR` | no | BIOS dir, default `/system` (mounted read-only) |
| `GAMESCOPE_ARGS` / `RETROARCH_ARGS` | no | extra flags (word-split) |

## Mounts (per-game, via `app_mounts`)

| Container path | Source | Notes |
| --- | --- | --- |
| `/home/retro` | per-game app-state dir | saves + savestates + config (persistent) |
| `/roms` | host ROM library (ro) | `RETRO_ROM` points inside it |
| `/system` | host BIOS dir (ro) | only for cores that need BIOS (PSX, Neo-Geo) |

## Bundled cores

`nestopia snes9x mupen64plus_next gambatte mgba genesis_plus_gx
mednafen_pce_fast pcsx_rearmed mednafen_psx_hw fbneo` — fetched from the
libretro nightly buildbot at build time into `/cores`. Most are
software-rendered; N64 (GLideN64) and `mednafen_psx_hw` use OpenGL.
`pcsx_rearmed` is the no-BIOS-friendly PSX default (HLE BIOS);
`mednafen_psx_hw` is the higher-accuracy PSX core (needs a real BIOS in
`/system`). Add a core to the `CORES` build arg + a row in the backend
`SYSTEMS` registry to support a new system.

## Saves & BIOS

- **Saves/savestates** land under `/home/retro/{saves,states}` → persisted per
  game (`state_scope = "game"`).
- **BIOS** (PSX region BIOS, Neo-Geo `neogeo.zip`, …) must be user-provided in
  the host BIOS dir mounted at `/system`. Cartridge systems need none.

## Build

```
docker build -t ghcr.io/luebke-dev/streamarr-retro:latest containers/retro
```
