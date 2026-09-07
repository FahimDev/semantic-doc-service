# 06 — Alembic Migration and Schema Inspection

**Working directory:** `policy-vault/`  
**Prerequisite:** PostgreSQL container is healthy  
**Build output:** a reproducible physical schema

## Why not `Base.metadata.create_all()`?

`create_all()` can create a current schema, but it does not record an ordered history of changes.
Alembic migrations are reviewable, repeatable, deployable, and reversible. Schema is source code.

## 1. Initialize Alembic

```bash
uv run alembic init alembic
```

In `alembic.ini`, confirm these two values exist:

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
```

The generated `sqlalchemy.url` value is irrelevant because `env.py` will replace it from Pydantic
settings.

## 2. Connect Alembic to settings and ORM metadata

**File:** `policy-vault/alembic/env.py`  
Replace the generated content completely:

```python
"""Alembic runtime: uses the same validated URL and ORM metadata as the app."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.infrastructure import orm  # noqa: F401 -- importing registers mapped tables
from app.infrastructure.database import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

## 3. Create the first revision

Delete any placeholder file inside `alembic/versions/`, then create this exact file.

**File:** `policy-vault/alembic/versions/0001_initial.py`

```python
"""Create authoritative document, vector, version, and outbox state."""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_KB_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # The extension must exist before PostgreSQL can understand vector(384).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_bases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "knowledge_base_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_knowledge_base_id", "documents", ["knowledge_base_id"])
    op.create_index("ix_documents_status", "documents", ["status"])
    # Partial uniqueness permits the same bytes only after the old record is fully DELETED.
    op.execute(
        "CREATE UNIQUE INDEX uq_documents_active_sha "
        "ON documents (knowledge_base_id, sha256) WHERE status <> 'DELETED'"
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_chunks_document_chunk_index"
        ),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(100), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_outbox_pending", "outbox_events", ["processed_at", "locked_at", "created_at"]
    )

    # Seed a single local knowledge base so early API requests need no administration endpoint.
    op.execute(
        sa.text(
            "INSERT INTO knowledge_bases (id, name, version) "
            "VALUES (:id, 'default', 1)"
        ).bindparams(id=DEFAULT_KB_ID)
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
    # Appropriate for this isolated lab DB; shared production DBs need a separate decision.
    op.execute("DROP EXTENSION IF EXISTS vector")
```

## 4. Validate before applying

```bash
uv run ruff check alembic
uv run alembic upgrade head --sql
```

The `--sql` command renders SQL without changing the database. Read it. Confirm that
`CREATE EXTENSION` appears before `VECTOR(384)`.

## 5. Apply and inspect

```bash
uv run alembic upgrade head
uv run alembic current
```

Inspect tables and indexes:

```bash
docker compose exec postgres psql -U policy_vault -d policy_vault -c "\dt"
docker compose exec postgres psql -U policy_vault -d policy_vault -c "\d chunks"
docker compose exec postgres psql -U policy_vault -d policy_vault -c "\di"
```

Notice: there is **no ANN index yet**. Exact vector search is the correct baseline.

Commit:

```bash
git add alembic alembic.ini
git commit -m "feat: add initial pgvector migration"
```

Continue with `07_DOCUMENT_PARSERS_PDF.md`.
