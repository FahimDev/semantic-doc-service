from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import DEFAULT_KNOWLEDGE_BASE_ID
from app.domain.models import DocumentStatus
from app.infrastructure.orm import ChunkRow, DocumentRow
from app.infrastructure.repositories import DocumentRepository, KnowledgeBaseRepository

pytestmark = pytest.mark.integration

VECTOR = [0.1] * 384


def make_document(sha: str = "a" * 64, status: str = "READY", chunks: int = 0) -> DocumentRow:
    document = DocumentRow(
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        filename="handbook.txt",
        content_type="text/plain",
        storage_key=f"key-{uuid4()}",
        sha256=sha,
        status=status,
        page_count=1,
    )
    document.chunks = [
        ChunkRow(
            page_number=1,
            chunk_index=index,
            char_start=index * 10,
            char_end=index * 10 + 10,
            content=f"chunk {index}",
            embedding=VECTOR,
        )
        for index in range(chunks)
    ]
    return document


def test_snapshot_counts_chunks(session: Session) -> None:
    document = make_document(chunks=3)
    session.add(document)
    session.flush()

    snapshot = DocumentRepository(session).get_snapshot(document.id)

    assert snapshot is not None
    assert snapshot.chunk_count == 3
    assert snapshot.status is DocumentStatus.READY
    assert snapshot.filename == "handbook.txt"


def test_metadata_and_updated_at_defaults(session: Session) -> None:
    document = make_document()
    session.add(document)
    session.flush()
    session.refresh(document)

    assert document.metadata_json == {}
    assert document.updated_at is not None


def test_find_active_by_hash_ignores_deleted(session: Session) -> None:
    repository = DocumentRepository(session)
    deleted = make_document(sha="b" * 64, status="DELETED")
    session.add(deleted)
    session.flush()

    assert repository.find_active_by_hash(DEFAULT_KNOWLEDGE_BASE_ID, "b" * 64) is None

    active = make_document(sha="b" * 64)
    session.add(active)
    session.flush()

    found = repository.find_active_by_hash(DEFAULT_KNOWLEDGE_BASE_ID, "b" * 64)
    assert found is not None
    assert found.id == active.id


def test_list_active_excludes_deleted_and_orders_newest_first(session: Session) -> None:
    session.add_all(
        [
            make_document(sha="c" * 64),
            make_document(sha="d" * 64, status="DELETED"),
            make_document(sha="e" * 64),
        ]
    )
    session.flush()

    listed = DocumentRepository(session).list_active(DEFAULT_KNOWLEDGE_BASE_ID)

    assert {s.sha256 for s in listed} == {"c" * 64, "e" * 64}


def test_duplicate_active_hash_is_rejected_by_database(session: Session) -> None:
    session.add(make_document(sha="f" * 64))
    session.flush()
    session.add(make_document(sha="f" * 64))

    with pytest.raises(IntegrityError, match="uq_documents_active_sha"):
        session.flush()


def test_deleting_document_cascades_to_chunks(session: Session) -> None:
    document = make_document(sha="1" * 64, chunks=2)
    session.add(document)
    session.flush()
    document_id = document.id

    session.delete(document)
    session.flush()

    assert session.scalars(select(ChunkRow).where(ChunkRow.document_id == document_id)).all() == []


def test_get_row_for_update_returns_row(session: Session) -> None:
    document = make_document(sha="2" * 64)
    session.add(document)
    session.flush()

    row = DocumentRepository(session).get_row_for_update(document.id)

    assert row is not None
    assert row.id == document.id
    assert DocumentRepository(session).get_row_for_update(uuid4()) is None


def test_knowledge_base_version_bumps(session: Session) -> None:
    repository = KnowledgeBaseRepository(session)
    before = repository.get_version(DEFAULT_KNOWLEDGE_BASE_ID)

    after = repository.bump_version(DEFAULT_KNOWLEDGE_BASE_ID)

    assert after == before + 1
    assert repository.get_version(DEFAULT_KNOWLEDGE_BASE_ID) == after


def test_unknown_knowledge_base_raises(session: Session) -> None:
    with pytest.raises(LookupError):
        KnowledgeBaseRepository(session).get_version(uuid4())
