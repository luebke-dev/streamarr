# streamarr-retro — libretro (RetroArch) kiosk container

One container for **many** retro systems (NES, SNES, N64, GB/GBC, GBA,
Genesis/MD, Mega-CD, Master System, Game Gear, PC Engine, PSX, Atari 2600, 3DO,
Arcade). RetroArch runs as a
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

`RETRO_CORE` is **pinned by the backend** (`container_profiles._derive_rom_launch`)
from the ROM's full path, not just its extension. This matters because several
systems share one extension — `.bin` is Atari 2600 *and* Mega Drive *and* a raw
PSX track, `.chd` is Mega-CD *and* PSX — so only the ROM-set directory it came
from identifies the system. `run.sh`'s `core_for_ext` remains a last-resort
fallback for a manually launched ROM.

## Mounts (per-game, via `app_mounts`)

| Container path | Source | Notes |
| --- | --- | --- |
| `/home/retro` | per-game app-state dir | saves + savestates + config (persistent) |
| `/rom` | host ROM directory (ro) | `RETRO_ROM` points inside it |
| `/system` | host BIOS dir (ro) | only for cores that need BIOS (PSX, Mega-CD, 3DO, Neo-Geo) |

The `/system` mount is derived automatically: `game_platforms._BIOS_DIRS` lists
the platforms whose core cannot boot without a BIOS, and the matching
`roms/bios/<system>/` folder is mounted **flat** at `/system` (cores look their
BIOS up by bare filename, e.g. `scph1001.bin`). Cartridge systems get no mount.
If the folder is absent the game still launches and the core reports the missing
BIOS, rather than failing on a bad bind source.

## Bundled cores

`nestopia snes9x mupen64plus_next gambatte mgba genesis_plus_gx
mednafen_pce_fast pcsx_rearmed mednafen_psx_hw fbneo stella opera` — fetched
from the libretro nightly buildbot at build time into `/cores`. Most are
software-rendered; N64 (GLideN64) and `mednafen_psx_hw` use OpenGL.
`pcsx_rearmed` is the no-BIOS-friendly PSX default (HLE BIOS);
`mednafen_psx_hw` is the higher-accuracy PSX core (needs a real BIOS in
`/system`). `stella` runs Atari 2600, `opera` runs 3DO, and `genesis_plus_gx`
covers Genesis, Mega-CD, Master System and Game Gear. Add a core to the `CORES`
build arg + a row in the backend `game_platforms` registry to support a new
system.

## Saves & BIOS

- **Saves/savestates** land under `/home/retro/{saves,states}` → persisted per
  game (`state_scope = "game"`).
- **BIOS** (PSX region BIOS, Mega-CD `bios_CD_*.bin`, 3DO `panafz*.bin`,
  Neo-Geo `neogeo.zip`, …) must be user-provided under the games library's
  `roms/bios/<system>/` folder; the backend mounts the right one at `/system`
  per game. Cartridge systems need none.

## Build

```
docker build -t ghcr.io/luebke-dev/pyrate-retro:latest containers/retro
```
