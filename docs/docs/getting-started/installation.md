# Installation

This guide walks you through the installation of Pyrate.Media.

## Prerequisites

### System Requirements

- **Operating System**: Linux, Windows, or macOS
- **CPU**: 2+ cores (4+ recommended for transcoding)
- **RAM**: 4GB minimum (8GB+ recommended)
- **Storage**: 20GB free (50GB+ recommended)
- **Network**: Stable internet connection

### Required Software

=== "Docker (Recommended)"

    - [Docker](https://docs.docker.com/get-docker/) 20.10+
    - [Docker Compose](https://docs.docker.com/compose/install/) 2.0+

=== "Development"

    - [Python](https://www.python.org/downloads/) 3.11+
    - [uv](https://github.com/astral-sh/uv) (Python Package Manager)
    - [Node.js](https://nodejs.org/) 18+
    - [Yarn](https://yarnpkg.com/)
    - [PostgreSQL](https://www.postgresql.org/download/) 14+
    - [Redis](https://redis.io/download) 6+

## Installation

### Docker Compose (Recommended)

Docker Compose is the easiest way to start Pyrate.Media.

#### 1. Clone the repository

```bash
git clone https://github.com/luebke-dev/pyrate.media.git
cd pyrate.media
```

#### 2. Configure environment variables

Copy the example configuration:

```bash
cp .env.example .env
```

Edit the `.env` file:

```bash
# Database
POSTGRES_DB=pyrate
POSTGRES_USER=pyrate
POSTGRES_PASSWORD=sicheres_passwort

# Redis
REDIS_URL=redis://redis:6379/0

# Application
SECRET_KEY=dein_secret_key
DEBUG=false

# OIDC (Optional)
OIDC_ENABLED=false
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=
OIDC_DISCOVERY_URL=
```

#### 3. Start services

```bash
docker-compose up -d
```

This starts:
- PostgreSQL database
- Redis cache
- Backend API server
- Frontend web server
- TaskIQ Worker

#### 4. Initialize the database

```bash
docker-compose exec backend uv run alembic upgrade head
```

#### 5. Create an admin user

The first user can be created via the API or OIDC.

#### 6. Access the application

- **Frontend**: http://localhost:3000
- **API Documentation**: http://localhost:8000/docs

### Development Environment

For local development or customizations.

#### 1. Clone the repository

```bash
git clone https://github.com/luebke-dev/pyrate.media.git
cd pyrate.media
```

#### 2. Set up the backend

```bash
cd backend

# Install dependencies with uv
uv sync

# Run database migrations
uv run alembic upgrade head

# Start the development server
uv run uvicorn pyrate.web:app --reload --host 0.0.0.0 --port 8000
```

#### 3. Start the worker (separate terminal)

```bash
cd backend
uv run taskiq worker pyrate.worker:broker
```

#### 4. Set up the frontend

```bash
cd frontend

# Install dependencies
yarn install

# Start the development server
yarn dev
```

#### 5. Services

Make sure PostgreSQL and Redis are running:

```bash
# With Docker
docker run -d --name postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:14
docker run -d --name redis -p 6379:6379 redis:7
```

## Post-Installation

### 1. Configure plugins

#### TMDB API Key

1. Register at [TMDB](https://www.themoviedb.org/settings/api)
2. Get your API key
3. Configure the TMDB plugin in the admin panel

#### IGDB Credentials (for games)

1. Register at [Twitch Developers](https://dev.twitch.tv/)
2. Create an application and get the Client ID and Secret
3. Configure the IGDB plugin

### 2. Create libraries

1. Go to **Administration** → **Libraries**
2. Click **Create Library**
3. Choose the type (Movies, Shows, Games)
4. Configure the storage path
5. Save

### 3. Add indexers

1. Go to **Administration** → **Indexers**
2. Click **Add Indexer**
3. Choose the indexer type
4. Configure URL and API key
5. Test connection and save

### 4. Set up download clients

1. Go to **Administration** → **Downloader**
2. Click **Add Downloader**
3. Choose the client type (SABnzbd, Deluge)
4. Configure connection details
5. Test connection and save

## Verification

### Health Check

```bash
# API status
curl http://localhost:8000/health

# Frontend
curl http://localhost:3000
```

### Service Status

=== "Docker Compose"

    ```bash
    docker-compose ps
    ```

=== "Manual"

    Check that all services are running:
    - Backend API (Port 8000)
    - Frontend (Port 3000)
    - PostgreSQL (Port 5432)
    - Redis (Port 6379)
    - Worker processes

## Troubleshooting

### Database connection failed

```bash
# Check PostgreSQL logs
docker-compose logs postgres

# Verify connection string
echo $DATABASE_URL
```

### Redis connection failed

```bash
# Check Redis logs
docker-compose logs redis

# Test Redis connection
redis-cli ping
```

### Frontend not loading

```bash
# Check frontend logs
docker-compose logs frontend

# Check build
docker-compose exec frontend ls -la /app/dist
```

### Worker not starting

```bash
# Check worker logs
docker-compose logs worker

# Start manually for debugging
docker-compose exec backend uv run taskiq worker pyrate.worker:broker
```

## Security Notes

!!! warning "Production Environment"
    For production use:

    - Change all default passwords
    - Use strong, unique secret keys
    - Enable HTTPS/TLS
    - Configure firewall rules
    - Keep software up to date

!!! tip "Backup Strategy"
    Regular backups of:

    - PostgreSQL database
    - Configuration files
    - Media files
    - Plugin configurations

## Next Steps

1. **[Quick Start](quick-start.md)** - Learn the basics
2. **[Dashboard](../user-guide/dashboard.md)** - Explore the interface
3. **[Administration](../administration/overview.md)** - Configure the system
