"Small immutable values passed between application and infrastructure layers."

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class DocumentStatus(StrEnum):
    READY = "READY"
    DELETING = "DELETING"
    DELETED = "DELETED"
    FAILED = "FAILED"

class DistanceMetric(StrEnum):
    """Distance metric for vector similarity search."""

    COSINE = "cosine"
    L2 = "l2"
    INNER_PRODUCT = "inner_product"

@dataclass(frozen=True, slots=True)
class ParsedPage:
    """Parsed page of a document."""

    page_number: int
    text: str

@dataclass(frozen=True, slots=True)
class ParsedDocument:
    # dataclass removes boilerplate, frozen makes the model safe to share, and slots keeps it lean.
    pages: tuple[ParsedPage, ...]
    metadata: dict[str, str] = field(default_factory=dict)



@dataclass(frozen=True, slots=True)
class TextChunk:
    # Chunk metadata must stay stable because later stages use these offsets to reconstruct provenance.
    page_number: int
    chunk_index: int
    char_start: int
    char_end: int
    content: str


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    # This snapshot is passed around read-only so different layers cannot accidentally desynchronize state.
    id: UUID
    filename: str
    content_type: str
    sha256: str
    status: DocumentStatus
    page_count: int
    chunk_count: int
    created_at: datetime
    deleted_at: datetime | None

@dataclass(frozen=True, slots=True)
class UploadResult:
    # Small result objects make use-case responses explicit instead of returning loose tuples or dicts.
    document: DocumentSnapshot
    deduplicated: bool

@dataclass(frozen=True, slots=True)
class DeleteResult:
    # Immutable results make deletion state easy to reason about in async workflows.
    document_id: UUID
    status: DocumentStatus
    cleanup_pending: bool

@dataclass(frozen=True, slots=True)
class SearchHit:
    # Search results are plain data, so dataclass keeps the representation simple and test-friendly.
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    content: str
    distance: float
    score: float

@dataclass(frozen=True, slots=True)
class AnswerSource:
    # The answer assembler needs lightweight source metadata, not behavior.
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    excerpt: str
    score: float

@dataclass(frozen=True, slots=True)
class QuestionResult:
    # This aggregates the final answer plus traceability metadata for the caller.
    answer: str
    sources: tuple[AnswerSource, ...]
    knowledge_base_version: int
    cache_hit: bool = False
    cache_distance: float | None = None