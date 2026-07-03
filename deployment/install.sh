#!/usr/bin/env bash
# =============================================================================
# pyrate.media installer
# "Your media, your rules."
#
# Supported: Debian 12+, Ubuntu 22.04+, Fedora 39+, RHEL/CentOS 9+
# Usage:     curl -fsSL https://get.pyrate.media | sudo bash
#            or:  sudo bash install.sh
# =============================================================================
set -euo pipefail

PYRATE_VERSION="1.0.0"
INSTALL_DIR="/opt/pyrate-media"
DATA_DIR="/var/lib/pyrate-media"
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"

# Default ports
FRONTEND_PORT=3000
BACKEND_PORT=8000
POSTGRES_PORT=5432
ES_PORT=9200
SABNZBD_PORT=8080
LIGHTRAYS_PORT=8009

# Optional services (disabled by default)
ENABLE_SABNZBD=false
ENABLE_SPOTDL=false
ENABLE_LIGHTRAYS=false
ENABLE_ELASTICSEARCH=true

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# ─── Helpers ──────────────────────────────────────────────────────────────────

banner() {
    echo -e "${PURPLE}${BOLD}"
    cat << 'BANNER'

    ____                   __             __  ___         ___
   / __ \__  ___________ _/ /____        /  |/  /__  ____/ (_)___ _
  / /_/ / / / / ___/ __ `/ __/ _ \      / /|_/ / _ \/ __  / / __ `/
 / ____/ /_/ / /  / /_/ / /_/  __/  _  / /  / /  __/ /_/ / / /_/ /
/_/    \__, /_/   \__,_/\__/\___/  (_)/_/  /_/\___/\__,_/_/\__,_/
      /____/
                     Your media, your rules.

BANNER
    echo -e "${NC}"
    echo -e "  ${CYAN}Installer v${PYRATE_VERSION}${NC}"
    echo ""
}

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }
fatal()   { error "$*"; exit 1; }

ask() {
    local prompt="$1" default="$2" var="$3"
    local input
    echo -ne "${CYAN}? ${NC}${prompt} ${YELLOW}[${default}]${NC}: "
    read -r input
    eval "$var='${input:-$default}'"
}

ask_yn() {
    local prompt="$1" default="$2"
    local input
    echo -ne "${CYAN}? ${NC}${prompt} ${YELLOW}[${default}]${NC}: "
    read -r input
    input="${input:-$default}"
    [[ "${input,,}" =~ ^(y|yes)$ ]]
}

# ─── OS Detection ─────────────────────────────────────────────────────────────

detect_os() {
    if [[ ! -f /etc/os-release ]]; then
        fatal "Cannot detect OS. /etc/os-release not found."
    fi

    . /etc/os-release

    case "$ID" in
        debian|ubuntu|pop|linuxmint|elementary)
            DISTRO_FAMILY="debian"
            DISTRO_NAME="$PRETTY_NAME"
            ;;
        fedora)
            DISTRO_FAMILY="fedora"
            DISTRO_NAME="$PRETTY_NAME"
            ;;
        centos|rhel|rocky|almalinux)
            DISTRO_FAMILY="rhel"
            DISTRO_NAME="$PRETTY_NAME"
            ;;
        *)
            fatal "Unsupported distribution: $ID. Supported: Debian, Ubuntu, Fedora, RHEL, CentOS, Rocky, Alma."
            ;;
    esac

    info "Detected OS: ${DISTRO_NAME} (${DISTRO_FAMILY})"
}

# ─── Prerequisite Checks ─────────────────────────────────────────────────────

check_root() {
    if [[ $EUID -ne 0 ]]; then
        fatal "This script must be run as root. Try: sudo bash install.sh"
    fi
}

check_docker_installed() {
    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        local docker_version
        docker_version=$(docker --version 2>/dev/null || echo "unknown")
        success "Docker already installed: ${docker_version}"
        return 0
    fi
    return 1
}

# ─── Docker Installation ─────────────────────────────────────────────────────

