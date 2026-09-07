"""Capabilities required by use cases, expressed without vendor dependencies."""


from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.domain.models import ParsedDocument, SearchHit


class DocumentParser(Protocol):
    name: str

    def supports(self, filename: str, content_type: str, data: bytes) -> bool: ...

    def parse(self, filename: str, content_type: str, data: bytes) -> ParsedDocument: ...

class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def warm_up(self) -> None: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

class FileStorage(Protocol):
    @property
    def root(self) -> Path: ...

    def save(self, data: bytes, suffix: str) -> str: ...

    def delete(self, storage_key: str) -> None: ...

@dataclass(frozen=True, slots=True)
class CacheMatch:
    payload_json: str
    distance: float


class SemanticCache(Protocol):
    def ensure_index(self) -> bool: ...

    def find(self, scope: str, query_embedding: Sequence[float]) -> CacheMatch | None: ...

    def put(
        self,
        scope: str,
        prompt: str,
        embedding: Sequence[float],
        payload_json: str,
    ) -> None: ...

    def ping(self) -> bool: ...


class AnswerProvider(Protocol):
    @property
    def version(self) -> str: ...

    def answer(self, question: str, hits: Sequence[SearchHit]) -> str: ...

class ExternalVectorStore(Protocol):
    # This hook remains no-op while pgvector stores authoritative vectors.
    def delete_document(self, document_id: UUID) -> None: ...