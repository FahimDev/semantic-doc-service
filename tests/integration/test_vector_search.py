import math

import pytest
from sqlalchemy.orm import Session

from app.core.constants import DEFAULT_KNOWLEDGE_BASE_ID
from app.infrastructure.orm import ChunkRow, DocumentRow
from scripts.visualize_vectors import load_chunks, nearest_chunks

pytestmark = pytest.mark.integration


def unit_vector(*components: float) -> list[float]:
    padded = [*components] + [0.0] * (384 - len(components))
    norm = math.sqrt(sum(value * value for value in padded))
    return [value / norm for value in padded]


def add_document(session: Session, name: str, status: str, vectors: list[list[float]]) -> None:
    document = DocumentRow(
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        filename=name,
        content_type="text/plain",
        storage_key=f"test/{name}",
        sha256=name.ljust(64, "0"),
        status=status,
        page_count=1,
    )
    document.chunks = [
        ChunkRow(
            page_number=1,
            chunk_index=index,
            char_start=0,
            char_end=1,
            content=f"{name} chunk {index}",
            embedding=vector,
        )
        for index, vector in enumerate(vectors)
    ]
    session.add(document)
    session.flush()


def test_nearest_chunks_rank_by_cosine_distance(session: Session) -> None:
    add_document(
        session,
        "near.txt",
        "READY",
        [unit_vector(1, 0), unit_vector(1, 1), unit_vector(0, 0, 1)],
    )

    hits = nearest_chunks(session, unit_vector(1, 0), k=3)

    assert [(name, index) for name, index, _ in hits] == [
        ("near.txt", 0),
        ("near.txt", 1),
        ("near.txt", 2),
    ]
    distances = [distance for _, _, distance in hits]
    assert distances == pytest.approx([0.0, 1 - math.sqrt(0.5), 1.0], abs=1e-5)


def test_search_and_map_ignore_deleted_documents(session: Session) -> None:
    add_document(session, "live.txt", "READY", [unit_vector(0, 1)])
    add_document(session, "gone.txt", "DELETED", [unit_vector(1, 0)])

    hits = nearest_chunks(session, unit_vector(1, 0), k=5)
    points = load_chunks(session)

    assert [name for name, _, _ in hits] == ["live.txt"]
    assert [point.filename for point in points] == ["live.txt"]


def test_loaded_embeddings_keep_their_dimensions(session: Session) -> None:
    add_document(session, "dims.txt", "READY", [unit_vector(1, 2, 3)])

    (point,) = load_chunks(session)

    assert point.embedding.shape == (384,)
    assert point.embedding.dtype.name == "float32"
