# 05 — SQLAlchemy Schema and Repositories

**Working directory:** `policy-vault/`  
**Build output:** Python mapping for authoritative relational/vector state  
**Database tables are created in Chapter 06, not by `create_all()`.**

## 1. Engine and session factory

**File:** `policy-vault/app/infrastructure/database.py`

```python
"""PostgreSQL engine and transaction/session construction."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """All ORM tables inherit one metadata registry."""


def build_engine(database_url: str) -> Engine:
    # pool_pre_ping replaces dead pooled connections before a request uses one.
    return create_engine(database_url, pool_pre_ping=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False lets services return already-loaded values safely.
    return sessionmaker(bind=engine, expire_on_commit=False)
```

Theory: a SQLAlchemy `Session` is a unit-of-work boundary and identity map. It is not a global
connection. Create a short-lived session per use case and define transaction scope explicitly.

## 2. ORM tables

**File:** `policy-vault/app/infrastructure/orm.py`

```python
"""ORM persistence rows. Domain dataclasses remain independent from these rows."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import EMBEDDING_DIMENSIONS
from app.infrastructure.database import Base


class KnowledgeBaseRow(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    # Version is incremented whenever searchable knowledge changes.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_bases.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    # SHA-256 makes client retries idempotent and detects identical bytes.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # JSONB holds parser/embedding recipe metadata, not core relational identity.
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chunks: Mapped[list["ChunkRow"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_knowledge_base_id", "knowledge_base_id"),
        Index("ix_documents_status", "status"),
    )


class ChunkRow(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Page and character positions support citations back to source text.
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # vector(384) is a database invariant; mismatched inserts fail.
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[DocumentRow] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_chunk_index"),
        Index("ix_chunks_document_id", "document_id"),
    )


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_outbox_pending", "processed_at", "locked_at", "created_at"),)
```

### Why four tables?

- `knowledge_bases` gives a cache-invalidating version boundary.
- `documents` owns identity, content hash, file key, and lifecycle.
- `chunks` co-locates text and vector with a foreign key.
- `outbox_events` durably describes work outside the DB transaction.

Do not store one giant document vector. Searchable meaning normally lives in smaller passages.

## 3. Repositories

Repositories centralize reusable persistence queries and conversion from ORM rows to immutable
domain snapshots. They do not open or commit transactions; the service owns that boundary.

**File:** `policy-vault/app/infrastructure/repositories.py`

```python
"""Focused database access helpers used by application services."""

from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.domain.models import DocumentSnapshot, DocumentStatus
from app.infrastructure.orm import ChunkRow, DocumentRow, KnowledgeBaseRow


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_active_by_sha(self, knowledge_base_id: UUID, sha256: str) -> DocumentSnapshot | None:
        statement = self._snapshot_statement().where(
            DocumentRow.knowledge_base_id == knowledge_base_id,
            DocumentRow.sha256 == sha256,
            DocumentRow.status != DocumentStatus.DELETED.value,
        )
        row = self.session.execute(statement).one_or_none()
        return self._to_snapshot(row) if row else None

    def get_snapshot(self, document_id: UUID) -> DocumentSnapshot | None:
        row = self.session.execute(
            self._snapshot_statement().where(DocumentRow.id == document_id)
        ).one_or_none()
        return self._to_snapshot(row) if row else None

    def get_row_for_update(self, document_id: UUID) -> DocumentRow | None:
        # Row lock prevents two deletion flows from changing the same document concurrently.
        return self.session.scalar(
            select(DocumentRow).where(DocumentRow.id == document_id).with_for_update()
        )

    def list_active(self, knowledge_base_id: UUID) -> list[DocumentSnapshot]:
        rows = self.session.execute(
            self._snapshot_statement()
            .where(
                DocumentRow.knowledge_base_id == knowledge_base_id,
                DocumentRow.status != DocumentStatus.DELETED.value,
            )
            .order_by(DocumentRow.created_at.desc())
        ).all()
        return [self._to_snapshot(row) for row in rows]

    @staticmethod
    def _snapshot_statement() -> Select[tuple[DocumentRow, int]]:
        # A correlated scalar query avoids loading every ChunkRow just to count them.
        chunk_count = (
            select(func.count(ChunkRow.id))
            .where(ChunkRow.document_id == DocumentRow.id)
            .correlate(DocumentRow)
            .scalar_subquery()
        )
        return select(DocumentRow, chunk_count.label("chunk_count"))

    @staticmethod
    def _to_snapshot(row: Sequence[object]) -> DocumentSnapshot:
        document = row[0]
        if not isinstance(document, DocumentRow):
            raise TypeError("Expected DocumentRow")
        return DocumentSnapshot(
            id=document.id,
            filename=document.filename,
            content_type=document.content_type,
            sha256=document.sha256,
            status=DocumentStatus(document.status),
            page_count=document.page_count,
            chunk_count=cast(int, row[1]),
            created_at=document.created_at,
            deleted_at=document.deleted_at,
        )


class KnowledgeBaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_version(self, knowledge_base_id: UUID) -> int:
        version = self.session.scalar(
            select(KnowledgeBaseRow.version).where(KnowledgeBaseRow.id == knowledge_base_id)
        )
        if version is None:
            raise LookupError(f"Unknown knowledge base {knowledge_base_id}")
        return version

    def bump_version(self, knowledge_base_id: UUID) -> int:
        # Locking prevents lost increments from concurrent upload/delete transactions.
        knowledge_base = self.session.scalar(
            select(KnowledgeBaseRow)
            .where(KnowledgeBaseRow.id == knowledge_base_id)
            .with_for_update()
        )
        if knowledge_base is None:
            raise LookupError(f"Unknown knowledge base {knowledge_base_id}")
        knowledge_base.version += 1
        self.session.flush()
        return knowledge_base.version
```

## Checkpoint

```bash
uv run python -c "from app.infrastructure.orm import Base; print(sorted(Base.metadata.tables))"
uv run ruff check app
uv run mypy app
```

Expected table names:

```text
['chunks', 'documents', 'knowledge_bases', 'outbox_events']
```

Commit:

```bash
git add app/infrastructure
git commit -m "feat: model PostgreSQL and pgvector state"
```

Continue with `06_ALEMBIC_MIGRATION.md`.

