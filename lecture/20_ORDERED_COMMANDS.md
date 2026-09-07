# 20 — Ordered Command Cheat Sheet

This is the POSIX command sequence from an empty parent directory. It is a checklist, not a
replacement for the explanations and file contents in Chapters 01–19. PowerShell equivalents for
file operations appear where they are first introduced.

Every Python package and command goes through `uv`; there is no `pip install` or manual virtual
environment activation.

## A. Preflight and project creation

```bash
git --version
docker --version
docker compose version
uv --version
uv python install 3.12

uv init --app --python 3.12 policy-vault
cd policy-vault
rm main.py
```

## B. Resolve all dependencies

```bash
uv add fastapi "uvicorn[standard]" pydantic pydantic-settings python-multipart
uv add sqlalchemy "psycopg[binary]" pgvector alembic
uv add numpy sentence-transformers pypdf redis
uv add --dev pytest pytest-cov httpx ruff mypy reportlab

uv tree
uv lock --check
uv run python --version
```

## C. Create directories and empty package markers

```bash
mkdir -p app/api app/application app/core app/domain app/infrastructure
mkdir -p scripts tests/unit tests/integration sample_data .github/workflows
touch app/__init__.py app/api/__init__.py app/application/__init__.py
touch app/core/__init__.py app/domain/__init__.py app/infrastructure/__init__.py
touch scripts/__init__.py tests/__init__.py
```

Now create `pyproject.toml` additions and `.gitignore` from Chapter 02, then `compose.yaml` and
`.env.example` from Chapter 03.

```bash
cp .env.example .env
docker compose config
docker compose up -d
docker compose ps
docker compose exec postgres psql -U policy_vault -d policy_vault -c "SELECT version();"
docker compose exec postgres psql -U policy_vault -d policy_vault -c \
  "SELECT default_version FROM pg_available_extensions WHERE name = 'vector';"
docker compose exec redis redis-cli PING
docker compose exec redis redis-cli COMMAND INFO FT.SEARCH
```

## D. Build the foundation and migration

Create the Chapter 04 and Chapter 05 files in this order:

```text
app/core/constants.py
app/core/config.py
app/core/errors.py
app/domain/models.py
app/application/ports.py
app/infrastructure/database.py
app/infrastructure/orm.py
app/infrastructure/repositories.py
```

Then run:

```bash
uv run ruff format app
uv run ruff check app
uv run mypy app
uv run python -c "from app.infrastructure.orm import Base; print(sorted(Base.metadata.tables))"

uv run alembic init alembic
```

Replace `alembic/env.py`, create `alembic/versions/0001_initial.py`, and confirm `alembic.ini` as
shown in Chapter 06. Then:

```bash
uv run ruff format alembic
uv run ruff check alembic
uv run alembic upgrade head --sql
uv run alembic upgrade head
uv run alembic current
docker compose exec postgres psql -U policy_vault -d policy_vault -c "\dt"
docker compose exec postgres psql -U policy_vault -d policy_vault -c "\d chunks"
```

## E. Build ingestion and exact retrieval

Create these files from Chapters 07–10:

```text
app/infrastructure/parsers.py
sample_data/handbook.txt
app/infrastructure/chunking.py
app/infrastructure/embedding.py
app/infrastructure/storage.py
app/application/document_service.py
scripts/metric_playground.py
app/application/search_service.py
```

Run each layer before moving on:

```bash
uv run ruff format app scripts
uv run ruff check app scripts
uv run mypy app scripts
uv run python -m scripts.metric_playground
uv run python -c "from pathlib import Path; from app.infrastructure.parsers import Utf8TextParser; from app.infrastructure.chunking import TextChunker; from app.infrastructure.embedding import HashingEmbedder; p=Path('sample_data/handbook.txt'); d=Utf8TextParser().parse(p.name,'text/plain',p.read_bytes()); c=TextChunker(200,30).split(d); print(len(c),len(HashingEmbedder().embed_query(c[0].content)))"
```

## F. Add ANN, deletion, cache, and answer flow

Create or edit these files in order from Chapters 11–14:

```text
scripts/manage_chunk_index.py
app/application/document_service.py       # add delete method/imports
app/application/outbox_service.py
scripts/process_outbox.py
app/infrastructure/cache.py
app/application/question_service.py
```

Validate:

