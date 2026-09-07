# 15 — FastAPI Assembly, Dependency Injection, and Lifespan

**Working directory:** `policy-vault/`  
**Build output:** a runnable HTTP API and outbox worker

This chapter is deliberately late. FastAPI is now a thin transport layer around use cases you
already understand and can test without HTTP.

## 1. Build the composition root

A composition root is the one place allowed to know concrete implementations. It wires ports to
adapters, owns process-lifetime resources, and keeps construction code out of routes.

**File:** `policy-vault/app/infrastructure/container.py`

```python
"""Application composition root: construct concrete adapters once per process."""

import os
import socket
from functools import lru_cache

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.application.document_service import DocumentService
from app.application.outbox_service import NoOpExternalVectorStore, OutboxService
from app.application.ports import Embedder, SemanticCache
from app.application.question_service import ExtractiveAnswerProvider, QuestionService
from app.application.search_service import SearchService
from app.core.config import Settings, get_settings
from app.infrastructure.cache import NullSemanticCache, RedisSemanticCache
from app.infrastructure.chunking import TextChunker
from app.infrastructure.database import build_engine, build_session_factory
from app.infrastructure.embedding import HashingEmbedder, SentenceTransformerEmbedder
from app.infrastructure.parsers import ParserRegistry, PdfTextParser, Utf8TextParser
from app.infrastructure.storage import LocalFileStorage


class Container:
    """Long-lived resources plus factories for application use cases."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine: Engine = build_engine(settings.database_url)
        self.session_factory: sessionmaker[Session] = build_session_factory(self.engine)
        self.storage = LocalFileStorage(settings.upload_dir)
        self.embedder = self._build_embedder(settings)
        self.semantic_cache = self._build_cache(settings)

        parser_registry = ParserRegistry(
            (Utf8TextParser(), PdfTextParser(max_pages=settings.max_pdf_pages))
        )
        chunker = TextChunker(settings.chunk_size, settings.chunk_overlap)

        self.document_service = DocumentService(
            self.session_factory,
            parser_registry,
            chunker,
            self.embedder,
            self.storage,
            settings.max_upload_bytes,
        )
        self.search_service = SearchService(self.session_factory, self.embedder)
        self.question_service = QuestionService(
            self.session_factory,
            self.embedder,
            self.semantic_cache,
            self.search_service,
            ExtractiveAnswerProvider(),
        )

    @staticmethod
    def _build_embedder(settings: Settings) -> Embedder:
        if settings.embedding_provider == "hashing":
            # Use only for fast plumbing tests; it is not a semantic model.
            return HashingEmbedder(settings.embedding_dimensions)
        if settings.embedding_provider == "sentence-transformer":
            return SentenceTransformerEmbedder(
                settings.embedding_model, settings.embedding_dimensions
            )
        raise ValueError(
            "EMBEDDING_PROVIDER must be 'sentence-transformer' or 'hashing'"
        )

    @staticmethod
    def _build_cache(settings: Settings) -> SemanticCache:
        if not settings.semantic_cache_enabled:
            return NullSemanticCache()
        return RedisSemanticCache(
            redis_url=settings.redis_url,
            index_name=settings.redis_cache_index,
            key_prefix=settings.redis_cache_prefix,
            dimensions=settings.embedding_dimensions,
            ttl_seconds=settings.semantic_cache_ttl_seconds,
            distance_threshold=settings.semantic_cache_distance_threshold,
        )

    def prepare(self) -> None:
        """Fail startup for authoritative dependencies; degrade for the optional cache."""
        self.storage.prepare()
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        self.semantic_cache.ensure_index()  # Adapter logs and fails open if Redis is unavailable.
        if self.settings.warm_embedding_model:
            # Download/load now so the first real request does not pay a surprise cold start.
            self.embedder.warm_up()

    def build_outbox_service(self) -> OutboxService:
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        return OutboxService(
            self.session_factory,
            self.storage,
            NoOpExternalVectorStore(),
            worker_id,
            self.settings.outbox_lease_seconds,
        )

    def close(self) -> None:
        if isinstance(self.semantic_cache, RedisSemanticCache):
            self.semantic_cache.client.close()
        self.engine.dispose()


@lru_cache
def get_container() -> Container:
    """FastAPI dependency and script entry point share the same construction policy."""
    return Container(get_settings())
```

`hashing` exists so you can prove transactions and HTTP flow without downloading a model. Switch
back to `sentence-transformer` before judging semantic quality.

## 2. Define HTTP schemas

Pydantic models belong at the untrusted HTTP boundary. Do not return SQLAlchemy rows directly:
that couples the public contract to persistence and can accidentally trigger lazy database loads.

**File:** `policy-vault/app/api/schemas.py`

