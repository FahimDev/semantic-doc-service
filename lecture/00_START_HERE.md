# Vector Search Mastery Lab — Start Here

This ZIP contains **only learning material**. You will create the application yourself, one
file at a time, by following the numbered Markdown chapters.

The project you will build is **PolicyVault**: a FastAPI API that accepts `.txt`, `.md`, and
text-based `.pdf` documents, chunks and embeds their text, stores metadata and vectors in
PostgreSQL with pgvector, searches them, deletes them safely, and serves semantically similar
answers from Redis cache.

## What “complete” means

At the end, you will be able to:

- explain why FastAPI/Python is the better learning backend for this project;
- manage Python and every dependency using `uv`;
- validate configuration and HTTP data with Pydantic;
- model authoritative relational and vector state in one PostgreSQL transaction;
- parse TXT, Markdown, and text-layer PDFs behind a replaceable interface;
- preserve PDF page provenance while chunking;
- explain dimensions, cosine distance/similarity, L2 distance, and inner product;
- implement exact nearest-neighbor search with pgvector;
- build and tune HNSW and IVFFlat ANN indexes;
- distinguish a B-tree index from a vector index;
- implement retry-safe upload and ACID-aware document deletion;
- use a transactional outbox for file cleanup and future external-VDB cleanup;
- create a Redis vector index for semantic caching;
- return a complete cached answer without repeating retrieval or answer generation;
- test the important boundaries and benchmark recall versus latency;
- extend the parser later with OCR or layout-aware PDF extraction.

## The final API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/documents` | Upload, parse, chunk, embed, and persist |
| `GET` | `/api/v1/documents` | List active documents |
| `GET` | `/api/v1/documents/{id}` | Inspect lifecycle state |
| `DELETE` | `/api/v1/documents/{id}` | Delete vectors atomically and schedule file cleanup |
| `GET` | `/api/v1/search` | Search with cosine, L2, or inner product |
| `POST` | `/api/v1/ask` | Semantic-cache lookup, retrieval, answer, and cache write |
| `GET` | `/health/live` | Process health |
| `GET` | `/health/ready` | PostgreSQL and Redis status |

## How to use the guide

1. Read chapters in numeric order.
2. Type each code block yourself. Copy only when you are correcting a typo.
3. Every code listing starts with an exact relative path such as
   `policy-vault/app/core/config.py`.
4. Run every checkpoint command before continuing.
5. When a checkpoint fails, compare the exception with the chapter’s troubleshooting section.
6. Commit after each chapter so that experiments are reversible.
7. Keep a small lab journal with your prediction, observation, and explanation.

Use this journal template:

```text
Experiment:
Prediction:
Command/input:
Observed result:
Why it happened:
What I will change next:
```

## Chapter map

| Chapter | Build outcome |
|---:|---|
| 01 | Architecture, state ownership, and core theory |
| 02 | `uv` project, dependencies, quality tooling, directories |
| 03 | Dockerized PostgreSQL/pgvector and Redis |
| 04 | Pydantic settings, domain values, and clean-code ports |
| 05 | SQLAlchemy engine, ORM schema, and repositories |
| 06 | Alembic migration and schema inspection |
| 07 | TXT/Markdown/PDF parser boundary |
| 08 | Page-aware chunking, embeddings, and file storage |
| 09 | Upload use case and authoritative state |
| 10 | Vector mathematics and exact pgvector search |
| 11 | HNSW, IVFFlat, ANN tuning, and VDB comparison |
| 12 | ACID deletion and transactional outbox worker |
| 13 | Redis vector semantic-cache adapter |
| 14 | Ask flow and complete-answer caching |
| 15 | FastAPI routes, dependency injection, and lifespan |
| 16 | Unit/integration tests, linting, typing, and CI |
| 17 | Recall/latency benchmark experiments |
| 18 | Six-hour execution plan |
| 19 | PDF OCR/layout and external-VDB extension path |
| 20 | Ordered command cheat sheet |
| 21 | Primary references and next mastery exercises |

## Time expectation

The guided first build is designed for approximately six focused hours if Python, SQL, and
Docker are already familiar. That creates a solid working understanding—not permanent mastery.
For mastery, repeat the benchmark and extension exercises over several sessions.

## Important scope decisions

- PostgreSQL is the source of truth. Redis is disposable.
- The first PDF adapter handles selectable text, not scans.
- The first answer provider is extractive and deterministic. It makes semantic-cache behavior
  observable without requiring a paid LLM key.
- The web API runs locally through `uv`; only PostgreSQL and Redis are Dockerized.
- Embedding dimension is fixed at 384. Changing the model dimension requires a schema migration.

Continue with `01_ARCHITECTURE_AND_THEORY.md`.

