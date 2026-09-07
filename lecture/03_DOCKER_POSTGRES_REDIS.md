# 03 — Dockerized PostgreSQL/pgvector and Redis

**Working directory:** `policy-vault/`  
**Build output:** persistent local database and cache services  
**Application runtime:** remains local through `uv`

## Why only the services are Dockerized

Running the Python API locally keeps the edit/run/debug loop fast. PostgreSQL with pgvector and
Redis have more installation variance, so containers give the lab a repeatable service layer.

The images below deliberately pin major capabilities. pgvector 0.8.6 is used because it is the
current extension version verified for this guide and includes important fixes over earlier 0.8.x
releases. Redis 8 includes Search/vector capabilities in Redis Open Source.

## 1. Create Compose configuration

**File:** `policy-vault/compose.yaml`

```yaml
name: policy-vault

services:
  postgres:
    image: pgvector/pgvector:0.8.6-pg17
    environment:
      POSTGRES_DB: policy_vault
      POSTGRES_USER: policy_vault
      POSTGRES_PASSWORD: policy_vault
    ports:
      - "5432:5432"
    volumes:
      # A named volume keeps authoritative state across container recreation.
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U policy_vault -d policy_vault"]
      interval: 5s
      timeout: 5s
      retries: 20

  redis:
    image: redis:8.2-alpine
    ports:
      - "6379:6379"
    volumes:
      # Persistence is useful for observation, though cache data remains disposable.
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 20

volumes:
  postgres_data:
  redis_data:
```

## 2. Create typed configuration inputs

**File:** `policy-vault/.env.example`

```dotenv
APP_ENV=development
LOG_LEVEL=INFO
DATABASE_URL=postgresql+psycopg://policy_vault:policy_vault@localhost:5432/policy_vault
REDIS_URL=redis://localhost:6379/0
UPLOAD_DIR=./data/uploads
MAX_UPLOAD_BYTES=10485760
MAX_PDF_PAGES=100
CHUNK_SIZE=800
CHUNK_OVERLAP=120
EMBEDDING_PROVIDER=sentence-transformer
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSIONS=384
SEMANTIC_CACHE_ENABLED=true
SEMANTIC_CACHE_TTL_SECONDS=3600
SEMANTIC_CACHE_DISTANCE_THRESHOLD=0.12
REDIS_CACHE_INDEX=idx:semantic-cache
REDIS_CACHE_PREFIX=semantic-cache:
WARM_EMBEDDING_MODEL=true
OUTBOX_POLL_SECONDS=2.0
OUTBOX_LEASE_SECONDS=60
```

Copy it to the ignored runtime file:

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

The credentials are intentionally local lab credentials. Never reuse them in a hosted system.

## 3. Start and inspect services

```bash
docker compose up -d
docker compose ps
docker compose logs postgres
docker compose logs redis
```

Verify PostgreSQL and extension availability:

```bash
docker compose exec postgres psql -U policy_vault -d policy_vault -c "SELECT version();"
docker compose exec postgres psql -U policy_vault -d policy_vault -c "SELECT default_version FROM pg_available_extensions WHERE name = 'vector';"
```

Verify Redis and Search commands:

```bash
docker compose exec redis redis-cli PING
docker compose exec redis redis-cli COMMAND INFO FT.SEARCH
```

Expected essentials:

- PostgreSQL returns a version row.
- The extension query returns `0.8.6`.
- Redis returns `PONG`.
- `COMMAND INFO FT.SEARCH` is not empty.

## Lifecycle commands

```bash
docker compose stop
docker compose start
docker compose down
```

`docker compose down` removes containers and the network but preserves named volumes. The following
command also deletes all local lab database/cache data and is intentionally destructive:

```bash
docker compose down --volumes
```

Run it only when you explicitly want a clean database.

## Checkpoint

```bash
docker compose ps
uv run python -c "import psycopg; c=psycopg.connect('postgresql://policy_vault:policy_vault@localhost:5432/policy_vault'); print(c.execute('select 1').fetchone()); c.close()"
```

Expected Python output:

```text
(1,)
```

Commit:

```bash
git add compose.yaml .env.example
git commit -m "chore: add PostgreSQL pgvector and Redis services"
```

Continue with `04_FOUNDATION_CONFIG_DOMAIN_PORTS.md`.
