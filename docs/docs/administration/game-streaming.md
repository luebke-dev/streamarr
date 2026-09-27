# Retro Game Streaming

The **retro** container profile runs cartridge and disc-based consoles in the browser through RetroArch and a curated set of libretro cores. This page covers the administrator side: how ROMs are laid out, which systems need a BIOS, and how to troubleshoot a game that will not start.

For the player-facing experience, see [Games](../user-guide/games.md).

## Library layout

The games library is scanned for ROM files. One directory per system is the expected layout, and the directory name is what decides the platform:

```
games/
├── roms/
│   ├── nes/
│   ├── snes/
│   ├── n64/
│   ├── atari2600/
│   ├── megacd/
│   ├── psx/
│   ├── 3do/
│   └── bios/
│       ├── psx/
│       ├── megacd/
│       └── 3do/
└── <PC game directories>
```

!!! tip "Why the directory decides, not the extension"
    Several systems share one file extension. A `.bin` is an Atari 2600 ROM, a Mega Drive ROM, and a raw PlayStation track. Game Gear sets are commonly named `.sms`, the same extension as Master System. The ROM-set directory is the only reliable signal, so it wins over the extension. A file with an unambiguous extension (`.z64`, `.nes`, `.sfc`) still resolves correctly even from the wrong folder.

## Supported systems

