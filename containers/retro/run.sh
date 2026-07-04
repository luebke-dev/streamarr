#!/usr/bin/env bash
#
# pyrate-retro ENTRYPOINT
# =======================
# Boots a single retro game under a nested gamescope that connects to the
# parent Wayland compositor lightrays runs OUTSIDE the container, then hands
# off to RetroArch in kiosk mode (no menu). See README for the full contract.
#
# What lightrays injects (we only READ these — never set them):
#   WAYLAND_DISPLAY        parent compositor socket name (e.g. wayland-1)
#   XDG_RUNTIME_DIR        /tmp/sockets (holds the wayland + pulse sockets)
#   PULSE_SERVER           unix:/tmp/sockets/pulse/native
#   GAMESCOPE_WIDTH/HEIGHT/REFRESH   requested session geometry
#   /dev/dri (Intel render node), /dev/uinput   passed through as devices
#
# Our launch env (set by the container profile / per-game app_env):
#   RETRO_ROM    (required) absolute path to the ROM (game's app_ref)
#   RETRO_CORE   (optional) libretro core override — "snes9x" or a full
#                path/.so. If unset, the core is auto-detected from the ROM
#                file extension (see core_for_ext), so a game only needs its
#                ROM file — no per-game core config.
#   RETRO_SYSTEM_DIR (optional) BIOS dir, default /system (mounted read-only)
#   GAMESCOPE_ARGS   (optional) extra flags for gamescope (word-split)
#   RETROARCH_ARGS   (optional) extra flags for retroarch (word-split)
set -euo pipefail

log() { printf '[pyrate-retro] %s\n' "$*" >&2; }

# Map a ROM file extension → bundled libretro core basename. Keep in sync with
# the backend's ROM-extension registry. Ambiguous extensions (.bin, .zip) get
# a best-effort default; set RETRO_CORE to override.
core_for_ext() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        nes|fds|unf|unif)      echo nestopia ;;
        sfc|smc|swc|fig|bs)    echo snes9x ;;
        n64|z64|v64|ndd)       echo mupen64plus_next ;;
        gb|gbc|dmg)            echo gambatte ;;
        gba)                   echo mgba ;;
        md|gen|smd|sgd|68k|bin) echo genesis_plus_gx ;;
        sms|gg|sg)             echo genesis_plus_gx ;;
        pce|sgx)               echo mednafen_pce_fast ;;
        cue|chd|pbp|m3u|exe)   echo pcsx_rearmed ;;
        zip|7z)                echo fbneo ;;
        *)                     echo "" ;;
    esac
}

export HOME="${HOME:-/home/retro}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
CORES_DIR="${CORES_DIR:-/cores}"
KIOSK_CFG="/opt/pyrate/retroarch-kiosk.cfg"

# Per-game persistent state dirs (under the /home/retro mount). RetroArch
# writes .srm saves + savestates here; they survive because lightrays mounts
# the per-game app-state dir over /home/retro.
mkdir -p "$HOME/saves" "$HOME/states" "$HOME/config" "$XDG_CONFIG_HOME/retroarch"

log "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<unset>} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-<unset>}"
log "PULSE_SERVER=${PULSE_SERVER:-<unset>}"

# --- Resolve the ROM (needed before core auto-detection) -------------------
: "${RETRO_ROM:?RETRO_ROM must be set to the ROM path (from the game app_ref)}"

# --- Resolve the core .so (RETRO_CORE override, else from ROM extension) ----
if [ -z "${RETRO_CORE:-}" ]; then
    RETRO_CORE="$(core_for_ext "${RETRO_ROM##*.}")"
    if [ -z "$RETRO_CORE" ]; then
        log "ERROR: could not auto-detect a core for '${RETRO_ROM##*.}' — set RETRO_CORE."
        exit 1
    fi
    log "auto-detected core '$RETRO_CORE' from .${RETRO_ROM##*.}"
fi
case "$RETRO_CORE" in
    /*) CORE_SO="$RETRO_CORE" ;;                        # absolute path given
    *_libretro.so) CORE_SO="$CORES_DIR/$RETRO_CORE" ;;  # full filename given
    *.so) CORE_SO="$CORES_DIR/$RETRO_CORE" ;;
    *) CORE_SO="$CORES_DIR/${RETRO_CORE}_libretro.so" ;; # short name given
esac
if [ ! -f "$CORE_SO" ]; then
    log "ERROR: core '$RETRO_CORE' not found at '$CORE_SO'. Available cores:"
    ls -1 "$CORES_DIR" 2>/dev/null | sed 's/^/[pyrate-retro]   /' >&2 || true
    exit 1
fi

if [ ! -f "$RETRO_ROM" ]; then
    log "WARN: ROM '$RETRO_ROM' does not exist (ROM file bind-mounted at launch?)"
fi

W="${GAMESCOPE_WIDTH:-1920}"
H="${GAMESCOPE_HEIGHT:-1080}"
R="${GAMESCOPE_REFRESH:-60}"

# --- Per-user controller override (deadzone + D-pad mode) ------------------
# lightrays injects RETRO_ANALOG_DEADZONE / RETRO_DPAD_MODE from the user's
# gaming preferences. Materialise them into a RetroArch --appendconfig so they
# override the baked kiosk cfg without mutating it.
APPEND_ARGS=""
OVERRIDE_CFG="$HOME/pyrate-controller.cfg"
if [ -n "${RETRO_ANALOG_DEADZONE:-}" ] || [ -n "${RETRO_DPAD_MODE:-}" ]; then
    : > "$OVERRIDE_CFG"
    if [ -n "${RETRO_ANALOG_DEADZONE:-}" ]; then
        printf 'input_analog_deadzone = "%s"\n' "$RETRO_ANALOG_DEADZONE" >> "$OVERRIDE_CFG"
    fi
    if [ -n "${RETRO_DPAD_MODE:-}" ]; then
        for p in 1 2 3 4 5; do
            printf 'input_player%s_analog_dpad_mode = "%s"\n' "$p" "$RETRO_DPAD_MODE" >> "$OVERRIDE_CFG"
        done
    fi
    APPEND_ARGS="--appendconfig $OVERRIDE_CFG"
    log "controller override applied: $(tr '\n' ' ' < "$OVERRIDE_CFG")"
fi

log "core=$CORE_SO"
log "rom=$RETRO_ROM"
log "Launch: gamescope -W $W -H $H -r $R ${GAMESCOPE_ARGS:-} -- retroarch -L <core> <rom> --config $KIOSK_CFG ${APPEND_ARGS}"

# The core and ROM are passed as single arguments (robust to spaces);
# GAMESCOPE_ARGS / RETROARCH_ARGS / APPEND_ARGS are intentionally word-split.
exec gamescope -W "$W" -H "$H" -r "$R" ${GAMESCOPE_ARGS:-} -- \
     retroarch -L "$CORE_SO" "$RETRO_ROM" \
     --config "$KIOSK_CFG" --fullscreen ${APPEND_ARGS} ${RETROARCH_ARGS:-}
