FROM ghcr.io/games-on-whales/xfce:edge
COPY bg.jpg /usr/share/backgrounds/xfce/bg.jpg
COPY docker/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml
COPY docker/xfce4/xfconf/xfce-perchannel-xml/keyboard-layout.xml /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/keyboard-layout.xml
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y --no-install-recommends \
        curl gcc g++ make pkg-config ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
        wine \
        wine32:i386 \
        winetricks \
        mesa-vulkan-drivers \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvulkan1 \
    libvulkan-dev \
    vulkan-tools \
    libgl1-mesa-dri \
    && rm -rf /var/lib/apt/lists/*

RUN dpkg --add-architecture i386 && apt-get update && sudo apt install -y \
libvulkan1 libvulkan1:i386 \
mesa-vulkan-drivers mesa-vulkan-drivers:i386 \
libgl1 libgl1:i386 \
libgl1-mesa-dri libgl1-mesa-dri:i386 \
libglu1-mesa libglu1-mesa:i386 \
mesa-utils \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends \
    winbind \
    && rm -rf /var/lib/apt/lists/*