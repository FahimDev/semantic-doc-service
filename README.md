# semantic-doc-service

A document search and Q&A backend: upload documents, embed them, store the vectors in PostgreSQL
(pgvector), and search by meaning. Redis is used as a disposable semantic cache.

> **Status:** the schema (Alembic), parsers, repositories and demo tooling work. The upload,
> search and ask flows and the FastAPI layer are still being built following `lecture/`.

## Setup

Requires Docker and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env               # local settings (already git-ignored)
uv sync                            # install Python dependencies
docker compose up -d               # PostgreSQL + pgvector, Redis, pgAdmin, RedisInsight
uv run alembic upgrade head        # create the tables and seed the default knowledge base
```

## Try it with demo data

```bash
uv run python -m scripts.seed_demo_data            # loads 3 demo docs, 24 chunks
uv run python -m scripts.visualize_vectors --query "how many vacation days do I get" --open
```

The first run downloads the embedding model (about 90 MB). The second command embeds your
question, has PostgreSQL rank the chunks by cosine distance, and opens an interactive map of all
the stored vectors with the top hits highlighted. The page is written to
`data/visualizations/vector_map.html`.

Useful variations:

```bash
uv run python -m scripts.visualize_vectors                      # map only, no query
uv run python -m scripts.visualize_vectors --top-k 10 --query "who do I tell about a phishing email"
uv run python -m scripts.visualize_vectors --projector          # also export TSVs for projector.tensorflow.org
uv run python -m scripts.seed_demo_data --reset                 # delete the demo docs and load them again
```

`--projector` writes `vectors.tsv` and `metadata.tsv` next to the map. Upload both at
<https://projector.tensorflow.org> to explore the raw 384 dimensions in 3D with UMAP or t-SNE.

## Web UIs

Both are bound to localhost only and need **no login**.

| Tool | URL | Notes |
|---|---|---|
| pgAdmin (PostgreSQL) | <http://localhost:5050> | The `policy-vault (local)` server is already registered. Open *Databases > policy_vault > Schemas > public > Tables*. Right-click the database and choose **ERD For Database** for a diagram. If it ever asks for a login: `admin@example.com` / `admin`. |
| RedisInsight (Redis) | <http://localhost:5540> | Accept the terms on first open, then `policy-vault (local)` appears automatically. If it does not, choose **Add Redis database** with host `redis`, port `6379`, and no username or password. |

The UIs run inside Docker, so they reach the databases by service name (`postgres`, `redis`), not
`localhost`. Use `localhost` only from tools on your own machine.

## Connection details

| Service | Host connection | Credentials |
|---|---|---|
| PostgreSQL 17 + pgvector | `localhost:5432`, database `policy_vault` | user `policy_vault`, password `policy_vault` |
| Redis 8 | `localhost:6379` | none |

```bash
docker compose exec postgres psql -U policy_vault -d policy_vault     # SQL shell
docker compose exec redis redis-cli                                   # Redis shell
```

## Tests and checks

```bash
uv run pytest                          # everything; integration tests need PostgreSQL running
uv run pytest -m "not integration"     # unit tests only, no Docker needed
uv run ruff check . && uv run ruff format --check app alembic tests scripts
uv run mypy app tests alembic scripts
```

Integration tests create a throwaway `policy_vault_test` database, so they never touch your
development data.

## Database migrations

```bash
uv run alembic upgrade head            # apply
uv run alembic downgrade base          # undo everything
uv run alembic check                   # fails if the ORM models and migrations disagree
```

To start over with an empty database: `docker compose down -v`, then `docker compose up -d` and
`uv run alembic upgrade head`. This deletes all stored data.