```python
"""Stable request/response contracts and explicit domain-to-HTTP conversion."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import (
    DeleteResult,
    DocumentStatus,
    QuestionResult,
    UploadResult,
)


class DocumentResponse(BaseModel):
    # Domain dataclasses expose attributes rather than dictionaries.
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str
    sha256: str
    status: DocumentStatus
    page_count: int
    chunk_count: int
    created_at: datetime
    deleted_at: datetime | None


class UploadResponse(BaseModel):
    document: DocumentResponse
    deduplicated: bool

    @classmethod
    def from_domain(cls, result: UploadResult) -> "UploadResponse":
        return cls(
            document=DocumentResponse.model_validate(result.document),
            deduplicated=result.deduplicated,
        )


class DeleteResponse(BaseModel):
    document_id: UUID
    status: DocumentStatus
    cleanup_pending: bool

    @classmethod
    def from_domain(cls, result: DeleteResult) -> "DeleteResponse":
        return cls.model_validate(result, from_attributes=True)


class SearchHitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    content: str
    distance: float
    score: float


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2_000)
    limit: int = Field(default=4, ge=1, le=20)


class AnswerSourceResponse(BaseModel):
    document_id: UUID
    filename: str
    page_number: int
    chunk_index: int
    excerpt: str
    score: float


class QuestionResponse(BaseModel):
    answer: str
    sources: list[AnswerSourceResponse]
    knowledge_base_version: int
    cache_hit: bool
    cache_distance: float | None

    @classmethod
    def from_domain(cls, result: QuestionResult) -> "QuestionResponse":
        return cls(
            answer=result.answer,
            sources=[AnswerSourceResponse.model_validate(source, from_attributes=True)
                     for source in result.sources],
            knowledge_base_version=result.knowledge_base_version,
            cache_hit=result.cache_hit,
            cache_distance=result.cache_distance,
        )


class HealthResponse(BaseModel):
    status: str
    dependencies: dict[str, str] = Field(default_factory=dict)
```

Run the linter immediately after creating each file. Unused imports often reveal that a boundary
is carrying concepts it does not actually need.

## 3. Add API and health routes

FastAPI runs ordinary `def` route functions in its thread pool. Upload is `async` only because
`UploadFile.read()` is asynchronous; its CPU/DB use case is explicitly moved to the thread pool.

**File:** `policy-vault/app/api/routes.py`

```python
"""Thin HTTP adapters: validate, call one use case, convert the result."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas import (
    AskRequest,
    DeleteResponse,
    DocumentResponse,
    HealthResponse,
    QuestionResponse,
    SearchHitResponse,
    UploadResponse,
)
from app.domain.models import DistanceMetric
from app.infrastructure.container import Container, get_container

ContainerDependency = Annotated[Container, Depends(get_container)]

api_router = APIRouter(prefix="/api/v1")
health_router = APIRouter(prefix="/health")


@api_router.post(
    "/documents", response_model=UploadResponse, status_code=status.HTTP_201_CREATED
)
async def upload_document(
    container: ContainerDependency,
    file: Annotated[UploadFile, File(description="TXT, Markdown, or text-layer PDF")],
) -> UploadResponse:
    # Read at most limit + 1 so oversized uploads never grow memory without a bound.
    try:
        data = await file.read(container.settings.max_upload_bytes + 1)
    finally:
        await file.close()
    result = await run_in_threadpool(
        container.document_service.upload,
        file.filename or "",
        file.content_type or "application/octet-stream",
        data,
    )
    return UploadResponse.from_domain(result)


@api_router.get("/documents", response_model=list[DocumentResponse])
def list_documents(container: ContainerDependency) -> list[DocumentResponse]:
    return [
        DocumentResponse.model_validate(document)
        for document in container.document_service.list_documents()
    ]


@api_router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: UUID, container: ContainerDependency) -> DocumentResponse:
    return DocumentResponse.model_validate(
        container.document_service.get_document(document_id)
    )


@api_router.delete(
    "/documents/{document_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def delete_document(document_id: UUID, container: ContainerDependency) -> DeleteResponse:
    return DeleteResponse.from_domain(
        container.document_service.delete_document(document_id)
    )


@api_router.get("/search", response_model=list[SearchHitResponse])
def search_documents(
    container: ContainerDependency,
    query: Annotated[str, Query(min_length=2, max_length=2_000)],
    metric: DistanceMetric = DistanceMetric.COSINE,
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
) -> list[SearchHitResponse]:
    hits = container.search_service.search(query, metric=metric, limit=limit)
    return [SearchHitResponse.model_validate(hit) for hit in hits]


@api_router.post("/ask", response_model=QuestionResponse)
def ask(request: AskRequest, container: ContainerDependency) -> QuestionResponse:
    result = container.question_service.ask(request.question, limit=request.limit)
    return QuestionResponse.from_domain(result)


@health_router.get("/live", response_model=HealthResponse)
def live() -> HealthResponse:
    # Liveness only proves that the process can serve Python code.
    return HealthResponse(status="ok")


@health_router.get("/ready", response_model=HealthResponse)
def ready(response: Response, container: ContainerDependency) -> HealthResponse:
    dependencies: dict[str, str] = {}
    try:
        with container.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        dependencies["postgres"] = "ok"
    except SQLAlchemyError:
        dependencies["postgres"] = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    if container.settings.semantic_cache_enabled:
        # Redis is visible as degraded, but it is not authoritative readiness.
        dependencies["redis_cache"] = (
            "ok" if container.semantic_cache.ping() else "degraded"
        )
    else:
        dependencies["redis_cache"] = "disabled"
    overall = "ok" if dependencies["postgres"] == "ok" else "unavailable"
    return HealthResponse(status=overall, dependencies=dependencies)
```

