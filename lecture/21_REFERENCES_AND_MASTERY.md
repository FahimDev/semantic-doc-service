# 21 — Primary References, Mastery Exercises, and Answer Key

This chapter turns a completed build into durable understanding. The links are official project
documentation or primary technical material, checked on **2026-09-03**.

## Final project tree

Use this to detect a misplaced file. Generated `.venv`, cache, upload, and database-volume files
are omitted.

```text
policy-vault/
├── .github/
│   └── workflows/
│       └── ci.yml
├── alembic/
│   ├── versions/
│   │   └── 0001_initial.py
│   └── env.py
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── schemas.py
│   ├── application/
│   │   ├── __init__.py
│   │   ├── document_service.py
│   │   ├── outbox_service.py
│   │   ├── ports.py
│   │   ├── question_service.py
│   │   └── search_service.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── constants.py
│   │   └── errors.py
│   ├── domain/
│   │   ├── __init__.py
│   │   └── models.py
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── cache.py
│   │   ├── chunking.py
│   │   ├── container.py
│   │   ├── database.py
│   │   ├── embedding.py
│   │   ├── orm.py
│   │   ├── parsers.py
│   │   ├── repositories.py
│   │   └── storage.py
│   ├── __init__.py
│   └── main.py
├── sample_data/
│   └── handbook.txt
├── scripts/
│   ├── __init__.py
│   ├── benchmark_indexes.py
│   ├── manage_chunk_index.py
│   ├── metric_playground.py
│   └── process_outbox.py
├── tests/
│   ├── integration/
│   │   └── test_api_flow.py
│   ├── unit/
│   │   ├── test_chunking.py
│   │   ├── test_foundations.py
│   │   └── test_parsers.py
│   └── __init__.py
├── .env.example
├── .gitignore
├── .python-version
├── alembic.ini
├── compose.yaml
├── pyproject.toml
└── uv.lock
```

`app/infrastructure/ocr.py` is added only when you perform the optional Chapter 19 extension.

## Primary reading route

Do not read every page before building. Follow the “read when” column when an experiment gives you
a concrete question.

