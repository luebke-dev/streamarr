FROM rust:1.87-alpine AS builder

RUN apk add --no-cache musl-dev

WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY src/ src/

RUN cargo build --release

FROM debian:bookworm-slim

RUN apt-get update && \
    echo "deb http://deb.debian.org/debian bookworm non-free" >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
    par2 unrar p7zip-full ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -m -u 1000 app && \
    mkdir -p /data /downloads && \
    chown -R app:app /data /downloads

COPY --from=builder /build/target/release/usenet-downloader /usr/local/bin/usenet-downloader

USER app

ENV SERVER_HOST=0.0.0.0 \
    SERVER_PORT=3000 \
    DATABASE_PATH=/data/usenet.db \
    DOWNLOAD_DIR=/downloads \
    DOWNLOAD_TEMP_DIR=/downloads/.tmp \
    DOWNLOAD_MAX_CONCURRENT_JOBS=3 \
    RUST_LOG=usenet_downloader=info,tower_http=info

VOLUME ["/data"]
EXPOSE 3000

ENTRYPOINT ["usenet-downloader"]
