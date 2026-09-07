# 04 — Foundation: Configuration, Domain Values, and Ports

**Working directory:** `policy-vault/`  
**Build output:** framework-independent concepts and validated settings

## 1. Constants

**File:** `policy-vault/app/core/constants.py`

```python
"""Schema-level constants shared across layers.

Embedding dimensions are not a casual runtime option: PostgreSQL declares vector(384),
Redis declares DIM=384, and the model must emit 384 values.
"""

from uuid import UUID

DEFAULT_KNOWLEDGE_BASE_ID = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".pdf"})
```

## 2. Pydantic settings

Pydantic serves two different boundaries in this project:

- `BaseSettings` validates environment configuration at startup.
- `BaseModel` later validates HTTP request and response shapes.

Pydantic does not replace domain models or database rows. Each has a different responsibility.

**File:** `policy-vault/app/core/config.py`

```python
"""Typed configuration loaded from .env and process environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import DEFAULT_EMBEDDING_MODEL, EMBEDDING_DIMENSIONS


class Settings(BaseSettings):
    # Environment variables override .env; unknown keys are ignored for easy deployment.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+psycopg://policy_vault:policy_vault@localhost:5432/policy_vault"
    )
    redis_url: str = "redis://localhost:6379/0"
    upload_dir: Path = Path("data/uploads")

    # Field constraints reject unsafe or nonsensical runtime values immediately.
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=100, gt=0, le=1000)
    chunk_size: int = Field(default=800, ge=100)
    chunk_overlap: int = Field(default=120, ge=0)

    embedding_provider: str = "sentence-transformer"
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = EMBEDDING_DIMENSIONS
    warm_embedding_model: bool = True

    semantic_cache_enabled: bool = True
    semantic_cache_ttl_seconds: int = Field(default=3600, gt=0)
    semantic_cache_distance_threshold: float = Field(default=0.12, ge=0, le=2)
    redis_cache_index: str = "idx:semantic-cache"
    redis_cache_prefix: str = "semantic-cache:"

    outbox_poll_seconds: float = Field(default=2.0, gt=0)
    outbox_lease_seconds: int = Field(default=60, gt=0)

    @model_validator(mode="after")
    def validate_cross_field_invariants(self) -> "Settings":
        # Overlap must advance; otherwise a chunk loop can never terminate.
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        # Changing dimensions requires a PostgreSQL migration and Redis index rebuild.
        if self.embedding_dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError("change vector schema before changing embedding dimensions")
        return self


@lru_cache
def get_settings() -> Settings:
    # One validated settings object is reused throughout this process.
    return Settings()
```

Test configuration now:

```bash
uv run python -c "from app.core.config import get_settings; print(get_settings().model_dump())"
```

Change `CHUNK_OVERLAP=900` temporarily in `.env` and repeat. Read the validation error, then restore
the correct value. This is fail-fast configuration.

## 3. Expected application errors

**File:** `policy-vault/app/core/errors.py`

```python
"""Errors the HTTP layer can translate into stable client responses."""


class PolicyVaultError(Exception):
    """Base type for expected use-case failures."""


class NotFoundError(PolicyVaultError):
    pass


class UnsupportedDocumentError(PolicyVaultError):
    pass


class InvalidDocumentError(PolicyVaultError):
    pass


class OCRRequiredError(InvalidDocumentError):
    """The PDF is valid but has no usable text layer."""


class UploadTooLargeError(InvalidDocumentError):
    pass


class EmbeddingConfigurationError(PolicyVaultError):
    pass
```

## 4. Domain values

These dataclasses do not import FastAPI, Pydantic, SQLAlchemy, Redis, or pypdf. That is the test:
the domain vocabulary remains independent of technical adapters.

**File:** `policy-vault/app/domain/models.py`

```python
"""Small immutable values passed between application and infrastructure layers."""

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
    COSINE = "cosine"
    L2 = "l2"
    INNER_PRODUCT = "inner_product"


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    pages: tuple[ParsedPage, ...]
    metadata: dict[str, object] = field(default_factory=dict)


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
```

## 5. Dependency-inversion ports

A `Protocol` defines behavior without owning an implementation. Application code will accept
these capabilities through constructors. Tests can supply fakes; production supplies adapters.

**File:** `policy-vault/app/application/ports.py`

```python
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
```

## Checkpoint

```bash
uv run ruff check app
uv run mypy app/core app/domain app/application/ports.py
```

Commit:

```bash
git add app
git commit -m "feat: define settings domain values and dependency ports"
```

Continue with `05_SQLALCHEMY_SCHEMA_REPOSITORIES.md`.
