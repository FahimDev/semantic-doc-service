# Vector Search Project Summary

## What this project is
This project is a **document intelligence and semantic retrieval service** built around FastAPI, PostgreSQL + pgvector, and Redis.

It is designed to:
- accept user documents like `.txt`, `.md`, and text-based `.pdf` files;
- extract and chunk text in a provenance-aware way;
- create embeddings for semantic search;
- store authoritative document and vector state in PostgreSQL;
- expose exact and approximate vector search APIs;
- answer questions from retrieved context;
- cache complete answers semantically in Redis;
- delete documents safely with ACID-aware lifecycle handling.

In short: this is a **backend service for turning documents into searchable knowledge**.

## Why it exists
The lecture material is not just about vector search theory. It is a full build plan for a production-shaped service that teaches how to:
- keep PostgreSQL as the source of truth;
- treat Redis as disposable cache, not authoritative state;
- preserve document lifecycle integrity;
- benchmark exact versus ANN search;
- design the system so it can later grow into OCR, layout-aware parsing, or an external vector database.

## How to frame it as a service
The cleanest product framing is:

**"A reusable document retrieval and semantic Q&A API for any application that needs private knowledge search."**

That means this project can be used as a standalone service by other apps through HTTP, instead of being tied to one frontend or one domain.

### Service-style positioning
You can present it as:
- a **RAG-ready knowledge service**;
- a **document search API**;
- a **semantic answer backend**;
- a **private enterprise knowledge layer**;
- a **pluggable retrieval microservice**.

## What it does for other projects
Any app can integrate this service to:
- upload policy files, manuals, notes, or internal docs;
- search similar content using cosine, L2, or inner-product distance;
- ask natural-language questions against the uploaded corpus;
- reuse cached answers when the prompt and knowledge scope match;
- delete content safely without leaving stale vectors behind.

## Core capabilities
- **Document ingestion**: validates and stores uploaded files.
- **Parsing**: supports UTF-8 text, Markdown, and text-layer PDFs.
- **Chunking**: keeps chunks page-aware and provenance-preserving.
- **Embeddings**: converts chunks and queries into fixed-size vectors.
- **Vector storage**: stores chunks and embeddings in PostgreSQL with pgvector.
- **Search**: supports exact retrieval and ANN strategies like HNSW and IVFFlat.
- **Ask flow**: retrieves relevant passages and generates an answer.
- **Semantic cache**: reuses full answers for compatible prompts in Redis.
- **Deletion safety**: uses ACID rules and an outbox worker for cleanup.
- **Benchmarking**: compares recall, latency, and index trade-offs.

## Main architecture
- **FastAPI** handles HTTP transport.
- **Application services** own document ingestion, search, question answering, and outbox processing.
- **Ports and adapters** keep the domain isolated from infrastructure libraries.
- **PostgreSQL** stores document state, chunk text, vectors, and lifecycle metadata.
- **Redis** stores semantic cache entries and can be safely rebuilt.
- **Local file storage** holds uploaded source files in the lab version.

## Good use cases
This service fits projects like:
- internal knowledge bases;
- policy or compliance search;
- support article retrieval;
- document Q&A tools;
- engineering handbook search;
- private workspace assistants;
- research note explorers;
- contract and SOP lookup systems.

## What makes it reusable
The project is structured to work as a service in any app because it already separates:
- transport from business logic;
- parsing from chunking;
- retrieval from answer generation;
- authoritative state from cache state;
- database behavior from future storage backends.

That makes it easy to swap in:
- a different frontend;
- a different embedding model;
- a different answer provider;
- OCR for scanned PDFs;
- an external vector database later.


## Best short description
If you need one sentence for the repo description:

**Private document retrieval and semantic Q&A API with PostgreSQL pgvector, Redis cache, and safe document lifecycle management.**

## If you want to productize it
A strong next-step product pitch would be:

**"Drop-in knowledge search as a service for any app."**

That framing makes the project feel like an infrastructure layer, not just a tutorial.
