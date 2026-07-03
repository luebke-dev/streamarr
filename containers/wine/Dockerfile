# syntax=docker/dockerfile:1
#
# pyrate game-container library — image #1: Wine + gamescope
# ==========================================================
# A lean, self-built runtime for streaming Windows/Wine games through
# lightrays. Deliberately NOT based on games-on-whales (no s6/launch
# scaffolding, no XFCE desktop) — just the bits a nested-gamescope Wine
# session needs.
#
# Base: Arch Linux (rolling) — gamescope, multilib Wine (32-bit for WoW
# 3.3.5) and the Intel Vulkan/GL userspace all live in the official repos,
# which makes this by far the least painful distro to assemble the stack on.
# DXVK is the one exception (not packaged) and is baked from upstream below.
FROM archlinux:latest

# DXVK release baked into the image (installed into each WINEPREFIX at
# runtime by /opt/pyrate/setup_dxvk). v3.0 still ships d3d9.dll, which is
# what WoW 3.3.5 needs.
ARG DXVK_VERSION=3.0

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------
# Enable [multilib] (required for 32-bit Wine + the lib32 GPU userspace),
# do a full sync/upgrade, install the runtime stack in a single layer, then
# aggressively clear the pacman cache + docs/man to keep the image lean.
# The pacman download cache is a BuildKit cache mount, so the .pkg.tar files
# never land in an image layer.
RUN --mount=type=cache,target=/var/cache/pacman/pkg,sharing=locked \
    printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >> /etc/pacman.conf && \
    pacman -Syu --noconfirm --needed \
      gamescope xorg-xwayland \
      wine winetricks cabextract unzip wget \
      vulkan-icd-loader lib32-vulkan-icd-loader \
      vulkan-intel lib32-vulkan-intel \
      mesa lib32-mesa \
      vulkan-tools \
      libpulse lib32-libpulse \
      gnutls lib32-gnutls && \
    pacman -Scc --noconfirm && \
    rm -rf /var/cache/pacman/pkg/* \
           /usr/share/doc/* /usr/share/man/* /usr/share/info/* \
           /var/log/* /tmp/*

# ---------------------------------------------------------------------------
# DXVK (D3D8/9/10/11 -> Vulkan)
# ---------------------------------------------------------------------------
# Not in the Arch repos; bake the upstream release DLLs into the image and
# copy them into each WINEPREFIX at runtime via our setup_dxvk helper. The
# v3.0 tarball no longer ships a setup_dxvk.sh, so we provide our own.
ADD https://github.com/doitsujin/dxvk/releases/download/v${DXVK_VERSION}/dxvk-${DXVK_VERSION}.tar.gz /tmp/dxvk.tar.gz
RUN mkdir -p /opt/pyrate/dxvk && \
    tar -xzf /tmp/dxvk.tar.gz -C /opt/pyrate/dxvk --strip-components=1 && \
    rm /tmp/dxvk.tar.gz && \
    ls -R /opt/pyrate/dxvk

# ---------------------------------------------------------------------------
# pyrate entrypoint + helpers
# ---------------------------------------------------------------------------
COPY run.sh /opt/pyrate/run.sh
COPY setup_dxvk /opt/pyrate/setup_dxvk
RUN chmod +x /opt/pyrate/run.sh /opt/pyrate/setup_dxvk && \
    ln -sf /opt/pyrate/setup_dxvk /usr/local/bin/setup_dxvk

# Persistent per-session state (the WINEPREFIX) lives under /home/retro;
# lightrays bind-mounts the app-state dir over it at launch. World-writable
# so it works whether the session runs as root or an unprivileged uid.
RUN install -d -m 0777 /home/retro

ENV DXVK_VERSION=${DXVK_VERSION} \
    DXVK_DIR=/opt/pyrate/dxvk \
    HOME=/home/retro \
    WINEPREFIX=/home/retro/.wine \
    WINEARCH=win64 \
    WINEDEBUG=-all \
    PYRATE_IMAGE=pyrate-wine

ENTRYPOINT ["/opt/pyrate/run.sh"]