```bash
uv run ruff format app scripts
uv run ruff check app scripts
uv run mypy app scripts

uv run python -m scripts.manage_chunk_index exact --metric cosine
uv run python -m scripts.manage_chunk_index hnsw --metric cosine \
  --m 16 --ef-construction 64
docker compose exec postgres psql -U policy_vault -d policy_vault -c \
  "\di ix_chunks_embedding*"
uv run python -m scripts.manage_chunk_index exact --metric cosine
```

## G. Assemble and run FastAPI

Create the Chapter 15 files:

```text
app/infrastructure/container.py
app/api/schemas.py
app/api/routes.py
app/main.py
```

For the first smoke test, edit `.env` to use:

```dotenv
EMBEDDING_PROVIDER=hashing
WARM_EMBEDDING_MODEL=false
```

Terminal A:

```bash
uv run uvicorn app.main:app --reload
```

Terminal B:

```bash
uv run python -m scripts.process_outbox
```

Terminal C:

```bash
curl -f http://127.0.0.1:8000/health/live
curl -f http://127.0.0.1:8000/health/ready
curl -sS -F "file=@sample_data/handbook.txt;type=text/plain" \
  http://127.0.0.1:8000/api/v1/documents
curl -sS http://127.0.0.1:8000/api/v1/documents
curl -sS --get --data-urlencode "query=What is the learning budget?" \
  --data "metric=cosine" --data "limit=3" \
  http://127.0.0.1:8000/api/v1/search
curl -sS -H "Content-Type: application/json" \
  -d '{"question":"What is the learning budget?","limit":3}' \
  http://127.0.0.1:8000/api/v1/ask
curl -sS -H "Content-Type: application/json" \
  -d '{"question":"What is the learning budget?","limit":3}' \
  http://127.0.0.1:8000/api/v1/ask
```

To upload your own text-layer PDF:

```bash
curl -sS -F "file=@/absolute/path/to/document.pdf;type=application/pdf" \
  http://127.0.0.1:8000/api/v1/documents
```

Copy a real UUID from the document response; never run the placeholder unchanged:

```bash
export DOCUMENT_ID="paste-document-uuid-here"
curl -sS -X DELETE "http://127.0.0.1:8000/api/v1/documents/${DOCUMENT_ID}"
curl -sS "http://127.0.0.1:8000/api/v1/documents/${DOCUMENT_ID}"
```

If the continuous worker is not running, process exactly one pending event:

```bash
uv run python -m scripts.process_outbox --once
```

## H. Add and run tests

Create all Chapter 16 test and CI files, then:

```bash
uv run ruff format app scripts tests alembic
uv run ruff format --check app scripts tests alembic
uv run ruff check app scripts tests alembic
uv run mypy app scripts
uv run pytest tests/unit --cov=app --cov-report=term-missing

RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -vv
uv lock --check
```

## I. Run the index benchmark

Create `scripts/benchmark_indexes.py` from Chapter 17, then:

```bash
mkdir -p benchmark-results
uv run ruff format scripts/benchmark_indexes.py
uv run ruff check scripts/benchmark_indexes.py
uv run python -m scripts.benchmark_indexes \
  --rows 1000 --dimensions 384 --queries 20 --k 10 --lists 20
uv run python -m scripts.benchmark_indexes \
  --rows 10000 --dimensions 384 --queries 30 --k 10 --lists 100 \
  | tee benchmark-results/10k.txt
docker compose exec postgres psql -U policy_vault -d policy_vault -c \
  "DROP TABLE IF EXISTS ann_benchmark;"
```

## J. Switch to genuine semantic embeddings

Stop API and worker, edit `.env`:

```dotenv
EMBEDDING_PROVIDER=sentence-transformer
WARM_EMBEDDING_MODEL=true
```

Hashing vectors and model vectors must not coexist. For this disposable lab only, reset volumes,
then recreate schema and content:

```bash
docker compose down --volumes
docker compose up -d
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Repeat upload, search, and paraphrased `/ask` calls. Record cache distance and retrieval quality.

## K. Final reproducibility and shutdown

```bash
uv lock --check
uv sync --locked
uv run ruff format --check app scripts tests alembic
uv run ruff check app scripts tests alembic
uv run mypy app scripts
uv run pytest
git status --short
docker compose stop
```

Commit `pyproject.toml`, `uv.lock`, `.python-version`, migrations, source, and tests. Do not commit
`.env`, `.venv`, uploaded bytes, cache data, or benchmark output.

Continue with `21_REFERENCES_AND_MASTERY.md`.
