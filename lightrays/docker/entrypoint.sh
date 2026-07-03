#!/bin/bash
set -e

# Ensure runtime directories exist
STATE_DIR="${LIGHTRAYS_STATE_DIR:-/etc/lightrays}"
mkdir -p "$STATE_DIR"
mkdir -p "$XDG_RUNTIME_DIR"

echo "☀️  Lightrays starting..."
echo "   State dir:   $STATE_DIR"
echo "   HTTP port:   ${LIGHTRAYS_HTTP_PORT:-8080}"
echo "   STUN:        ${LIGHTRAYS_STUN_SERVER:-stun://stun.l.google.com:19302}"
echo "   Log level:   ${RUST_LOG:-info}"

# ── Verify GStreamer ─────────────────────────────────────────────────────────
if command -v gst-inspect-1.0 &>/dev/null; then
    echo "   GStreamer:   $(gst-inspect-1.0 --version | head -1)"

    REQUIRED_ELEMENTS="videotestsrc videoconvert x264enc rtph264pay opusenc webrtcbin"
    MISSING=""
    for elem in $REQUIRED_ELEMENTS; do
        if ! gst-inspect-1.0 "$elem" &>/dev/null; then
            MISSING="$MISSING $elem"
        fi
    done

    if [ -n "$MISSING" ]; then
        echo "   ⚠  Missing GStreamer elements:$MISSING"
    else
        echo "   ✔  All required GStreamer elements available"
    fi

    # Check for waylanddisplaysrc
    if gst-inspect-1.0 waylanddisplaysrc &>/dev/null; then
        echo "   ✔  waylanddisplaysrc available (Smithay compositor)"
    else
        echo "   ⚠  waylanddisplaysrc not found — Docker containers won't work"
    fi

    # HW encoders
    HW_ENCODERS="vaapih264enc vah264enc nvh264enc"
    HW_FOUND=""
    for enc in $HW_ENCODERS; do
        if gst-inspect-1.0 "$enc" &>/dev/null; then
            HW_FOUND="$HW_FOUND $enc"
        fi
    done
    if [ -n "$HW_FOUND" ]; then
        echo "   ✔  HW encoders:$HW_FOUND"
    else
        echo "   ℹ  No HW encoders found, using software encoding (x264)"
    fi
else
    echo "   ⚠  GStreamer not found"
fi

# ── Verify Docker socket ────────────────────────────────────────────────────
DOCKER_SOCK="${LIGHTRAYS_DOCKER_SOCKET:-/var/run/docker.sock}"
if [ -S "$DOCKER_SOCK" ]; then
    echo "   ✔  Docker socket: $DOCKER_SOCK"
else
    echo "   ⚠  Docker socket not found at $DOCKER_SOCK — container runners disabled"
fi

# ── Start PulseAudio server ──────────────────────────────────────────────────
PULSE_SOCKET="$XDG_RUNTIME_DIR/pulse/native"

# Kill any surviving PulseAudio process from a previous run
pulseaudio --kill 2>/dev/null || true
for i in $(seq 1 20); do
    if ! pgrep -x pulseaudio >/dev/null 2>&1; then break; fi
    sleep 0.1
done

# Clean ALL stale PulseAudio state (container fs persists across restarts)
rm -rf "$XDG_RUNTIME_DIR/pulse" /var/run/pulse /var/lib/pulse /tmp/pulseaudio.log
mkdir -p "$XDG_RUNTIME_DIR/pulse" /var/run/pulse /var/lib/pulse
chown pulse:pulse "$XDG_RUNTIME_DIR/pulse" /var/run/pulse /var/lib/pulse 2>/dev/null || true
chmod 777 "$XDG_RUNTIME_DIR/pulse" /var/run/pulse

cat > /tmp/lightrays-pulse.pa <<PAEOF
load-module module-native-protocol-unix auth-anonymous=1 socket=$PULSE_SOCKET
load-module module-native-protocol-tcp auth-ip-acl=127.0.0.0/8;172.16.0.0/12;192.168.0.0/16;10.0.0.0/8 auth-anonymous=1
load-module module-always-sink
load-module module-rescue-streams
load-module module-null-sink sink_name=auto_null sink_properties=device.description="Default-Null-Sink"
PAEOF

# Start PulseAudio daemon.
# IMPORTANT: log to a file, NOT stderr.  With --daemonize the parent exits
# closing the pipe; if --log-target=stderr the child inherits the broken pipe
# fd and dies from SIGPIPE on the first log write — this was the root cause of
# PulseAudio failing on container restarts.
PA_EXIT=0
pulseaudio --system --daemonize --disallow-exit \
    --no-cpu-limit --disable-shm=true \
    --high-priority=no \
    --exit-idle-time=-1 \
    --file=/tmp/lightrays-pulse.pa \
    --log-target=file:/tmp/pulseaudio.log --log-level=notice 2>/dev/null || PA_EXIT=$?

if [ "$PA_EXIT" -ne 0 ]; then
    echo "   ⚠  PulseAudio daemon exited with code $PA_EXIT — audio will use test tone fallback"
    [ -f /tmp/pulseaudio.log ] && head -20 /tmp/pulseaudio.log | sed 's/^/      /' || true
else
    # Wait for the socket to appear (up to 3s)
    for i in $(seq 1 30); do
        if [ -S "$PULSE_SOCKET" ]; then break; fi
        sleep 0.1
    done
    chmod 777 "$PULSE_SOCKET" 2>/dev/null || true
fi

export PULSE_SERVER="unix:$PULSE_SOCKET"
export LIGHTRAYS_PULSE_SERVER="$PULSE_SERVER"

if PULSE_SERVER="unix:$PULSE_SOCKET" pactl info &>/dev/null; then
    echo "   ✔  PulseAudio server running (socket: $PULSE_SOCKET)"
else
    echo "   ⚠  PulseAudio failed to start — audio will use test tone fallback"
    [ -f /tmp/pulseaudio.log ] && head -20 /tmp/pulseaudio.log | sed 's/^/      /' || true
fi

echo ""
exec lightrays "$@"