install_docker_debian() {
    info "Installing Docker on ${DISTRO_NAME}..."

    # Remove old versions
    apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

    # Install prerequisites
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg openssl

    # Add Docker GPG key
    install -m 0755 -d /etc/apt/keyrings
    if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
        curl -fsSL "https://download.docker.com/linux/${ID}/gpg" | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg
    fi

    # Add Docker repository
    local arch
    arch=$(dpkg --print-architecture)
    local codename
    # Ubuntu-based distros may not have matching Docker repos, fall back to Ubuntu codename
    codename="${UBUNTU_CODENAME:-${VERSION_CODENAME}}"
    echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${codename} stable" \
        > /etc/apt/sources.list.d/docker.list

    # Install Docker
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    success "Docker installed successfully"
}

install_docker_fedora() {
    info "Installing Docker on ${DISTRO_NAME}..."

    # Remove old versions
    dnf remove -y docker docker-client docker-client-latest docker-common \
        docker-latest docker-latest-logrotate docker-logrotate docker-engine 2>/dev/null || true

    # Install prerequisites
    dnf install -y -q curl openssl

    # Add Docker repository
    dnf config-manager addrepo --from-repofile="https://download.docker.com/linux/fedora/docker-ce.repo" 2>/dev/null \
        || dnf config-manager --add-repo "https://download.docker.com/linux/fedora/docker-ce.repo" 2>/dev/null \
        || true

    # Install Docker
    dnf install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    success "Docker installed successfully"
}

install_docker_rhel() {
    info "Installing Docker on ${DISTRO_NAME}..."

    # Remove old versions
    dnf remove -y docker docker-client docker-client-latest docker-common \
        docker-latest docker-latest-logrotate docker-logrotate docker-engine podman 2>/dev/null || true

    # Install prerequisites
    dnf install -y -q curl openssl yum-utils

    # Add Docker repository
    yum-config-manager --add-repo "https://download.docker.com/linux/centos/docker-ce.repo" 2>/dev/null || true

    # Install Docker
    dnf install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    success "Docker installed successfully"
}

install_docker() {
    if check_docker_installed; then
        return 0
    fi

    case "$DISTRO_FAMILY" in
        debian) install_docker_debian ;;
        fedora) install_docker_fedora ;;
        rhel)   install_docker_rhel ;;
    esac

    # Enable and start Docker
    systemctl enable --now docker
    success "Docker service started"
}

# ─── Configuration ────────────────────────────────────────────────────────────

configure() {
    echo ""
    echo -e "${BOLD}Configuration${NC}"
    echo -e "─────────────────────────────────────────"
    echo ""

    ask "Install directory" "$INSTALL_DIR" INSTALL_DIR
    ask "Data directory" "$DATA_DIR" DATA_DIR
    ask "Frontend port" "$FRONTEND_PORT" FRONTEND_PORT
    ask "Backend API port" "$BACKEND_PORT" BACKEND_PORT

    echo ""
    echo -e "${BOLD}Optional services${NC}"
    echo ""

    if ask_yn "Enable Elasticsearch? (recommended for large libraries)" "y"; then
        ENABLE_ELASTICSEARCH=true
    else
        ENABLE_ELASTICSEARCH=false
    fi

    if ask_yn "Enable SABnzbd? (Usenet downloader)" "n"; then
        ENABLE_SABNZBD=true
        ask "SABnzbd port" "$SABNZBD_PORT" SABNZBD_PORT
    fi

    if ask_yn "Enable Lightrays? (game streaming, requires GPU)" "n"; then
        ENABLE_LIGHTRAYS=true
        ask "Lightrays port" "$LIGHTRAYS_PORT" LIGHTRAYS_PORT
    fi

    echo ""
}

# ─── Secrets Generation ──────────────────────────────────────────────────────

generate_secrets() {
    SECRET_KEY=$(openssl rand -hex 32)
    POSTGRES_PASSWORD=$(openssl rand -hex 16)
    LIGHTRAYS_JWT_SECRET=$(openssl rand -hex 32)
    success "Generated secure secrets"
}

# ─── Directory Structure ─────────────────────────────────────────────────────

