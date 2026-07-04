# syntax=docker/dockerfile:1
#
# pyrate game-container library — image #2: RetroArch (libretro) kiosk
# ===================================================================
# One container for MANY retro systems. RetroArch is run headless as a
# KIOSK: a core + ROM are passed on the command line so it boots straight
# into the game, and `menu_driver = "null"` (see retroarch-kiosk.cfg)
# removes the menu entirely — no RGUI/XMB, no launcher UI. RetroArch quits
# when the content closes, which fits the one-game-per-container model.
#
# Per game, lightrays injects RETRO_CORE (which core to load) and RETRO_ROM
# (the ROM path, from the game's app_ref); everything else is the same
# gamescope + nested-Wayland contract the pyrate-wine image already uses.
#
# Base: Arch Linux — retroarch, gamescope, Xwayland and the Intel Vulkan/GL
# userspace are all packaged. The libretro CORES are fetched from the
# canonical libretro nightly buildbot (they aren't reliably packaged), which
# keeps the curated core set explicit and reproducible.
FROM archlinux:latest

# Curated libretro core set (buildbot basenames, without the _libretro.so
# suffix). Add a system here + a row in the backend SYSTEMS registry to
# support it — nothing else changes. beetle_psx_hw is the HW/GL PSX core;
# the rest are software-rendered and run on any GPU.
ARG CORES="nestopia snes9x mupen64plus_next gambatte mgba genesis_plus_gx mednafen_pce_fast pcsx_rearmed mednafen_psx_hw fbneo"
ARG LIBRETRO_BUILDBOT=https://buildbot.libretro.com/nightly/linux/x86_64/latest

# ---------------------------------------------------------------------------
# System packages (single layer, cache-mounted pacman, then trimmed lean)
# ---------------------------------------------------------------------------
RUN --mount=type=cache,target=/var/cache/pacman/pkg,sharing=locked \
    pacman -Syu --noconfirm --needed \
      retroarch \
      gamescope xorg-xwayland \
      mesa vulkan-intel vulkan-icd-loader vulkan-tools \
      libpulse \
      unzip wget ca-certificates && \
    pacman -Scc --noconfirm && \
    rm -rf /var/cache/pacman/pkg/* \
           /usr/share/doc/* /usr/share/man/* /usr/share/info/* \
           /var/log/* /tmp/*

# ---------------------------------------------------------------------------
# libretro cores (fetched from the nightly buildbot into /cores)
# ---------------------------------------------------------------------------
# Each core ships as <name>_libretro.so.zip (a single .so). We drop the .so
# into /cores and its .info metadata into RetroArch's libretro_directory so
# core-matched features (savestates) work even when loaded by absolute path.
RUN mkdir -p /cores /usr/lib/libretro && \
    for c in ${CORES}; do \
      echo "fetching core: ${c}" && \
      wget -q "${LIBRETRO_BUILDBOT}/${c}_libretro.so.zip" -O "/tmp/${c}.zip" && \
      unzip -o -q "/tmp/${c}.zip" -d /cores && \
      rm -f "/tmp/${c}.zip" && \
      wget -q "https://buildbot.libretro.com/assets/frontend/info/${c}_libretro.info" \
           -O "/usr/lib/libretro/${c}_libretro.info" || true ; \
    done && \
    ln -sf /cores/*.so /usr/lib/libretro/ 2>/dev/null || true && \
    ls -la /cores && \
    for c in ${CORES}; do \
      test -f "/cores/${c}_libretro.so" || { echo "MISSING CORE: ${c}_libretro.so (bad buildbot name?)" >&2; exit 1; } ; \
    done

# ---------------------------------------------------------------------------
# Gamepad autoconfig profiles (RetroPad autodetection across all cores)
# ---------------------------------------------------------------------------
# One physical->RetroPad mapping is reused by EVERY core, so a recognised pad
# "just works" with no per-system input setup. Fetch the upstream profiles
# into the configured joypad_autoconfig_dir.
RUN mkdir -p /usr/share/libretro/autoconfig && \
    wget -q "https://github.com/libretro/retroarch-joypad-autoconfig/archive/refs/heads/master.tar.gz" \
         -O /tmp/autoconf.tar.gz && \
    tar -xzf /tmp/autoconf.tar.gz -C /tmp && \
    cp -r /tmp/retroarch-joypad-autoconfig-master/* /usr/share/libretro/autoconfig/ && \
    rm -rf /tmp/autoconf.tar.gz /tmp/retroarch-joypad-autoconfig-master || true

# ---------------------------------------------------------------------------
# pyrate entrypoint + baked kiosk config
# ---------------------------------------------------------------------------
COPY retroarch-kiosk.cfg /opt/pyrate/retroarch-kiosk.cfg
COPY run.sh /opt/pyrate/run.sh
RUN chmod +x /opt/pyrate/run.sh

# Persistent per-game state (saves + savestates + config) lives under
# /home/retro; lightrays bind-mounts the app-state dir over it at launch.
# World-writable so it works as root or an unprivileged uid.
RUN install -d -m 0777 /home/retro

ENV HOME=/home/retro \
    XDG_CONFIG_HOME=/home/retro/.config \
    CORES_DIR=/cores \
    PYRATE_IMAGE=pyrate-retro

ENTRYPOINT ["/opt/pyrate/run.sh"]
