# 18 — Six-Hour Core Build Plan

**Working directory:** follow the directory named in each chapter  
**Outcome:** one complete first pass through every requested concept

Six hours is realistic for a focused first build if you already know basic Python, SQL, Git, and
Docker. If two or more are new, use the same checkpoints over 10–14 hours. “Mastery” comes from
explaining failures and repeating experiments, not merely finishing the clock.

## Before the timer

Have these installed and working:

```bash
git --version
docker --version
docker compose version
uv --version
```

Download the sentence-transformer model only when the plan asks for it. Use the hashing adapter
first so a model download cannot consume the infrastructure learning block.

## The schedule

| Time | Chapters | Build target | Do not continue until |
|---|---|---|---|
| 00:00–00:40 | 01–03 | architecture, `uv`, PostgreSQL/pgvector, Redis | both service health checks pass |
| 00:40–01:25 | 04–06 | settings, domain/ports, ORM, migration | four tables and `vector(384)` exist |
| 01:25–02:10 | 07–08 | TXT/MD/PDF parsing, chunking, hashing embeddings, storage | sample becomes page-aware 384-D chunks |
| 02:10–02:55 | 09–10 | idempotent upload, vector math, exact search | duplicate upload returns one document |
| 02:55–03:35 | 11 + 17 small run | HNSW, IVFFlat, recall/latency | you can explain `ef_search` and `probes` |
| 03:35–04:20 | 12 | ACID delete and outbox worker | search hides content before file cleanup |
| 04:20–05:05 | 13–14 | Redis semantic cache and complete-answer hit | repeated identical prompt reports a hit |
| 05:05–05:35 | 15 | API composition, routes, lifespan | upload/search/ask/delete work through HTTP |
| 05:35–06:00 | 16 | unit suite and vertical integration test | quality commands are green |

Chapter 19 is deliberately after the timed core. Chapters 20–21 help you repeat and deepen it.

## How to work inside each block

Use a 3-step loop:

1. **Predict (20%)** — state what should happen and why.
2. **Build (60%)** — create only the named file/chunk and run its immediate command.
3. **Explain (20%)** — write the observation in your lab journal without copying the chapter.

If a command fails, read the first relevant traceback from the bottom upward. Spend at most ten
minutes before using the troubleshooting map below; do not blindly reinstall everything.

## Fast-lane environment

For hours 1–5, set:

```dotenv
EMBEDDING_PROVIDER=hashing
WARM_EMBEDDING_MODEL=false
```

This makes transactions, dimensions, vector SQL, deletion, Redis indexing, and API behavior fast
and deterministic. It does not demonstrate genuine semantic similarity.

At the end of hour 5, change back to:

```dotenv
EMBEDDING_PROVIDER=sentence-transformer
WARM_EMBEDDING_MODEL=true
```

Restart the API. The first startup may download the model. Because stored vectors must come from
one recipe, reset this disposable learning database before re-uploading:

```bash
docker compose down --volumes
docker compose up -d
uv run alembic upgrade head
```

That command deletes the lab’s local database and Redis volumes. Do not run it against data you
intend to keep.

## Required observations

Your six-hour result is complete only if your journal contains these ten observations:

1. the same bytes uploaded twice produce one active document;
2. every PDF chunk carries a page number;
3. a scanned/blank PDF produces an explicit OCR-required error;
4. a vector with the wrong dimension fails at a boundary;
5. normalized dot-product and cosine rankings agree;
6. exact results form ANN ground truth;
7. increasing HNSW `ef_search` or IVFFlat `probes` changes recall/latency;
8. delete removes searchable chunks in the DB commit;
9. the outbox safely retries file deletion;
10. an identical prompt returns the complete cached response while Redis failure still permits
    PostgreSQL search.

## Troubleshooting map

| Symptom | First diagnostic | Likely cause |
|---|---|---|
| PostgreSQL connection refused | `docker compose ps` | container not healthy or port conflict |
| `type "vector" does not exist` | `uv run alembic current` | migration not applied |
| Redis says unknown `FT.SEARCH` | `redis-cli COMMAND INFO FT.SEARCH` | image lacks Search capability |
| PDF returns `ocr_required` | try selecting/copying its text | image-only scan, not a parser bug |
| model dimension error | print `embedder.dimensions` and inspect `\d chunks` | model/schema mismatch |
| vector index not used | `EXPLAIN (ANALYZE, BUFFERS)` | tiny table, wrong operator class, or query shape |
| cache never hits | inspect distance, scope/version, Redis index | threshold too strict or scope changed |
| deleted result still searchable | inspect document status and query predicate | missing `status = 'READY'` filter |
| worker repeats a job | inspect `last_error` and storage key | side effect failed; retry is expected |
| import fails | `uv sync --locked` then `uv run python ...` | command ran outside the uv environment |

## End-of-session oral exam

Record a five-minute explanation, without notes, answering:

- Why is PostgreSQL authoritative while Redis is not?
- Where is the ACID boundary during upload and delete?
- Why can an outbox guarantee retry but not one atomic DB-plus-filesystem commit?
- When would you choose exact, HNSW, or IVFFlat?
- Why does a PDF adapter belong before chunking?
- Which values must enter a semantic-cache scope?

Anything you cannot explain identifies the chapter to revisit. Continue with
`19_EXTENSION_PATHS.md`.
