# 10 — Vector Mathematics and Exact pgvector Search

**Working directory:** `policy-vault/`  
**Build output:** three metric choices and an exact search baseline

## Dimensions and storage cost

Dimension is the number of numeric features in an embedding. Models with different dimensions
cannot be compared directly. A float32 vector’s raw payload is approximately:

$$bytes = dimensions \times 4$$

Therefore, 384 dimensions use 1,536 raw bytes per vector before PostgreSQL row/index overhead.
One million such vectors require roughly 1.43 GiB just for raw float values.

## The three metrics

For vectors $x$ and $y$:

### Cosine distance and similarity

$$similarity_{cos}=\frac{x\cdot y}{\lVert x\rVert\lVert y\rVert}$$

$$distance_{cos}=1-similarity_{cos}$$

Cosine focuses on direction. Lower distance is better; higher similarity is better.

### Euclidean/L2 distance

$$distance_{L2}=\sqrt{\sum_i(x_i-y_i)^2}$$

L2 measures straight-line distance and remains sensitive to magnitude.

### Dot/inner product

$$score_{dot}=x\cdot y=\sum_i x_i y_i$$

Higher is better. With unit-normalized vectors, dot product equals cosine similarity. Also:

$$\lVert x-y\rVert^2=2-2(x\cdot y)$$

## Build a metric playground

**File:** `policy-vault/scripts/metric_playground.py`

```python
"""Use tiny vectors to make metric behavior visible before using embeddings."""

import numpy as np


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def main() -> None:
    query = np.array([1.0, 1.0, 0.0], dtype=np.float32)
    candidates = {
        "same direction, longer": np.array([3.0, 3.0, 0.0], dtype=np.float32),
        "nearby point": np.array([1.0, 0.8, 0.2], dtype=np.float32),
        "opposite direction": np.array([-1.0, -1.0, 0.0], dtype=np.float32),
    }

    print(f"{'candidate':28} {'cosine distance':>16} {'L2':>10} {'dot product':>14}")
    for name, candidate in candidates.items():
        cosine_distance = 1.0 - float(np.dot(normalize(query), normalize(candidate)))
        l2_distance = float(np.linalg.norm(query - candidate))
        dot_product = float(np.dot(query, candidate))
        print(f"{name:28} {cosine_distance:16.4f} {l2_distance:10.4f} {dot_product:14.4f}")

    print("\nAfter normalization: dot = cosine similarity")
    normalized_query = normalize(query)
    for name, candidate in candidates.items():
        normalized_candidate = normalize(candidate)
        cosine = float(np.dot(normalized_query, normalized_candidate))
        l2_squared = float(np.sum((normalized_query - normalized_candidate) ** 2))
        print(f"{name:28} dot={cosine:.4f} L2^2={l2_squared:.4f}")


if __name__ == "__main__":
    main()
```

Run:

```bash
uv run python -m scripts.metric_playground
```

Predict why “same direction, longer” wins cosine but loses L2 before viewing the output.

## Implement pgvector search

pgvector operators:

| Metric | SQL operator | SQLAlchemy method | Ordering |
|---|---|---|---|
| L2 | `<->` | `l2_distance()` | lower is closer |
| Negative inner product | `<#>` | `max_inner_product()` | lower negative value = higher product |
| Cosine distance | `<=>` | `cosine_distance()` | lower is closer |

PostgreSQL indexes support ascending scans, so `<#>` returns **negative** inner product. Convert it
back to a human-facing score by negating it.

**File:** `policy-vault/app/application/search_service.py`

```python
"""Exact or ANN search; the SQL shape stays the same when an index is added."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.application.ports import Embedder
from app.core.constants import DEFAULT_KNOWLEDGE_BASE_ID
from app.domain.models import DistanceMetric, DocumentStatus, SearchHit
from app.infrastructure.orm import ChunkRow, DocumentRow


class SearchService:
    def __init__(self, session_factory: sessionmaker, embedder: Embedder) -> None:
        self.session_factory = session_factory
        self.embedder = embedder

    def search(
        self,
        query: str,
        metric: DistanceMetric = DistanceMetric.COSINE,
        limit: int = 5,
        knowledge_base_id: UUID = DEFAULT_KNOWLEDGE_BASE_ID,
    ) -> list[SearchHit]:
        return self.search_embedding(
            self.embedder.embed_query(query), metric, limit, knowledge_base_id
        )

    def search_embedding(
        self,
        query_embedding: Sequence[float],
        metric: DistanceMetric = DistanceMetric.COSINE,
        limit: int = 5,
        knowledge_base_id: UUID = DEFAULT_KNOWLEDGE_BASE_ID,
    ) -> list[SearchHit]:
        vector = list(query_embedding)
        if metric is DistanceMetric.COSINE:
            distance_expression = ChunkRow.embedding.cosine_distance(vector)
        elif metric is DistanceMetric.L2:
            distance_expression = ChunkRow.embedding.l2_distance(vector)
        else:
            distance_expression = ChunkRow.embedding.max_inner_product(vector)

        statement = (
            select(ChunkRow, DocumentRow, distance_expression.label("distance"))
            .join(DocumentRow, DocumentRow.id == ChunkRow.document_id)
            .where(
                DocumentRow.knowledge_base_id == knowledge_base_id,
                # Lifecycle filtering prevents DELETING/DELETED content from leaking.
                DocumentRow.status == DocumentStatus.READY.value,
            )
            # ORDER BY distance operator + LIMIT is the indexable pgvector query shape.
            .order_by(distance_expression)
            .limit(limit)
        )
        with self.session_factory() as session:
            rows = session.execute(statement).all()

        hits: list[SearchHit] = []
        for chunk, document, raw_distance in rows:
            distance = float(raw_distance)
            if metric is DistanceMetric.COSINE:
                score = 1.0 - distance
            elif metric is DistanceMetric.L2:
                # This bounded score is presentation only; ranking still uses true L2.
                score = 1.0 / (1.0 + distance)
            else:
                score = -distance
            hits.append(
                SearchHit(
                    document_id=document.id,
                    filename=document.filename,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    distance=distance,
                    score=score,
                )
            )
        return hits
```

With no HNSW/IVFFlat index, this query performs exact search. That is desirable now.

## Checkpoint

```bash
uv run ruff check app/application/search_service.py scripts/metric_playground.py
uv run mypy app scripts
uv run python -m scripts.metric_playground
```

Commit:

```bash
git add app/application/search_service.py scripts/metric_playground.py
git commit -m "feat: add vector metrics and exact search"
```

Continue with `11_ANN_HNSW_IVFFLAT_VDB_MATRIX.md`.
