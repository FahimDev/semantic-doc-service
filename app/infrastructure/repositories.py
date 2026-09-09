"""Focused database access helpers used by application services."""

from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import select, func, delete, Select
from sqlalchemy.orm import Session

from app.domain.models import DocumentSnapshot, DocumentStatus
from app.infrastructure.orm import KnowledgeBaseRow, DocumentRow, ChunkRow

class DocumentRepository:
    """Repository for managing documents and their chunks.
    Data flow for this repository:
     KnowledgeBaseRow
       -> DocumentRow (filtered by knowledge_base_id, hash, status, etc.)
       -> ChunkRow count for each document
       -> DocumentSnapshot returned to the application layer    
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_active_by_hash(self, knowledge_base_id: UUID, sha256: str) -> DocumentSnapshot | None:
        """Find an active document by its SHA256 hash."""
        statement = self._snapshot_statement().where(
            DocumentRow.knowledge_base_id == knowledge_base_id,
            DocumentRow.sha256 == sha256, 
            DocumentRow.status != DocumentStatus.DELETED.value,
        )
        # Build the SQL statement first, then execute it once against the database.
        row = self.session.execute(statement).one_or_none()
        return self._to_snapshot(row) if row else None

    def get_snapshot(self, document_id: UUID) -> DocumentSnapshot | None:
        row = self.session.execute(
            self._snapshot_statement().where(DocumentRow.id == document_id)
        ).one_or_none()
        return self._to_snapshot(row) if row else None

    def get_row_for_update(self, document_id: UUID) -> DocumentRow | None:
        # Row lock prevents two deletion flows from changing the same document concurrently.
        # This forces the database to lock the selected row until the transaction ends,
        # so another worker cannot delete or update the same document at the same time.
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
        # This returns a reusable SELECT that fetches a document plus its chunk count.
        # The caller can add filters with .where(...), and SQLAlchemy will turn that
        # into a single SQL query before execution.
        #
        # A correlated scalar query avoids loading every ChunkRow just to count them.
        chunk_count = (
            select(func.count(ChunkRow.id))
            .where(ChunkRow.document_id == DocumentRow.id)
            # Link this subquery to the current outer DocumentRow so the chunk
            # count is calculated per document, not as a standalone query.
            .correlate(DocumentRow)
            # Convert the COUNT(*) SELECT into a single value that can be used
            # as a column in the outer query for each document row.
            .scalar_subquery()
        )
        return select(DocumentRow, chunk_count.label("chunk_count"))

    @staticmethod
    def _to_snapshot(row: Sequence[object]) -> DocumentSnapshot:
        # Convert the raw SQL row into the domain-level DocumentSnapshot object.
        # row[0] is the first selected column from the query: the DocumentRow.
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
            # row[1] is the chunk_count column from the SQL query; cast it to int
            # so the domain object gets a normal Python integer.
            chunk_count=cast(int, row[1]),
            created_at=document.created_at,
            deleted_at=document.deleted_at,
        )


class KnowledgeBaseRepository:
    """Repository for managing knowledge bases."""

    def __init__(self,session:Session)->None:
        self.session=session

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