| Topic | Primary source | Read when |
|---|---|---|
| uv project lifecycle | [uv projects guide](https://docs.astral.sh/uv/guides/projects/) | before changing dependencies or lock files |
| uv dependency groups/extras | [uv dependency management](https://docs.astral.sh/uv/concepts/projects/dependencies/) | before optional OCR or dev groups |
| uv in CI | [official GitHub Actions guide](https://docs.astral.sh/uv/guides/integration/github/) | while reviewing Chapter 16 |
| FastAPI structure | [Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/) | when adding another router |
| dependency injection | [FastAPI dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/) | when replacing adapters in tests |
| multipart files | [FastAPI request files](https://fastapi.tiangolo.com/tutorial/request-files/) | before changing upload behavior |
| process lifecycle | [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) | before adding startup resources |
| typed environment config | [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | before adding configuration |
| transaction boundaries | [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html) | when a service begins committing |
| PostgreSQL transactions | [PostgreSQL transaction tutorial](https://www.postgresql.org/docs/current/tutorial-transactions.html) | while explaining ACID |
| isolation/MVCC | [PostgreSQL isolation](https://www.postgresql.org/docs/current/transaction-iso.html) | before concurrency tests |
| B-tree behavior | [PostgreSQL B-tree indexes](https://www.postgresql.org/docs/current/btree.html) | before comparing scalar/vector indexes |
| pgvector operators/indexes | [pgvector README](https://github.com/pgvector/pgvector) | throughout exact and ANN work |
| Python integration | [pgvector-python](https://github.com/pgvector/pgvector-python) | while reading ORM/psycopg code |
| HNSW algorithm | [original HNSW paper](https://arxiv.org/abs/1603.09320) | after running the HNSW benchmark |
| inverted-file indexes | [Faiss index guide](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes) | after running IVFFlat |
| Redis vector search | [Redis vector concepts](https://redis.io/docs/latest/develop/ai/search-and-query/vectors/) | before reading the cache adapter |
| semantic caching | [Redis semantic cache use case](https://redis.io/docs/latest/develop/use-cases/semantic-cache/) | before threshold evaluation |
| PDF extraction/OCR | [pypdf extraction guide](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) | when a PDF extracts badly |

VDB comparison sources from Chapter 11:

- [Qdrant indexing](https://qdrant.tech/documentation/manage-data/indexing/)
- [Weaviate vector-index configuration](https://docs.weaviate.io/weaviate/config-refs/indexing/vector-index)
- [Redis vector index types](https://redis.io/docs/latest/develop/ai/search-and-query/vectors/)
- [Milvus index overview](https://milvus.io/docs/index-explained.md)

## Twelve deliberate experiments

Each experiment requires a prediction, recorded output, and explanation.

1. **Metric magnitude:** multiply one candidate vector by ten and compare cosine, L2, and inner
   product before/after normalization.
2. **Dimension invariant:** try inserting 383 values into `vector(384)` and explain where it fails.
3. **Chunk boundary:** test three chunk sizes and overlaps against five known questions.
4. **Exact baseline:** remove ANN indexes and save exact top-10 IDs for 30 queries.
5. **HNSW curve:** sweep `ef_search`; graph recall@10 versus p95.
6. **IVFFlat curve:** sweep `lists` at build and `probes` at query; graph recall@10 versus p95.
7. **Index mismatch:** build cosine HNSW, issue L2 search, and inspect the plan.
8. **Filtered ANN:** add a selective knowledge-base filter and compare result count/recall.
9. **Delete crash:** stop the worker after the DB commit; prove search hides the document and the
   event survives restart.
10. **Cache threshold:** label paraphrases and near-but-wrong questions, then calculate false-hit
    and miss rates over several thresholds.
11. **Cache invalidation:** cache an answer, upload or delete a document, and prove the versioned
    scope misses without scanning/deleting old Redis keys.
12. **PDF corpus:** evaluate a clean export, OCRed scan, image-only scan, two-column article, and
    table-heavy report; record extraction and citation errors separately from retrieval errors.

## Mastery rubric

| Level | Evidence |
|---|---|
| Built | endpoints and tests run |
| Understood | you can explain every invariant and failure boundary |
| Measured | you have recall/latency and cache-threshold evaluation data |
| Operable | crash/retry behavior and reconciliation are tested |
| Extensible | a fake OCR/VDB adapter is added without use-case rewrites |
| Mastered | you can defend trade-offs for a new workload and teach them clearly |

## Common misconceptions to eliminate

- **“Cosine distance is cosine similarity.”** No: distance is normally `1 - similarity`.
- **“Inner product always equals cosine.”** Only when both vectors are unit normalized.
- **“More dimensions always means better retrieval.”** Dimensions change capacity, cost, model
  compatibility, and may or may not improve task quality.
- **“HNSW is exact.”** It is approximate unless measured settings happen to recover all truth for
  a particular test.
- **“IVFFlat should be built on an empty table.”** It needs representative data to form useful
  partitions.
- **“A vector index replaces B-tree metadata indexes.”** Vector ranking and scalar filtering solve
  different access patterns.
- **“Redis loss loses answers permanently.”** Not here; authoritative content is in PostgreSQL and
  a miss recomputes the response.
- **“Database ACID covers a file or another VDB.”** Not across independent systems; use an outbox,
  idempotency, state filtering, and reconciliation.
- **“A PDF is just a long text file.”** Its text order, layout, images, fonts, and page provenance
  require a parser/evaluation boundary.
- **“A passing fake-embedding test proves semantic search.”** It proves only plumbing.

## Final self-exam

Answer these before reading the key:

1. Which state is authoritative, and which state may be flushed?
2. Why is upload hashing checked both before and inside the transaction?
3. What exactly commits atomically during delete?
4. What can happen if the process dies after deleting the file but before completing the event?
5. Which pgvector operator and operator class serve cosine search?
6. Why does normalized inner-product ranking match cosine ranking?
7. What do `m`, `ef_construction`, and `ef_search` control in HNSW?
8. What do `lists` and `probes` control in IVFFlat?
9. How is ANN recall calculated?
10. Why must cache scope include the knowledge-base and model versions?
11. Why does a semantic cache store the final response instead of only source chunks?
12. Why is `OCRRequiredError` preferable to silently accepting an empty PDF?
13. When is pgvector preferable to adding a separate VDB?
14. If a stale external VDB returns a deleted point, what is the final correctness fence?
15. What sequence safely changes from 384 to 768 dimensions?

## Answer key

1. PostgreSQL owns authoritative lifecycle/text/vector/version/outbox state; Redis cache may be
   flushed and rebuilt.
2. The first check avoids expensive duplicate work; the transactional recheck plus unique index
   resolves concurrent races.
3. Chunk removal, `DELETING` status, knowledge-base version increment, and durable outbox insert.
4. The event is retried; idempotent `missing_ok` deletion succeeds and completion can commit.
5. `<=>` with `vector_cosine_ops`.
6. Unit norms make the cosine denominator one, leaving the dot product.
7. Graph degree/build complexity, construction search effort, and query search effort.
8. Number of learned partitions and number of partitions visited per query.
9. The size of the approximate/exact top-k intersection divided by `k`, averaged over queries.
10. To forbid matches across changed knowledge or incompatible vector/answer recipes.
11. So a hit skips retrieval and answer generation and returns the same public contract directly.
12. It makes missing capability observable and prevents an empty, misleading searchable record.
13. When transactional co-location, operational simplicity, relational filters, and present scale
    matter more than specialized distributed vector features.
14. Re-read/hydrate through PostgreSQL and expose only documents whose status is `READY`.
15. Add v2 storage, backfill, build matching indexes/cache, shadow-evaluate, switch reads, observe,
    and remove v1 later.

## Graduation task

Write a one-page architecture decision record with:

- workload size and growth;
- correctness invariants;
- chosen metric and normalization;
- exact/HNSW/IVFFlat evidence;
- cache threshold evidence;
- PDF support tier;
- deletion crash analysis;
- why pgvector is sufficient or why an external VDB is justified.

If the decision cites your measurements instead of product popularity, this guide has done its job.
