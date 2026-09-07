# 14 — Ask Flow and Cache Scope

**Working directory:** `policy-vault/`  
**Build output:** retrieve/answer/cache orchestration with version-safe hits

## Scope before similarity

Semantic similarity answers “does this prompt mean roughly the same thing?” It must never decide
whether two records belong to the same security or compatibility boundary.

Build an exact scope from:

- tenant;
- knowledge-base ID and version;
- embedding model;
- answer-provider/prompt-template version.

Hashing the canonical scope gives a Redis-tag-safe fixed-size value. An upload or delete increments
the knowledge-base version, immediately making prior cache records unreachable. TTL later reclaims
their memory.

## Implement the question service

**File:** `policy-vault/app/application/question_service.py`

```python
"""Semantic-cache lookup, pgvector retrieval, answer construction, and cache write."""

import hashlib
import json
import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from app.application.ports import AnswerProvider, Embedder, SemanticCache
from app.application.search_service import SearchService
from app.core.constants import DEFAULT_KNOWLEDGE_BASE_ID
from app.domain.models import AnswerSource, DistanceMetric, QuestionResult, SearchHit
from app.infrastructure.repositories import KnowledgeBaseRepository

logger = logging.getLogger(__name__)


def semantic_cache_scope(
    knowledge_base_id: UUID,
    version: int,
    embedding_model: str,
    answer_provider_version: str,
    tenant: str = "local-lab",
) -> str:
    values = {
        "tenant": tenant,
        "knowledge_base": str(knowledge_base_id),
        "knowledge_base_version": version,
        "embedding_model": embedding_model,
        "answer_provider": answer_provider_version,
    }
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class ExtractiveAnswerProvider:
    """Deterministic learning provider; replace through the AnswerProvider port later."""

    @property
    def version(self) -> str:
        return "extractive-v1"

    def answer(self, question: str, hits: Sequence[SearchHit]) -> str:
        del question
        if not hits:
            return "I could not find a relevant passage in the uploaded documents."
        lead = " ".join(hits[0].content.split())
        if len(lead) > 700:
            lead = f"{lead[:697]}..."
        return f"Most relevant passage: {lead}"


class QuestionService:
    def __init__(
        self,
        session_factory: sessionmaker,
        embedder: Embedder,
        semantic_cache: SemanticCache,
        search_service: SearchService,
        answer_provider: AnswerProvider,
    ) -> None:
        self.session_factory = session_factory
        self.embedder = embedder
        self.semantic_cache = semantic_cache
        self.search_service = search_service
        self.answer_provider = answer_provider

    def ask(
        self,
        question: str,
        limit: int = 4,
        knowledge_base_id: UUID = DEFAULT_KNOWLEDGE_BASE_ID,
    ) -> QuestionResult:
        # Reuse one query embedding for Redis lookup and PostgreSQL retrieval.
        query_embedding = self.embedder.embed_query(question)
        with self.session_factory() as session:
            version = KnowledgeBaseRepository(session).get_version(knowledge_base_id)

        scope = semantic_cache_scope(
            knowledge_base_id,
            version,
            self.embedder.name,
            self.answer_provider.version,
        )
        match = self.semantic_cache.find(scope, query_embedding)
        if match is not None:
            try:
                return self._deserialize(match.payload_json, match.distance)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                # Old/corrupt cache payloads degrade to a miss rather than breaking the API.
                logger.warning("Ignored incompatible cache payload", exc_info=True)

        hits = self.search_service.search_embedding(
            query_embedding,
            metric=DistanceMetric.COSINE,
            limit=limit,
            knowledge_base_id=knowledge_base_id,
        )
        sources = tuple(
            AnswerSource(
                document_id=hit.document_id,
                filename=hit.filename,
                page_number=hit.page_number,
                chunk_index=hit.chunk_index,
                excerpt=self._excerpt(hit.content),
                score=hit.score,
            )
            for hit in hits
        )
        result = QuestionResult(
            answer=self.answer_provider.answer(question, hits),
            sources=sources,
            knowledge_base_version=version,
        )
        # Store the complete response so a hit skips retrieval and answer generation.
        self.semantic_cache.put(scope, question, query_embedding, self._serialize(result))
        return result

    @staticmethod
    def _excerpt(content: str) -> str:
        compact = " ".join(content.split())
        return compact if len(compact) <= 400 else f"{compact[:397]}..."

    @staticmethod
    def _serialize(result: QuestionResult) -> str:
        return json.dumps(
            {
                "answer": result.answer,
                "knowledge_base_version": result.knowledge_base_version,
                "sources": [
                    {
                        "document_id": str(source.document_id),
                        "filename": source.filename,
                        "page_number": source.page_number,
                        "chunk_index": source.chunk_index,
                        "excerpt": source.excerpt,
                        "score": source.score,
                    }
                    for source in result.sources
                ],
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _deserialize(payload_json: str, distance: float) -> QuestionResult:
        payload = json.loads(payload_json)
        return QuestionResult(
            answer=payload["answer"],
            knowledge_base_version=int(payload["knowledge_base_version"]),
            sources=tuple(
                AnswerSource(
                    document_id=UUID(source["document_id"]),
                    filename=source["filename"],
                    page_number=int(source["page_number"]),
                    chunk_index=int(source["chunk_index"]),
                    excerpt=source["excerpt"],
                    score=float(source["score"]),
                )
                for source in payload["sources"]
            ),
            cache_hit=True,
            cache_distance=distance,
        )
```

## Why the answer provider is not an LLM yet

The learning objective is cache correctness, not prompt-provider configuration. A deterministic
answer makes tests free, fast, and reproducible. Later, implement the same `AnswerProvider` port
with an LLM and change its version whenever the prompt template or output contract changes.

## Concurrency reasoning

The version is read before search. If a concurrent upload/delete commits afterward, any result
cached under the old version is immediately unreachable to later requests. It may be harmless
unused data until TTL expiry. Stronger snapshot requirements could move version read and retrieval
into one transaction, but that keeps a transaction open during more work.

## Checkpoint

```bash
uv run python -c "from uuid import uuid4; from app.application.question_service import semantic_cache_scope; k=uuid4(); print(semantic_cache_scope(k,1,'m','a') != semantic_cache_scope(k,2,'m','a'))"
uv run ruff check app/application/question_service.py
```

Expected: `True`.

Commit:

```bash
git add app/application/question_service.py
git commit -m "feat: add version-scoped cached answer flow"
```

Continue with `15_FASTAPI_ASSEMBLY.md`.