create_directories() {
    info "Creating directory structure..."

    mkdir -p "$INSTALL_DIR"
    mkdir -p "$DATA_DIR"/{postgres,redis,elastic}
    mkdir -p "$DATA_DIR"/library/{movies,shows,music}
    mkdir -p "$DATA_DIR"/sabnzbd/{config,downloads,incomplete}
    mkdir -p "$DATA_DIR"/spotdl/{downloads,cache}
    mkdir -p "$DATA_DIR"/{cache,temp}

    # Elasticsearch needs uid 1000
    chown -R 1000:1000 "$DATA_DIR/elastic"

    success "Created directories in ${DATA_DIR}"
}

# ─── Write .env ──────────────────────────────────────────────────────────────

write_env_file() {
    local env_path="${INSTALL_DIR}/${ENV_FILE}"

    if [[ -f "$env_path" ]]; then
        warn ".env already exists at ${env_path} — skipping (secrets preserved)"
        return 0
    fi

    cat > "$env_path" << EOF
# =============================================================================
# pyrate.media configuration
# Generated by installer on $(date -Iseconds)
# =============================================================================

# --- Image ---
REGISTRY=registry.gitlab.com/pyrate.media
IMAGE_TAG=latest

# --- Secrets ---
SECRET_KEY=${SECRET_KEY}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
LIGHTRAYS_JWT_SECRET=${LIGHTRAYS_JWT_SECRET}

# --- Database ---
POSTGRES_USER=pyrate
POSTGRES_DB=pyrate

# --- Paths ---
DATA_DIR=${DATA_DIR}

# --- Ports ---
FRONTEND_PORT=${FRONTEND_PORT}
BACKEND_PORT=${BACKEND_PORT}
POSTGRES_PORT=${POSTGRES_PORT}
ES_PORT=${ES_PORT}
SABNZBD_PORT=${SABNZBD_PORT}
LIGHTRAYS_PORT=${LIGHTRAYS_PORT}

# --- Performance ---
BACKEND_WORKERS=2
WORKER_REPLICAS=2
ES_HEAP_SIZE=512

# --- Lightrays (game streaming) ---
LIGHTRAYS_HOSTNAME=$(hostname -f 2>/dev/null || hostname)
LIGHTRAYS_HOST_XDG_RUNTIME_DIR=/run/user/1000/lightrays
LIGHTRAYS_HOST_STATE_DIR=${DATA_DIR}/lightrays

# --- Optional ---
# ENABLE_HARDWARE_ACCEL=false
# LOG_LEVEL=info
# PUID=1000
# PGID=1000
EOF

    chmod 600 "$env_path"
    success "Wrote ${env_path}"
}

# ─── Write docker-compose.yml ────────────────────────────────────────────────

write_docker_compose() {
    local compose_path="${INSTALL_DIR}/${COMPOSE_FILE}"

    info "Writing docker-compose.yml..."

    cat > "$compose_path" << 'COMPOSE_START'
# pyrate.media docker-compose — generated by installer
services:

  # ── Database ──────────────────────────────────────────────
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      - POSTGRES_USER=${POSTGRES_USER:-pyrate}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB:-pyrate}
    command: postgres -c max_connections=200
    volumes:
      - ${DATA_DIR}/postgres:/var/lib/postgresql/data:rw
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-pyrate}"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Redis ─────────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - ${DATA_DIR}/redis:/data:rw

COMPOSE_START

    # Elasticsearch (optional)
    if [[ "$ENABLE_ELASTICSEARCH" == true ]]; then
        cat >> "$compose_path" << 'COMPOSE_ES'
  # ── Elasticsearch ─────────────────────────────────────────
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.13.4
    restart: unless-stopped
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - xpack.monitoring.collection.enabled=false
      - ES_JAVA_OPTS=-Xms${ES_HEAP_SIZE:-512}m -Xmx${ES_HEAP_SIZE:-512}m
    ulimits:
      memlock: { soft: -1, hard: -1 }
    volumes:
      - ${DATA_DIR}/elastic:/usr/share/elasticsearch/data:rw
    ports:
      - "${ES_PORT:-9200}:9200"
    user: "1000:1000"
    init: true
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:9200/_cluster/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5

