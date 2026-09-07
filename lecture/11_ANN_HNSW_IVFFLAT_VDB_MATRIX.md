# 11 — ANN, HNSW, IVFFlat, and VDB Index Matrix

**Working directory:** `policy-vault/`  
**Build output:** safe index-switching CLI and a performance mental model

## HNSW graph structure

HNSW builds a multi-layer proximity graph:

- sparse upper layers make long jumps through vector space;
- dense lower layers refine the local neighborhood;
- search greedily follows promising edges toward the query;
- the graph can be queried before all future rows exist.

Important parameters:

| Parameter | Stage | Increase usually causes |
|---|---|---|
| `m` | Build/storage | More connections, memory, build time, often better recall |
| `ef_construction` | Build | More build work and often a better graph |
| `hnsw.ef_search` | Query | More candidates, latency, and usually recall |

HNSW is often the first ANN choice for pgvector when memory and build cost are acceptable.

## IVFFlat indexing

IVFFlat runs k-means-like clustering and assigns vectors to inverted lists. At query time it finds
nearby centroids and scans only selected lists.

| Parameter | Meaning | Trade-off |
|---|---|---|
| `lists` | Number of partitions built | More partitions narrow each list but require enough data |
| `ivfflat.probes` | Lists searched per query | More probes improve recall but cost latency |

Build IVFFlat after representative data exists. Unlike HNSW, its partitions depend strongly on the
data distribution used at build time.

## Create an index-management CLI

The metric operator class must match the query metric. An HNSW cosine index cannot accelerate an
L2 operator query.

**File:** `policy-vault/scripts/manage_chunk_index.py`

```python
"""Keep one learning index at a time so plans and storage remain easy to compare."""

import argparse
import time

from sqlalchemy import text

from app.core.config import get_settings
from app.infrastructure.database import build_engine

INDEX_NAMES = ("ix_chunks_embedding_hnsw", "ix_chunks_embedding_ivfflat")
OPERATOR_CLASSES = {
    "cosine": "vector_cosine_ops",
    "l2": "vector_l2_ops",
    "inner_product": "vector_ip_ops",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Select exact, HNSW, or IVFFlat search")
    parser.add_argument("method", choices=("exact", "hnsw", "ivfflat"))
    parser.add_argument("--metric", choices=tuple(OPERATOR_CLASSES), default="cosine")
    parser.add_argument("--lists", type=int, default=100)
    parser.add_argument("--m", type=int, default=16)
    parser.add_argument("--ef-construction", type=int, default=64)
    args = parser.parse_args()
    if args.lists < 1 or args.m < 2 or args.ef_construction < 4:
        parser.error("lists >= 1, m >= 2, and ef-construction >= 4 are required")

    operator_class = OPERATOR_CLASSES[args.metric]
    engine = build_engine(get_settings().database_url)
    started = time.perf_counter()

    # CREATE/DROP INDEX runs in autocommit mode so this CLI can later adopt CONCURRENTLY.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for index_name in INDEX_NAMES:
            connection.execute(text(f"DROP INDEX IF EXISTS {index_name}"))

        if args.method == "hnsw":
            connection.execute(
                text(
                    "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
                    f"USING hnsw (embedding {operator_class}) "
                    f"WITH (m = {args.m}, ef_construction = {args.ef_construction})"
                )
            )
        elif args.method == "ivfflat":
            connection.execute(
                text(
                    "CREATE INDEX ix_chunks_embedding_ivfflat ON chunks "
                    f"USING ivfflat (embedding {operator_class}) WITH (lists = {args.lists})"
                )
            )

        connection.execute(text("ANALYZE chunks"))

    engine.dispose()
    elapsed = time.perf_counter() - started
    print(f"method={args.method} metric={args.metric} elapsed={elapsed:.2f}s")
    if args.method == "exact":
        print("No ANN vector index exists; PostgreSQL will calculate exact neighbors.")


if __name__ == "__main__":
    main()
```

The f-strings are safe here because every substituted value comes from an `argparse` choice or a
validated integer. Do not generalize this into arbitrary user-provided SQL identifiers.

Run each mode:

```bash
uv run python -m scripts.manage_chunk_index exact --metric cosine
uv run python -m scripts.manage_chunk_index hnsw --metric cosine --m 16 --ef-construction 64
uv run python -m scripts.manage_chunk_index ivfflat --metric cosine --lists 100
```

Query-time tuning in a transaction:

```sql
BEGIN;
SET LOCAL hnsw.ef_search = 100;
SELECT id FROM chunks ORDER BY embedding <=> '[...]'::vector LIMIT 10;
COMMIT;
```

```sql
BEGIN;
SET LOCAL ivfflat.probes = 20;
SELECT id FROM chunks ORDER BY embedding <=> '[...]'::vector LIMIT 10;
COMMIT;
```

## Current index-family comparison

Checked against official documentation on **2026-09-03**. Counts are not perfectly comparable:
some products call brute-force scan an index, and some count CPU, GPU, sparse, or quantized variants
separately.

| Engine | User-visible dense choices | Practical count |
|---|---|---:|
| pgvector | Exact scan, HNSW, IVFFlat | 2 ANN families + exact |
| Qdrant | HNSW for dense vectors | 1 dense ANN family |
| Weaviate | HNSW, Flat, Dynamic, HFresh | 4 configurable types |
| Redis Search | FLAT, HNSW, SVS-VAMANA where supported | Up to 3 |
| Milvus | FLAT, IVF_FLAT, IVF_SQ8, IVF_PQ, HNSW, DISKANN, SCANN plus more variants | 7 common CPU float choices, more by category |

Priority recommendation: master pgvector’s exact/HNSW/IVFFlat trade-offs first. A high algorithm
count does not automatically make a database a better architectural fit.

Primary sources:

- [pgvector exact and approximate indexes](https://github.com/pgvector/pgvector)
- [Qdrant indexing](https://qdrant.tech/documentation/manage-data/indexing/)
- [Weaviate vector indexes](https://docs.weaviate.io/weaviate/config-refs/indexing/vector-index)
- [Redis vector concepts](https://redis.io/docs/latest/develop/ai/search-and-query/vectors/)
- [Milvus index overview](https://milvus.io/docs/index-explained.md)

## Explain-plan discipline

Use:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT chunks.id
FROM chunks
JOIN documents ON documents.id = chunks.document_id
WHERE documents.status = 'READY'
ORDER BY chunks.embedding <=> '[...]'::vector
LIMIT 10;
```

ANN is not automatically faster for tiny data. PostgreSQL may correctly choose a sequential scan.
Filtered ANN also requires measurement because filtering can remove candidates after index search.

## Checkpoint

```bash
uv run ruff check scripts/manage_chunk_index.py
uv run python -m scripts.manage_chunk_index hnsw --metric cosine
docker compose exec postgres psql -U policy_vault -d policy_vault -c "\di ix_chunks_embedding*"
uv run python -m scripts.manage_chunk_index exact --metric cosine
```

Commit:

```bash
git add scripts/manage_chunk_index.py
git commit -m "feat: add pgvector ANN index laboratory"
```

Continue with `12_ACID_DELETE_AND_OUTBOX.md`.

