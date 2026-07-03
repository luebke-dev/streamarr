FROM rust:1.88-alpine AS builder

RUN apk add --no-cache musl-dev pkgconfig openssl-dev openssl-libs-static

WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY src/ src/

RUN cargo build --release

FROM alpine:3.22

RUN apk add --no-cache p7zip && \
    adduser -D -u 1000 app && \
    mkdir -p /data /downloads && \
    chown -R app:app /data /downloads

COPY --from=builder /build/target/release/torrent-downloader /usr/local/bin/torrent-downloader

USER app

ENV SERVER_HOST=0.0.0.0 \
    SERVER_PORT=3000 \
    DATABASE_PATH=/data/torrent-downloader.db \
    DOWNLOAD_DIR=/downloads \
    MAX_CONCURRENT_DOWNLOADS=5 \
    ENABLE_DHT=true \
    RUST_LOG=torrent_downloader=info,tower_http=info

VOLUME ["/data"]
EXPOSE 3000 6881/tcp 6881/udp

ENTRYPOINT ["torrent-downloader"]
