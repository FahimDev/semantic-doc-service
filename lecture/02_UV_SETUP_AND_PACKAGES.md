# 02 — uv Setup, Dependencies, and Directories

**Working directory:** the parent folder where you keep projects  
**Build output:** `policy-vault/` with a locked Python environment  
**Package manager:** `uv` only

## 1. Install and verify uv

Use the official installer for your operating system.

Linux/macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Open a new terminal, then verify:

```bash
uv --version
uv python install 3.12
```

Theory: `uv` manages the Python version, `.venv`, dependency resolution, `pyproject.toml`, and
`uv.lock`. `uv run` first ensures that the environment matches the lock file, then runs the
command inside that environment.

## 2. Initialize the application

```bash
uv init --app --python 3.12 policy-vault
cd policy-vault
```

Delete the generated `main.py`; the real entry point will be `app/main.py`.

Linux/macOS:

```bash
rm main.py
```

Windows PowerShell:

```powershell
Remove-Item main.py
```

## 3. Add runtime packages in meaningful groups

Run these commands exactly from `policy-vault/`:

```bash
uv add fastapi "uvicorn[standard]" pydantic pydantic-settings python-multipart
uv add sqlalchemy "psycopg[binary]" pgvector alembic
uv add numpy sentence-transformers pypdf redis
```

Why each direct dependency exists:

| Package | Purpose | Theory to remember |
|---|---|---|
| `fastapi` | HTTP routes, dependency injection, OpenAPI | Transport layer, not business logic |
| `uvicorn[standard]` | ASGI application server | Runs FastAPI; extras improve production behavior |
| `pydantic` | Request/response validation and serialization | Converts untrusted boundary data into typed values |
| `pydantic-settings` | Typed environment configuration | Fails early if config is invalid |
| `python-multipart` | Parses `multipart/form-data` uploads | Required by FastAPI’s `UploadFile` |
| `sqlalchemy` | SQL construction, ORM, transactions | Unit-of-work and DB abstraction; SQL knowledge still matters |
| `psycopg[binary]` | PostgreSQL driver | Carries SQLAlchemy traffic to PostgreSQL |
| `pgvector` | Python/SQLAlchemy vector type and operators | Does not generate embeddings; it stores/searches them |
| `alembic` | Versioned schema migrations | Schema changes are code and must be repeatable |
| `numpy` | Float32 vector representation and metric experiments | Controls shape, dtype, normalization |
| `sentence-transformers` | Local text embedding model | Maps text to semantically meaningful vectors |
| `pypdf` | Extracts an existing PDF text layer | It is not OCR software |
| `redis` | Redis client and Search commands | Redis is the disposable semantic-cache store |

Why explicitly add `pydantic` when FastAPI also depends on it? Your code imports Pydantic directly,
so it is a first-class dependency. Depending on an indirect/transitive installation is fragile.

## 4. Add development packages

```bash
uv add --dev pytest pytest-cov httpx ruff mypy reportlab
```

| Development package | Purpose |
|---|---|
| `pytest` | Test runner |
| `pytest-cov` | Coverage measurement |
| `httpx` | FastAPI test client dependency and optional API calls |
| `ruff` | Fast linter and formatter |
| `mypy` | Static type checking |
| `reportlab` | Generates a real text-layer PDF during tests |

`reportlab` is a test/development dependency because the API reads PDFs but does not generate them.

## 5. Create the directory skeleton

Linux/macOS:

```bash
mkdir -p app/api app/application app/core app/domain app/infrastructure
mkdir -p scripts tests/unit tests/integration sample_data
touch app/__init__.py app/api/__init__.py app/application/__init__.py
touch app/core/__init__.py app/domain/__init__.py app/infrastructure/__init__.py
touch scripts/__init__.py tests/__init__.py
```

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force app/api,app/application,app/core,app/domain,app/infrastructure
New-Item -ItemType Directory -Force scripts,tests/unit,tests/integration,sample_data
New-Item -ItemType File -Force app/__init__.py,app/api/__init__.py,app/application/__init__.py
New-Item -ItemType File -Force app/core/__init__.py,app/domain/__init__.py
New-Item -ItemType File -Force app/infrastructure/__init__.py,scripts/__init__.py,tests/__init__.py
```

## 6. Configure quality tools

**File:** `policy-vault/pyproject.toml`  
Keep the project and dependency sections created by `uv`. Add these sections at the bottom:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers"
markers = ["integration: requires PostgreSQL/pgvector and Redis"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]

[tool.mypy]
python_version = "3.12"
check_untyped_defs = true
no_implicit_optional = true
warn_unused_ignores = true

[[tool.mypy.overrides]]
module = ["reportlab.*", "sentence_transformers.*"]
ignore_missing_imports = true
```

## 7. Ignore generated and secret files

**File:** `policy-vault/.gitignore`

```gitignore
.env
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/
data/uploads/
benchmark-results/
```

## 8. Understand uv’s files

- `pyproject.toml`: human-edited project intent and dependency ranges.
- `uv.lock`: exact resolved dependency graph; commit it.
- `.venv/`: machine-local environment; never commit it.
- `.python-version`: requested Python version; commit it.

Useful commands:

```bash
uv tree
uv lock --check
uv sync
uv run python --version
```

Do not use `pip install` in this project. Do not manually activate `.venv` for tutorial commands;
use `uv run` so the execution path is explicit and reproducible.

## Checkpoint

```bash
uv lock --check
uv run python -c "import fastapi, pydantic, sqlalchemy, redis, pypdf, pgvector; print('dependencies ok')"
```

Expected final line:

```text
dependencies ok
```

Commit:

```bash
git add .
git commit -m "chore: initialize uv project and dependencies"
```

Continue with `03_DOCKER_POSTGRES_REDIS.md`.

