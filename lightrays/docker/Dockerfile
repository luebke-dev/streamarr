###############################################################################
# lightrays Dockerfile
#
# Multi-stage build:
#   Stage 1:  Compile gst-wayland-display (Smithay-based Wayland compositor)
#   Stage 1b: Compile lightrays binary (Rust — axum + GStreamer + bollard)
#   Stage 2:  Ubuntu 24.04 runtime with GStreamer, PulseAudio
###############################################################################

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Build gst-wayland-display from source (Rust + cargo-c)
# ─────────────────────────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS gst-wl-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gcc g++ make pkg-config git ca-certificates \
        libwayland-dev libxkbcommon-dev libinput-dev libgbm-dev libdrm-dev \
        libudev-dev libseat-dev libssl-dev \
        libegl-dev libgl-dev \
        libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
        libgstreamer-plugins-bad1.0-dev \
        libclang-dev \
    && rm -rf /var/lib/apt/lists/*

ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH="/usr/local/cargo/bin:$PATH"

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --default-toolchain 1.89.0 \
    && cargo install cargo-c --version 0.10.18 --locked

# Pin upstream so the local patches keep applying cleanly. Bump the SHA
# when you pull in new upstream fixes and re-verify the patches.
ARG GST_WAYLAND_DISPLAY_REV=bc021a4
RUN git clone https://github.com/games-on-whales/gst-wayland-display.git \
        /build/gst-wayland-display \
    && git -C /build/gst-wayland-display checkout "$GST_WAYLAND_DISPLAY_REV"
WORKDIR /build/gst-wayland-display

# Local patches on top of upstream. Resize patch: let VideoInfo updates hit
# the wayland Output after it's been created so games see the new resolution.
COPY docker/gst-wayland-display-resize.patch /tmp/gst-wayland-display-resize.patch
RUN git apply /tmp/gst-wayland-display-resize.patch

RUN cargo cinstall --prefix=/usr/local --release 2>&1

RUN mkdir -p /output && \
    cp -v /usr/local/lib/gstreamer-1.0/libgstwaylanddisplaysrc.so /output/ 2>/dev/null || \
    find /usr/local -name "*.so" -path "*/gstreamer*" -exec cp -v {} /output/ \; || \
    find /usr/local -name "libgstwaylanddisplay*" -exec cp -v {} /output/ \;

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1b: Build lightrays binary
# ─────────────────────────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gcc g++ make pkg-config ca-certificates \
        libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
        libgstreamer-plugins-bad1.0-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH="/usr/local/cargo/bin:$PATH"

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --default-toolchain 1.89.0

# Copy Rust source
COPY ./ /build/lightrays-stream/

WORKDIR /build/lightrays-stream

RUN cargo build --release \
    && strip target/release/lightrays

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Runtime image
# ─────────────────────────────────────────────────────────────────────────────
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        # GStreamer runtime + plugins (including webrtcbin in plugins-bad)
        gstreamer1.0-tools \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-plugins-ugly \
        gstreamer1.0-libav \
        gstreamer1.0-x \
        gstreamer1.0-pulseaudio \
        gstreamer1.0-vaapi \
        gstreamer1.0-nice \
        # VA-API drivers for HW encoding (Intel iHD for Gen8+, mesa for AMD)
        intel-media-va-driver mesa-va-drivers vainfo \
        # GPU info for Smithay compositor
        hwdata \
        # Runtime deps for gst-wayland-display (Smithay compositor)
        libwayland-server0 libxkbcommon0 libinput10 libgbm1 \
        libegl1 libdrm2 libseat1 libudev1 \
        # PulseAudio
        pulseaudio pulseaudio-utils \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── gst-wayland-display GStreamer plugin ─────────────────────────────────────
COPY --from=gst-wl-builder /output/*.so /usr/local/lib/gstreamer-1.0/
ENV GST_PLUGIN_PATH="/usr/local/lib/gstreamer-1.0"
RUN ldconfig

WORKDIR /app

# ── lightrays binary ─────────────────────────────────────────────────────────
COPY --from=builder /build/lightrays-stream/target/release/lightrays /usr/local/bin/lightrays

# ── Environment defaults ────────────────────────────────────────────────────
ENV LIGHTRAYS_HOSTNAME=Lightrays \
    LIGHTRAYS_API_PORT=8080 \
    LIGHTRAYS_STREAMING_PORT=8081 \
    LIGHTRAYS_METRICS_PORT=9090 \
    LIGHTRAYS_METRICS_BIND_ADDR=127.0.0.1 \
    LIGHTRAYS_STUN_SERVER=stun://stun.l.google.com:19302 \
    LIGHTRAYS_GOW_IMAGE=ghcr.io/games-on-whales/steam:edge \
    LIGHTRAYS_RECONNECT_GRACE_SECS=30 \
    LIGHTRAYS_WS_TICKET_TTL_SECS=120 \
    LIGHTRAYS_STATE_DIR=/etc/lightrays \
    XDG_RUNTIME_DIR=/tmp/lightrays-runtime \
    RUST_LOG=info

EXPOSE 8080 8081 9090

# ── Entrypoint ──────────────────────────────────────────────────────────────
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

LABEL org.opencontainers.image.description="Lightrays: WebRTC desktop streaming to browsers"

ENTRYPOINT ["/entrypoint.sh"]