The bundled retro image ships these cores. A system without a core here cannot be played, and its ROMs are not imported (see [Not yet supported](#not-yet-supported)).

| System | ROM-set folder | Core |
|--------|----------------|------|
| NES / Famicom | `nes`, `famicom` | nestopia |
| SNES / Super Famicom | `snes`, `sfc` | snes9x |
| Nintendo 64 | `n64` | mupen64plus_next |
| Game Boy / Game Boy Color | `gb`, `gbc` | gambatte |
| Game Boy Advance | `gba` | mgba |
| Mega Drive / Genesis | `genesis`, `megadrive`, `md` | genesis_plus_gx |
| Master System | `sms` | genesis_plus_gx |
| Game Gear | `gamegear`, `gg` | genesis_plus_gx |
| Mega-CD / Sega CD | `megacd` | genesis_plus_gx |
| Atari 2600 | `atari2600` | stella |
| PC Engine / TurboGrafx-16 | `turbografx`, `pce`, `tg16` | mednafen_pce_fast |
| PlayStation | `psx` | pcsx_rearmed |
| Arcade | `arcade` | fbneo |
| 3DO | `3do` | opera |

!!! warning "Not every descriptive folder name is recognised"
    The folder has to match a known platform alias exactly. `mastersystem`, `pcengine`, and `segacd` are **not** aliases: a ROM in a folder with one of those names and an ambiguous extension (`.bin`, `.iso`, `.chd`) silently resolves to the wrong platform. Use the names in the table above. A `.sms` file in `mastersystem/` still works because the extension itself is unambiguous, but do not rely on that.

## BIOS files

Cartridge systems boot straight from the ROM and need nothing else. Four systems cannot start without a firmware image, and the core looks it up **by bare filename** in RetroArch's system directory. That is why each system's BIOS files live in their own folder and are mounted flat for the session.

Put them here, one folder per system, using the **exact filenames** in the tables below:

```
games/roms/bios/<system>/
```

The backend detects the folder for the platform it is launching and mounts it read-only at `/system` inside the session container. When the folder is absent, the session still starts and the core reports the missing BIOS rather than failing on a bad mount.

### PlayStation (`psx`)

The core only looks for these names. If it finds none, it falls back to a built-in high-level emulation BIOS, which lowers compatibility and is not recommended:

| Filename | Region |
|----------|--------|
| `scph5501.bin` | US (v3.0) |
| `scph5502.bin` | Europe (v3.0) |
| `scph5500.bin` | Japan (v3.0) |
| `psxonpsp660.bin` | from a PSP |

The core also accepts any file whose name starts with `scph`, so other retail dumps (`scph1001.bin`, `scph7001.bin`) work too.

!!! warning "Check the filenames, not just the files"
    A common mistake is having the right BIOS data under a name the core never looks for. A file called `scph7003.bin` may in fact hold the US v3.0 image, but the core searches for `scph5501.bin` first and falls back to high-level emulation when it finds nothing it recognises. Rename each BIOS to the region-appropriate name from the table. Verify with `md5sum` against the [libretro documentation](https://docs.libretro.com/library/pcsx_rearmed/) rather than trusting the filename.

### Mega-CD / Sega CD (`megacd`)

One file per region. The core picks the matching region's BIOS automatically:

| Filename | Region |
|----------|--------|
| `bios_CD_U.bin` | US (Sega CD) |
| `bios_CD_E.bin` | Europe (Mega-CD) |
| `bios_CD_J.bin` | Japan (Mega-CD) |

### 3DO (`3do`)

Any one of these is enough:

| Filename | Model |
|----------|-------|
| `panafz1.bin` | Panasonic FZ-1 |
| `panafz10.bin` | Panasonic FZ-10 |
| `panafz10e-anvil.bin` | Panasonic FZ-10-E |
| `goldstar.bin` | Goldstar GDO-101M |

Some Japanese titles additionally need a Kanji font ROM (`panafz1-kanji.bin`). See the [Opera core documentation](https://docs.libretro.com/library/opera/) for the full list.

### Arcade (`arcade`)

The FBNeo core needs the Neo Geo BIOS for Neo Geo titles:

| Filename | Purpose |
|----------|---------|
| `neogeo.zip` | Neo Geo BIOS (stays zipped) |

## BIOS folders are not games

Anything inside a BIOS directory is deliberately excluded from the library. The scanner treats these directory names as support data, at any depth:

```
bios/  BIOS Files/  bioses/  firmware/  system/  system files/
```

Without this, firmware images are imported as media items and show up as playable titles named after the file, for example `scph1001` or `bios CD U`. If you already scanned before adding a BIOS folder, the entries stay in the database until the next scan removes them.

Only **directory** names count, so a game legitimately called `System.nes` is not mistaken for firmware.

## Disc-based games

Mega-CD, PlayStation, and 3DO titles are disc images. Multi-track games should use a `.cue` or `.m3u` file next to the tracks, not a bare `.bin`, so the core sees the whole disc.

!!! warning "Do not store 3DO or arcade ROMs as 7z archives"
    The Opera and FBNeo cores require uncompressed content, and the image cannot extract `.7z` (no `7z` binary). A `.7z` ROM downloads and mounts fine, then fails at load with:

    ```
    [ERROR] [Content] Failed to extract content from compressed file
    ```

    Extract 3DO and arcade ROMs to `.iso`, `.cue`, or `.bin` and keep `.zip` only where the core supports it (FBNeo reads zipped arcade sets directly).

## Not yet supported

These systems have no core in the bundled image, and no platform alias either. Their ROMs are therefore **not imported at all**: they never appear in the library, so nothing is shown for them and no scan warning is raised.

| ROM-set folder | System |
|----------------|--------|
| `atari5200` | Atari 5200 |
| `atari7800` | Atari 7800 |
| `colecovision` | ColecoVision |
| `jaguar` | Atari Jaguar |
| `lynx` | Atari Lynx |
| `sega32x` | Sega 32X |
| `virtualboy` | Virtual Boy |

Adding one is a code change: register the platform and its aliases, map its ROM extensions, and add the core to the retro image. See `backend/src/streamarr/services/game_platforms.py` and `containers/retro/Dockerfile`.

## Troubleshooting

Start here when a game will not launch. The per-session container log shows what the backend decided and what the core reported.

**The session starts and immediately stops.** Check which core and ROM were used:

```bash
docker logs lightrays-<session-id> | grep 'streamarr-retro'
```

You should see the resolved core and ROM:

```
[streamarr-retro] core=/cores/pcsx_rearmed_libretro.so
[streamarr-retro] rom=/rom/Vib-Ribbon.pbp
```

**A wrong core is picked.** The backend resolves the core from the ROM's path, so a mis-resolved platform means the ROM is in the wrong folder. Move it into the correct `<system>` directory and rescan.

**The game starts but shows a BIOS screen or a black screen.** The BIOS is missing or misnamed. Confirm the mount happened:

```bash
docker inspect lightrays-<session-id> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

A disc-based session shows a `/system` mount, pointing at the BIOS folder on the host:

```
<host games path>/roms/bios/psx -> /system (ro)
```

No `/system` line means the platform needs a BIOS but the folder was not found. Check the path and the folder name against the tables above.

**Content fails to extract.** The ROM is a `.7z` archive for a core that needs uncompressed input. See the note above.

## Related

- [Games](../user-guide/games.md) for the player-facing experience
- [Libraries](libraries.md) for scanning and platform filters
- [Page Layouts](page-layouts.md) for the sections on the games browse page
