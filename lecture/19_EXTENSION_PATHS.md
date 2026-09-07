# 19 — Extension Paths: OCR, Layout, External VDBs, and New Dimensions

**Working directory:** `policy-vault/`  
**Build output:** a safe plan for growth without rewriting the use cases

The core project already accepts text-layer PDFs. This chapter shows why the parser boundary,
outbox, lifecycle status, and embedding recipe were designed as extension points.

## 1. Add OCR without changing document ingestion

`pypdf` extracts an existing text layer; it does not recognize letters inside images. OCR adds
rasterization, language packs, CPU cost, timeouts, and quality evaluation. Keep that complexity
behind the same `DocumentParser` contract.

### Add an OCR engine port

**File to edit:** `policy-vault/app/application/ports.py`

Add `ParsedPage` to the existing domain import:

```python
from app.domain.models import ParsedDocument, ParsedPage, SearchHit
```

Then add this protocol after `DocumentParser`:

```python
class OcrEngine(Protocol):
    """Vendor-independent page OCR; a concrete adapter may run locally or remotely."""

    def extract_pages(self, data: bytes, max_pages: int) -> tuple[ParsedPage, ...]: ...
```

### Add a tiered PDF adapter

**File:** `policy-vault/app/infrastructure/ocr.py`

```python
"""Optional OCR fallback that preserves the original parser contract."""

from pathlib import Path

from app.application.ports import DocumentParser, OcrEngine
from app.core.errors import InvalidDocumentError, OCRRequiredError
from app.domain.models import ParsedDocument


class OcrPdfParser:
    name = "ocr-pdf"

    def __init__(self, engine: OcrEngine, max_pages: int) -> None:
        self.engine = engine
        self.max_pages = max_pages

    def supports(self, filename: str, content_type: str, data: bytes) -> bool:
        del content_type, data
        return Path(filename).suffix.lower() == ".pdf"

    def parse(self, filename: str, content_type: str, data: bytes) -> ParsedDocument:
        del filename, content_type
        if not data.startswith(b"%PDF-"):
            raise InvalidDocumentError("A .pdf upload must have a valid PDF signature")
        pages = self.engine.extract_pages(data, self.max_pages)
        if not pages or not any(page.text.strip() for page in pages):
            raise InvalidDocumentError("OCR completed but produced no usable text")
        return ParsedDocument(
            pages=pages,
            metadata={"parser": self.name, "ocr": True, "pdf_pages": len(pages)},
        )


class TieredPdfParser:
    """Use cheap text extraction first and invoke OCR only for image-only PDFs."""

    name = "tiered-pdf"

    def __init__(
        self, text_parser: DocumentParser, ocr_parser: DocumentParser
    ) -> None:
        self.text_parser = text_parser
        self.ocr_parser = ocr_parser

    def supports(self, filename: str, content_type: str, data: bytes) -> bool:
        return self.text_parser.supports(filename, content_type, data)

    def parse(self, filename: str, content_type: str, data: bytes) -> ParsedDocument:
        try:
            return self.text_parser.parse(filename, content_type, data)
        except OCRRequiredError:
            return self.ocr_parser.parse(filename, content_type, data)
```

Now the `DocumentService` remains unchanged. In the composition root, replace only the concrete
PDF parser:

```python
pdf_parser = TieredPdfParser(
    PdfTextParser(max_pages=settings.max_pdf_pages),
    OcrPdfParser(your_ocr_engine, max_pages=settings.max_pdf_pages),
)
parser_registry = ParserRegistry((Utf8TextParser(), pdf_parser))
```

`your_ocr_engine` is intentionally a dependency, not a hidden library call. You can implement it
with a local engine or a cloud document service without changing chunking, embedding, storage,
upload, search, or deletion.

### Prove fallback behavior with a fake

**File to edit:** `policy-vault/tests/unit/test_parsers.py`

Add imports:

```python
from app.domain.models import ParsedPage
from app.infrastructure.ocr import OcrPdfParser, TieredPdfParser
```

Add the test:

```python
class FakeOcrEngine:
    def extract_pages(self, data: bytes, max_pages: int) -> tuple[ParsedPage, ...]:
        assert data.startswith(b"%PDF-")
        assert max_pages == 100
        return (ParsedPage(page_number=1, text="Recovered scan text"),)


def test_tiered_pdf_parser_falls_back_to_ocr() -> None:
    parser = TieredPdfParser(
        PdfTextParser(max_pages=100),
        OcrPdfParser(FakeOcrEngine(), max_pages=100),
    )

    parsed = parser.parse("scan.pdf", "application/pdf", make_pdf(None))

    assert parsed.pages[0].text == "Recovered scan text"
    assert parsed.metadata["ocr"] is True
```

When you choose OCRmyPDF, add it as an optional dependency rather than burdening every install:

```bash
uv add --optional ocr ocrmypdf
uv sync --extra ocr
```

OCRmyPDF uses Tesseract and a PDF rasterizer and therefore has operating-system dependencies. Read
its installation guide before writing that concrete adapter. Run expensive OCR in a durable job
for large files; an in-process FastAPI background task does not survive a process crash.

### Decide when layout needs another adapter

Escalate from plain page text when evaluation shows damage from:

