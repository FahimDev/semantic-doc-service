"""Capabilities required by use cases, expressed without vendor dependencies."""


from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.domain.models import ParsedDocument, SearchHit


class DocumentParser(Protocol):
    # Protocol gives us structural typing: any object with these methods works.
    # That keeps use cases decoupled from a specific base class or inheritance tree.
    name: str

    def supports(self, filename: str, content_type: str, data: bytes) -> bool: ...

    def parse(self, filename: str, content_type: str, data: bytes) -> ParsedDocument: ...

class Embedder(Protocol):
    # @property keeps the interface read-only while still looking like an attribute.
    # Sequence is used instead of list so callers can pass lists, tuples, or other ordered collections.
    @property
    def name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def warm_up(self) -> None: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

class FileStorage(Protocol):
    # root is exposed as a property because implementations usually compute or configure it once.
    @property
    def root(self) -> Path: ...

    def save(self, data: bytes, suffix: str) -> str: ...

    def delete(self, storage_key: str) -> None: ...

@dataclass(frozen=True, slots=True)
class CacheMatch:
    # A tiny immutable value object is ideal here because cache lookups should be cheap and predictable.
    payload_json: str
    distance: float


class SemanticCache(Protocol):
    # Sequence lets the cache accept any ordered embedding container, not just one concrete list type.
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
    # version is a property because it is metadata about the provider, not an action.
    @property
    def version(self) -> str: ...

    def answer(self, question: str, hits: Sequence[SearchHit]) -> str: ...

class ExternalVectorStore(Protocol):
    # This hook remains no-op while pgvector stores authoritative vectors.
    def delete_document(self, document_id: UUID) -> None: ...