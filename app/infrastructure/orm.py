"""ORM persistence rows. Domain dataclasses remain independent from these rows.
- knowledge_bases gives a cache-invalidating version boundary.
- documents owns identity, content hash, file key, and lifecycle.
- chunks co-locates text and vector with a foreign key.
- outbox_events durably describes work outside the DB transaction.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, String, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.constants import EMBEDDING_DIMENSIONS
from app.infrastructure.database import Base

class KnowledgeBaseRow(Base):
    """Knowledge base metadata row."""

    __tablename__ = "knowledge_bases"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    # Version is incremented whenever the knowledge base is updated, so clients can detect changes.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class DocumentRow(Base):
    """Document metadata row."""

    
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="READY")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_documents_knowledge_base_id", "knowledge_base_id"),
        Index("ix_documents_status", "status"),
    )


class ChunkRow(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    # Why this row exists:
    # - The application writes this record inside the same DB transaction as the
    #   main business change.
    # - That makes the event durable even if the process crashes right after commit.
    # - A separate worker can later read this row and perform side effects
    #   (cache invalidation, search indexing, notifications, sync jobs, etc.).
    # - This avoids the "save data succeeded, but the external action failed" problem.
    # - locked_at / locked_by / attempts / last_error help workers claim jobs safely,
    #   retry failures, and prevent multiple workers from processing the same event.
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
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