- mixed multi-column reading order;
- repeated headers and footers;
- tables whose row/column relationships matter;
- captions separated from figures;
- required bounding-box citations.

A layout-aware parser can still return `ParsedDocument`, but extend `ParsedPage` or `TextChunk`
with optional block/bounding-box metadata. Make that a migration and contract change, not an
unstructured dictionary convention.

Official background:

- [pypdf: why extraction is hard and why it is not OCR](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)
- [OCRmyPDF: OCR architecture](https://ocrmypdf.readthedocs.io/en/latest/introduction.html)
- [OCRmyPDF installation and system dependencies](https://ocrmypdf.readthedocs.io/en/latest/installation.html)
- [PyMuPDF: reading-order extraction options](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)

## 2. Move from pgvector-only to an external VDB safely

Do not dual-write PostgreSQL and a VDB inside one HTTP request and call it atomic. Neither system
can roll back the other. Extend the existing outbox instead.

### Recommended migration stages

| Stage | PostgreSQL | External VDB | Search path |
|---|---|---|---|
| 0 | source of truth, text + vectors | absent | pgvector |
| 1 | source of truth, text + vectors + outbox | idempotent mirror | pgvector; compare VDB offline |
| 2 | source of truth for lifecycle/text | searchable mirror | VDB candidate IDs, PostgreSQL authorization/hydration |
| 3 | source of truth for lifecycle/text/recipe | vector owner | VDB, always post-filtered by PostgreSQL state |

Stage 1 is the safest learning extension because pgvector remains the recovery baseline.

### Expand the port deliberately

**File to edit:** `policy-vault/app/application/ports.py`

Replace the current `ExternalVectorStore` protocol when you are ready to mirror writes:

```python
@dataclass(frozen=True, slots=True)
class ExternalVectorPoint:
    id: UUID
    document_id: UUID
    embedding: tuple[float, ...]
    metadata: dict[str, str | int]


class ExternalVectorStore(Protocol):
    def upsert_document(self, points: Sequence[ExternalVectorPoint]) -> None: ...

    def delete_document(self, document_id: UUID) -> None: ...
```

The adapter must use deterministic point IDs and upsert semantics. Retrying an event after a
network timeout must converge on the same state rather than duplicate points.

### State and event rules

On upload, commit the authoritative PostgreSQL rows and a `DOCUMENT_VECTORS_UPSERT` outbox event
together. The worker reads the durable chunks, upserts them, then marks the event complete.

On delete:

1. lock the document in PostgreSQL;
2. set it to `DELETING`, remove local authoritative chunks if still appropriate, bump cache
   version, and insert `DOCUMENT_VECTORS_DELETE` in one commit;
3. immediately reject any external result whose PostgreSQL document is not `READY`;
4. let the worker idempotently delete VDB points and the raw file;
5. mark the document `DELETED` only after side effects succeed.

This final PostgreSQL status check is a correctness fence: a briefly stale VDB can return an ID,
but the API must not expose it.

### Add reconciliation

A retrying outbox handles known work. Reconciliation detects unknown drift caused by defects,
manual changes, expired events, or damaged systems. Periodically compare:

- READY document IDs and expected chunk counts in PostgreSQL;
- point counts grouped by document ID in the VDB;
- embedding recipe/model version;
- completed delete events versus lingering VDB points.

Repair by re-upserting or deleting through the same idempotent adapter. Alert on drift before
repairing silently in production.

## 3. Change embedding dimensions with a blue/green migration

Never point a 768-dimensional model at a `vector(384)` column or a Redis index with `DIM 384`.
Treat model, dimension, normalization, metric, and chunking settings as one versioned recipe.

Safe sequence:

1. add a new column/table such as `embedding_v2 vector(768)`;
2. backfill it in restartable batches while recording recipe version;
3. create the matching HNSW/IVFFlat index;
4. create a new Redis index name with `DIM 768`;
5. compare retrieval results and recall with shadow queries;
6. switch reads to v2 behind configuration;
7. include the v2 model/provider version in cache scope;
8. stop v1 writes, observe, then remove v1 in a later migration.

Avoid altering a populated vector column in place. Blue/green state permits rollback and makes
mixed-model records visible.

## 4. Make ingestion asynchronous when documents grow

The six-hour app returns only after parsing and embedding. For large PDFs:

- upload bytes atomically;
- insert a document with `PROCESSING` status and an ingestion outbox job;
- return HTTP `202` with the document ID;
- let a worker parse/chunk/embed in bounded batches;
- commit chunks and transition to `READY` only when the full recipe succeeds;
- store a structured failure reason and permit a retry.

Search still filters `READY`, so partial ingestion never leaks. This is the same lifecycle pattern
you learned through deletion.

## 5. Add React only after the backend contract is stable

If you want a MERN-like user experience later, add a small React client for upload progress,
document state, search controls, sources, and cache-hit indicators. Keep PostgreSQL, Redis, and
embedding logic behind FastAPI. The browser should never hold database credentials or talk
directly to the vector store.

## Extension checkpoint

You understand the architecture when you can add the fake OCR fallback test without editing
`DocumentService`, and can draw a crash timeline showing why every external VDB write/delete must
be idempotent and outbox-driven.

Continue with `20_ORDERED_COMMANDS.md`.
