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
    pages: tuple[ParsedPage, ...]
    metadata: dict[str, str] = field(default_factory=dict)



@dataclass(frozen=True, slots=True)
class TextChunk:
    page_number: int
    chunk_index: int
    char_start: int
    char_end: int
    content: str


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
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
    document: DocumentSnapshot
    deduplicated: bool

@dataclass(frozen=True, slots=True)
class DeleteResult:
    document_id: UUID
    status: DocumentStatus
    cleanup_pending: bool

@dataclass(frozen=True, slots=True)
class SearchHit:
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    content: str
    distance: float
    score: float

@dataclass(frozen=True, slots=True)
class AnswerSource:
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    excerpt: str
    score: float

@dataclass(frozen=True, slots=True)
class QuestionResult:
    answer: str
    sources: tuple[AnswerSource, ...]
    knowledge_base_version: int
    cache_hit: bool = False
    cache_distance: float | None = None