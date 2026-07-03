FROM rust:1.94-bookworm AS builder

WORKDIR /build

COPY Cargo.toml Cargo.lock ./
COPY vendor/ vendor/
COPY src/ src/

RUN --mount=type=cache,target=/build/target \
    --mount=type=cache,target=/usr/local/cargo/registry \
    cargo build --release && \
    cp target/release/spotify-downloader /usr/local/bin/spotify-downloader

FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -r -u 1000 -d /data app && \
    mkdir -p /data/config /data/downloads && \
    chown -R app:app /data

COPY --from=builder /usr/local/bin/spotify-downloader /usr/local/bin/spotify-downloader

USER app

ENV SERVER_HOST=0.0.0.0 \
    SERVER_PORT=3000 \
    DATABASE_PATH=/data/spotify.db \
    CONFIG_DIR=/data/config \
    DOWNLOAD_DIR=/data/downloads \
    BITRATE=320 \
    RUST_LOG=spotify_downloader=info,librespot=warn

VOLUME ["/data"]
EXPOSE 3000 8898

ENTRYPOINT ["spotify-downloader"]