COMPOSE_ES
    fi

    # Backend — build depends_on dynamically
    local backend_depends="      db:\n        condition: service_healthy\n      redis:\n        condition: service_started"
    if [[ "$ENABLE_ELASTICSEARCH" == true ]]; then
        backend_depends="${backend_depends}\n      elasticsearch:\n        condition: service_healthy"
    fi

    local es_env=""
    if [[ "$ENABLE_ELASTICSEARCH" == true ]]; then
        es_env="      - ELASTICSEARCH_HOST=elasticsearch\n      - ELASTICSEARCH_PORT=9200"
    fi

    cat >> "$compose_path" << COMPOSE_BACKEND
  # ── Backend API ───────────────────────────────────────────
  backend:
    image: \${REGISTRY:-registry.gitlab.com/pyrate.media}/backend:\${IMAGE_TAG:-latest}
    command: ["uv", "run", "uvicorn", "pyrate.web:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "\${BACKEND_WORKERS:-2}"]
    restart: unless-stopped
    privileged: true
    env_file: .env
    environment:
      - DATABASE_URL=postgresql+asyncpg://\${POSTGRES_USER:-pyrate}:\${POSTGRES_PASSWORD}@db:5432/\${POSTGRES_DB:-pyrate}
      - REDIS_URL=redis://redis:6379/0
$(echo -e "$es_env")
      - SECRET_KEY=\${SECRET_KEY}
      - LIGHTRAYS_URL=http://127.0.0.1:\${LIGHTRAYS_PORT:-8009}
      - LIGHTRAYS_JWT_SECRET=\${LIGHTRAYS_JWT_SECRET}
      - PROJECT_ROOT=/data/
    volumes:
      - \${DATA_DIR}/library/movies:/library/movies:rw
      - \${DATA_DIR}/library/shows:/library/shows:rw
      - \${DATA_DIR}/library/music:/library/music:rw
      - \${DATA_DIR}/sabnzbd/downloads:/downloads:rw
      - \${DATA_DIR}/sabnzbd/incomplete:/incomplete:rw
      - \${DATA_DIR}/spotdl/downloads:/spotdl-downloads:rw
      - \${DATA_DIR}/cache:/cache:rw
      - \${DATA_DIR}/temp:/temp:rw
      - /var/run/docker.sock:/var/run/docker.sock:rw
    ports:
      - "\${BACKEND_PORT:-8000}:8000"
    depends_on:
$(echo -e "$backend_depends")

  # ── Worker ────────────────────────────────────────────────
  worker:
    image: \${REGISTRY:-registry.gitlab.com/pyrate.media}/backend:\${IMAGE_TAG:-latest}
    command: ["uv", "run", "taskiq", "worker", "pyrate.worker:broker"]
    restart: unless-stopped
    privileged: true
    env_file: .env
    environment:
      - DATABASE_URL=postgresql+asyncpg://\${POSTGRES_USER:-pyrate}:\${POSTGRES_PASSWORD}@db:5432/\${POSTGRES_DB:-pyrate}
      - REDIS_URL=redis://redis:6379/0
$(echo -e "$es_env")
      - SECRET_KEY=\${SECRET_KEY}
    volumes:
      - \${DATA_DIR}/library/movies:/library/movies:rw
      - \${DATA_DIR}/library/shows:/library/shows:rw
      - \${DATA_DIR}/library/music:/library/music:rw
      - \${DATA_DIR}/sabnzbd/downloads:/downloads:rw
      - \${DATA_DIR}/sabnzbd/incomplete:/incomplete:rw
      - \${DATA_DIR}/spotdl/downloads:/spotdl-downloads:rw
      - \${DATA_DIR}/cache:/cache:rw
      - \${DATA_DIR}/temp:/temp:rw
      - /var/run/docker.sock:/var/run/docker.sock:rw
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    deploy:
      replicas: \${WORKER_REPLICAS:-2}

  # ── Scheduler ─────────────────────────────────────────────
  scheduler:
    image: \${REGISTRY:-registry.gitlab.com/pyrate.media}/backend:\${IMAGE_TAG:-latest}
    command: ["uv", "run", "taskiq", "scheduler", "pyrate.worker:scheduler"]
    restart: unless-stopped
    env_file: .env
    environment:
      - DATABASE_URL=postgresql+asyncpg://\${POSTGRES_USER:-pyrate}:\${POSTGRES_PASSWORD}@db:5432/\${POSTGRES_DB:-pyrate}
      - REDIS_URL=redis://redis:6379/0
$(echo -e "$es_env")
      - SECRET_KEY=\${SECRET_KEY}
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started

  # ── Frontend ──────────────────────────────────────────────
  frontend:
    image: \${REGISTRY:-registry.gitlab.com/pyrate.media}/frontend:\${IMAGE_TAG:-latest}
    restart: unless-stopped
    ports:
      - "\${FRONTEND_PORT:-3000}:3000"

COMPOSE_BACKEND

    # SABnzbd (optional)
    if [[ "$ENABLE_SABNZBD" == true ]]; then
        cat >> "$compose_path" << 'COMPOSE_SAB'
  # ── SABnzbd ───────────────────────────────────────────────
  sabnzbd:
    image: linuxserver/sabnzbd:latest
    restart: unless-stopped
    environment:
      - PUID=${PUID:-1000}
      - PGID=${PGID:-1000}
    volumes:
      - ${DATA_DIR}/sabnzbd/config:/config:rw
      - ${DATA_DIR}/sabnzbd/downloads:/downloads:rw
      - ${DATA_DIR}/sabnzbd/incomplete:/incomplete:rw
    ports:
      - "${SABNZBD_PORT:-8080}:8080"

COMPOSE_SAB
    fi

    # Lightrays (optional)
    if [[ "$ENABLE_LIGHTRAYS" == true ]]; then
        cat >> "$compose_path" << 'COMPOSE_LR'
  # ── Lightrays (Game Streaming) ────────────────────────────
  lightrays:
    image: ${REGISTRY:-registry.gitlab.com/pyrate.media}/lightrays:${IMAGE_TAG:-latest}
    restart: unless-stopped
    privileged: true
    network_mode: host
    environment:
      - LIGHTRAYS_HOSTNAME=${LIGHTRAYS_HOSTNAME:-lightrays}
      - LIGHTRAYS_API_PORT=${LIGHTRAYS_PORT:-8009}
      - LIGHTRAYS_JWT_SECRET=${LIGHTRAYS_JWT_SECRET}
      - LIGHTRAYS_STUN_SERVER=${LIGHTRAYS_STUN_SERVER:-stun://stun.l.google.com:19302}
      - LIGHTRAYS_CORS_ORIGINS=${LIGHTRAYS_CORS_ORIGINS:-*}
      - XDG_RUNTIME_DIR=/run/lightrays
      - LIGHTRAYS_STATE_DIR=/state/lightrays
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:rw
      - ${LIGHTRAYS_HOST_XDG_RUNTIME_DIR:-/run/user/1000/lightrays}:/run/lightrays:rw
      - ${LIGHTRAYS_HOST_STATE_DIR:-/var/lib/pyrate-media/lightrays}:/state/lightrays:rw

COMPOSE_LR
    fi

    success "Wrote ${compose_path}"
}

# ─── Start Services ──────────────────────────────────────────────────────────

start_services() {
    info "Pulling images (this may take a few minutes)..."
    cd "$INSTALL_DIR"
    docker compose pull --quiet 2>/dev/null || docker compose pull

    info "Starting services..."
    docker compose up -d

    success "Services started"
}

# ─── Health Check ─────────────────────────────────────────────────────────────

wait_for_health() {
    info "Waiting for services to become healthy..."

    local max_wait=120
    local waited=0

    # Wait for backend
    while [[ $waited -lt $max_wait ]]; do
        if curl -sf "http://localhost:${BACKEND_PORT}/docs" > /dev/null 2>&1; then
            success "Backend API is ready"
            break
        fi
        sleep 3
        waited=$((waited + 3))
        echo -ne "\r  Waiting... ${waited}s / ${max_wait}s"
    done
    echo ""

    if [[ $waited -ge $max_wait ]]; then
        warn "Backend did not become healthy within ${max_wait}s. Check logs with: docker compose -f ${INSTALL_DIR}/docker-compose.yml logs backend"
    fi

    # Wait for frontend
    waited=0
    while [[ $waited -lt 60 ]]; do
        if curl -sf "http://localhost:${FRONTEND_PORT}" > /dev/null 2>&1; then
            success "Frontend is ready"
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done
}

# ─── Systemd Service ─────────────────────────────────────────────────────────

setup_systemd() {
    info "Creating systemd service..."

    cat > /etc/systemd/system/pyrate-media.service << EOF
[Unit]
Description=Pyrate.Media
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable pyrate-media.service
    success "Systemd service created and enabled (auto-start on boot)"
}

# ─── Summary ─────────────────────────────────────────────────────────────────

print_summary() {
    echo ""
    echo -e "${GREEN}${BOLD}============================================================${NC}"
    echo -e "${GREEN}${BOLD}  pyrate.media installed successfully!${NC}"
    echo -e "${GREEN}${BOLD}============================================================${NC}"
    echo ""
    echo -e "  ${BOLD}Frontend:${NC}    http://localhost:${FRONTEND_PORT}"
    echo -e "  ${BOLD}Backend API:${NC} http://localhost:${BACKEND_PORT}"
    echo -e "  ${BOLD}API Docs:${NC}    http://localhost:${BACKEND_PORT}/docs"

    if [[ "$ENABLE_SABNZBD" == true ]]; then
        echo -e "  ${BOLD}SABnzbd:${NC}     http://localhost:${SABNZBD_PORT}"
    fi
    if [[ "$ENABLE_LIGHTRAYS" == true ]]; then
        echo -e "  ${BOLD}Lightrays:${NC}   http://localhost:${LIGHTRAYS_PORT}"
    fi

    echo ""
    echo -e "  ${BOLD}Install dir:${NC} ${INSTALL_DIR}"
    echo -e "  ${BOLD}Data dir:${NC}    ${DATA_DIR}"
    echo -e "  ${BOLD}Config:${NC}      ${INSTALL_DIR}/.env"
    echo ""
    echo -e "  ${BOLD}Next steps:${NC}"
    echo -e "    1. Open ${CYAN}http://localhost:${FRONTEND_PORT}${NC} in your browser"
    echo -e "    2. Complete the setup wizard (create admin account)"
    echo -e "    3. Configure TMDB plugin (get API key from themoviedb.org)"
    echo -e "    4. Create your first library"
    echo ""
    echo -e "  ${BOLD}Useful commands:${NC}"
    echo -e "    ${CYAN}cd ${INSTALL_DIR} && docker compose logs -f${NC}     # View logs"
    echo -e "    ${CYAN}cd ${INSTALL_DIR} && docker compose ps${NC}          # Service status"
    echo -e "    ${CYAN}cd ${INSTALL_DIR} && docker compose restart${NC}     # Restart all"
    echo -e "    ${CYAN}cd ${INSTALL_DIR} && docker compose pull && docker compose up -d${NC}  # Update"
    echo -e "    ${CYAN}systemctl status pyrate-media${NC}                   # Systemd status"
    echo ""
    echo -e "  ${YELLOW}Remember to configure your firewall if needed!${NC}"
    echo -e "  ${YELLOW}Ports: ${FRONTEND_PORT} (web), ${BACKEND_PORT} (API)${NC}"
    echo ""
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
    banner
    check_root
    detect_os

    echo ""
    info "This script will install pyrate.media and its dependencies."
    echo ""

    if ! ask_yn "Continue with installation?" "y"; then
        info "Installation cancelled."
        exit 0
    fi

    install_docker
    configure
    generate_secrets
    create_directories
    write_env_file
    write_docker_compose
    start_services
    wait_for_health
    setup_systemd
    print_summary
}

main "$@"