Why no repository dependency in a route? A route should call a use case, not assemble database
behavior itself. Health checks are the narrow exception because they inspect infrastructure.

## 4. Create the FastAPI application

Lifespan runs startup and shutdown exactly around the application process. Migrations remain an
explicit command; silently migrating during web startup creates races when several replicas start.

**File:** `policy-vault/app/main.py`

```python
"""ASGI entry point and process-lifecycle policy."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import api_router, health_router
from app.core.config import get_settings
from app.core.errors import (
    InvalidDocumentError,
    NotFoundError,
    OCRRequiredError,
    PolicyVaultError,
    UnsupportedDocumentError,
    UploadTooLargeError,
)
from app.infrastructure.container import get_container


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        del application
        container = get_container()
        container.prepare()
        yield
        container.close()

    application = FastAPI(
        title="PolicyVault",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(api_router)
    application.include_router(health_router)

    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid4().hex)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @application.exception_handler(PolicyVaultError)
    async def handle_expected_error(
        request: Request, exception: PolicyVaultError
    ) -> JSONResponse:
        if isinstance(exception, NotFoundError):
            status_code, code = 404, "not_found"
        elif isinstance(exception, UploadTooLargeError):
            status_code, code = 413, "upload_too_large"
        elif isinstance(exception, OCRRequiredError):
            status_code, code = 422, "ocr_required"
        elif isinstance(exception, UnsupportedDocumentError):
            status_code, code = 415, "unsupported_document"
        elif isinstance(exception, InvalidDocumentError):
            status_code, code = 422, "invalid_document"
        else:
            status_code, code = 400, "policy_vault_error"
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": str(exception),
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    return application


app = create_app()
```

## 5. Run the complete system

Terminal 1, once after every schema change:

```bash
docker compose up -d
uv run alembic upgrade head
```

For a fast infrastructure smoke test, temporarily set these values in `.env`:

```dotenv
EMBEDDING_PROVIDER=hashing
WARM_EMBEDDING_MODEL=false
```

Terminal 2:

```bash
uv run uvicorn app.main:app --reload
```

Terminal 3:

```bash
uv run python -m scripts.process_outbox
```

Open <http://127.0.0.1:8000/docs>. FastAPI’s generated UI is enough for this backend lab.

## 6. Exercise every endpoint in order

```bash
curl -sS http://127.0.0.1:8000/health/ready
curl -sS -F "file=@sample_data/handbook.txt;type=text/plain" \
  http://127.0.0.1:8000/api/v1/documents
curl -sS http://127.0.0.1:8000/api/v1/documents
curl -sS --get --data-urlencode "query=How much is the learning budget?" \
  --data "metric=cosine" --data "limit=3" \
  http://127.0.0.1:8000/api/v1/search
curl -sS -H "Content-Type: application/json" \
  -d '{"question":"What is the annual learning allowance?","limit":3}' \
  http://127.0.0.1:8000/api/v1/ask
curl -sS -H "Content-Type: application/json" \
  -d '{"question":"How much may an employee spend on learning each year?","limit":3}' \
  http://127.0.0.1:8000/api/v1/ask
```

With the hashing embedder, the last paraphrase is not guaranteed to hit—it tests wiring only. Set
the provider back to `sentence-transformer`, restart, upload into a fresh database, and repeat to
evaluate meaning. The second response should show `"cache_hit": true` only if its cosine distance
is within your configured threshold.

Copy an ID from the document list:

```bash
export DOCUMENT_ID="paste-document-uuid-here"
curl -sS -X DELETE "http://127.0.0.1:8000/api/v1/documents/${DOCUMENT_ID}"
curl -sS "http://127.0.0.1:8000/api/v1/documents/${DOCUMENT_ID}"
```

Observe `DELETING`, then `DELETED` after the worker completes. Search must stop returning its
chunks immediately after the delete request—not after the worker runs.

## Checkpoint

```bash
uv run ruff format --check app scripts
uv run ruff check app scripts
uv run mypy app scripts
curl -f http://127.0.0.1:8000/health/live
```

Commit:

```bash
git add app
git commit -m "feat: expose document vector and cache use cases through FastAPI"
```

Continue with `16_TESTS_QUALITY_AND_CI.md`.
