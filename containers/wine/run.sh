#!/usr/bin/env bash
#
# pyrate-wine ENTRYPOINT
# ======================
# Runs a Windows/Wine game inside a nested gamescope that connects to the
# parent Wayland compositor lightrays runs OUTSIDE the container. See README
# for the full pyrate game-container contract.
#
# What lightrays injects (we only READ these — never set them):
#   WAYLAND_DISPLAY        parent compositor socket name (e.g. wayland-1)
#   XDG_RUNTIME_DIR        /tmp/sockets (holds the wayland + pulse sockets)
#   PULSE_SERVER           unix:/tmp/sockets/pulse/native
#   GAMESCOPE_WIDTH/HEIGHT/REFRESH   requested session geometry
#   /dev/dri (Intel render node), /dev/uinput   passed through as devices
#
# Our launch env (set by lightrays app_env / admin profile):
#   GAME_EXE    (required) absolute path to the .exe to run under Wine
#   GAME_ARGS   (optional) extra args passed to the game (word-split)
#   WINEPREFIX  (optional) default /home/retro/.wine (persisted via mount)
#   WINEARCH    (optional) default win64 (runs 32-bit apps via WoW64)
#   GAMESCOPE_ARGS (optional) extra flags for gamescope (word-split)
#   PYRATE_SKIP_DXVK=1   skip DXVK install (use built-in wined3d)
#   PYRATE_INIT_ONLY=1   create prefix + install DXVK, then exit (warmup)
set -euo pipefail

log() { printf '[pyrate-wine] %s\n' "$*" >&2; }

# --- Home / prefix ----------------------------------------------------------
export HOME="${HOME:-/home/retro}"
export WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"
export WINEARCH="${WINEARCH:-win64}"
export WINEDEBUG="${WINEDEBUG:--all}"
# Disable Mono (.NET) and Gecko (MSHTML). Neither is baked into the image, so
# a fresh `wineboot --init` would otherwise block for minutes trying to
# install Mono via appwiz.cpl (no display to prompt / no network to fetch).
# Games like WoW 3.3.5 need neither; override to skip the install entirely.
export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:-mscoree,mshtml=}"

# This image ships Wine's new-WoW64 build (a single 64-bit Wine, no i386-unix
# host libs), which CANNOT create a pure win32 prefix -- wineboot aborts with
# "WINEARCH is set to 'win32' but this is not supported in wow64 mode". 32-bit
# games (e.g. WoW 3.3.5) run fine in a win64 prefix via WoW64, so coerce
# win32 -> win64 rather than letting wineboot hard-fail the container.
if [ "$WINEARCH" = "win32" ]; then
    log "WARN: WINEARCH=win32 is unsupported by this new-WoW64 Wine build; using win64 (32-bit exes still run via WoW64)"
    export WINEARCH=win64
fi

mkdir -p "$HOME"
mkdir -p "$(dirname "$WINEPREFIX")"

log "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<unset>} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-<unset>}"
log "PULSE_SERVER=${PULSE_SERVER:-<unset>}"
log "WINEPREFIX=$WINEPREFIX WINEARCH=$WINEARCH"

# --- 1. Create / repair the WINEPREFIX (idempotent) -------------------------
# Use a real completion marker (system32/kernel32.dll), NOT system.reg: an
# aborted first init leaves system.reg but no system DLLs, and reusing that
# partial prefix makes Wine fail with "could not load kernel32.dll". Wipe any
# such partial prefix so wineboot rebuilds cleanly.
if [ -f "$WINEPREFIX/drive_c/windows/system32/kernel32.dll" ]; then
    log "Reusing existing WINEPREFIX"
else
    if [ -e "$WINEPREFIX" ]; then
        log "WINEPREFIX is incomplete (aborted init?) — wiping and reinitializing"
        rm -rf "$WINEPREFIX"
    else
        log "Initializing new WINEPREFIX (arch=$WINEARCH)"
    fi
    wineboot --init
    # Block until wineserver has finished writing the prefix before touching it.
    wineserver -w
fi

# --- 2. Install DXVK into the prefix (idempotent) ---------------------------
if [ "${PYRATE_SKIP_DXVK:-0}" = "1" ]; then
    log "PYRATE_SKIP_DXVK=1 — leaving built-in wined3d in place"
else
    if setup_dxvk install; then
        log "DXVK ready"
    else
        log "WARN: DXVK install failed — continuing with built-in wined3d"
    fi
fi

# --- Warmup mode: build the prefix, then stop -------------------------------
if [ "${PYRATE_INIT_ONLY:-0}" = "1" ]; then
    log "PYRATE_INIT_ONLY=1 — prefix prepared, exiting"
    exit 0
fi

# --- 3. Launch the game nested in gamescope ---------------------------------
: "${GAME_EXE:?GAME_EXE must be set to the absolute path of the .exe to run}"
if [ ! -f "$GAME_EXE" ]; then
    log "WARN: GAME_EXE '$GAME_EXE' does not exist yet (game dir bind-mounted at launch?)"
fi

W="${GAMESCOPE_WIDTH:-1920}"
H="${GAMESCOPE_HEIGHT:-1080}"
R="${GAMESCOPE_REFRESH:-60}"

# GAME_EXE is passed as a single argument (robust to spaces); GAME_ARGS and
# GAMESCOPE_ARGS are intentionally word-split so multiple args work.
log "Launch: gamescope -W $W -H $H -r $R ${GAMESCOPE_ARGS:-} -- wine \"$GAME_EXE\" ${GAME_ARGS:-}"
exec gamescope -W "$W" -H "$H" -r "$R" ${GAMESCOPE_ARGS:-} -- \
     wine "$GAME_EXE" ${GAME_ARGS:-}
