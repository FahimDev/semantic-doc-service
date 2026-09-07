# 16 — Tests, Quality Gates, and CI

**Working directory:** `policy-vault/`  
**Build output:** fast unit tests, one real service test, and a reproducible CI gate

Use the testing pyramid intentionally:

| Layer | Real dependencies | What it proves |
|---|---|---|
| Unit | None | parsing rules, offsets, normalization, path safety, cache scope |
| Integration | PostgreSQL/pgvector + Redis | migration, transactions, vector SQL, cache KNN, worker |
| Manual semantic evaluation | Real embedding model | whether similarity quality is useful |

A fake embedding can prove shape and control flow. It cannot prove semantic quality.

## 1. Test chunk provenance

**File:** `policy-vault/tests/unit/test_chunking.py`

```python
"""Chunk boundaries must remain traceable to their exact source page text."""

from app.domain.models import ParsedDocument, ParsedPage
from app.infrastructure.chunking import TextChunker


def test_chunks_preserve_offsets_and_page_boundaries() -> None:
    first = "Alpha sentence. " * 20
    second = "Beta sentence. " * 20
    document = ParsedDocument(
        pages=(ParsedPage(1, first), ParsedPage(2, second))
    )

    chunks = TextChunker(chunk_size=100, overlap=20).split(document)

    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        source = first if chunk.page_number == 1 else second
        assert source[chunk.char_start : chunk.char_end] == chunk.content


def test_empty_pages_do_not_create_empty_chunks() -> None:
    document = ParsedDocument(pages=(ParsedPage(1, "   \n"),))
    assert TextChunker().split(document) == []
```

## 2. Test text and real PDF bytes

`reportlab` creates a PDF with a real text layer entirely in memory. That tests your pypdf adapter
without committing a binary fixture.

**File:** `policy-vault/tests/unit/test_parsers.py`

```python
"""Parser contract tests, including the visible boundary between extraction and OCR."""

from io import BytesIO

import pytest
from reportlab.pdfgen.canvas import Canvas

from app.core.errors import InvalidDocumentError, OCRRequiredError
from app.infrastructure.parsers import PdfTextParser, Utf8TextParser


def make_pdf(text: str | None) -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    if text is not None:
        canvas.drawString(72, 750, text)
    canvas.showPage()
    canvas.save()
    return output.getvalue()


def test_utf8_parser_preserves_text() -> None:
    parsed = Utf8TextParser().parse("notes.md", "text/markdown", b"# ACID\nAtomicity")
    assert parsed.pages[0].text == "# ACID\nAtomicity"
    assert parsed.metadata["parser"] == "utf8-text"


def test_utf8_parser_rejects_binary_data() -> None:
    with pytest.raises(InvalidDocumentError):
        Utf8TextParser().parse("notes.txt", "text/plain", b"hello\x00world")


def test_pdf_parser_extracts_text_and_page_number() -> None:
    parsed = PdfTextParser().parse(
        "policy.pdf", "application/pdf", make_pdf("Annual learning budget is 1200 USD")
    )
    assert parsed.pages[0].page_number == 1
    assert "learning budget" in parsed.pages[0].text


def test_blank_pdf_requires_a_future_ocr_adapter() -> None:
    with pytest.raises(OCRRequiredError):
        PdfTextParser().parse("scan.pdf", "application/pdf", make_pdf(None))
```

## 3. Test embeddings, storage, settings, and cache scope

**File:** `policy-vault/tests/unit/test_foundations.py`

```python
"""Deterministic checks for boundaries that do not need network services."""

import math
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.application.question_service import semantic_cache_scope
from app.core.config import Settings
from app.infrastructure.embedding import HashingEmbedder
from app.infrastructure.storage import LocalFileStorage


def test_hashing_embedder_is_normalized_and_repeatable() -> None:
    embedder = HashingEmbedder(dimensions=32)
    first = embedder.embed_query("ACID transaction")
    second = embedder.embed_query("ACID transaction")

    assert first == second
    assert len(first) == 32
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)


def test_storage_save_delete_and_traversal_guard(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path / "uploads")
    key = storage.save(b"evidence", ".txt")

    assert (storage.root / key).read_bytes() == b"evidence"
    storage.delete(key)
    storage.delete(key)  # A retry remains successful.
    with pytest.raises(ValueError):
        storage.delete("../outside.txt")


def test_settings_reject_non_advancing_chunks() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, chunk_size=200, chunk_overlap=200)


def test_cache_scope_changes_with_every_compatibility_boundary() -> None:
    knowledge_base_id = uuid4()
    base = semantic_cache_scope(knowledge_base_id, 1, "model-a", "answer-v1")

    assert base != semantic_cache_scope(knowledge_base_id, 2, "model-a", "answer-v1")
    assert base != semantic_cache_scope(knowledge_base_id, 1, "model-b", "answer-v1")
    assert base != semantic_cache_scope(knowledge_base_id, 1, "model-a", "answer-v2")
    assert base != semantic_cache_scope(
        knowledge_base_id, 1, "model-a", "answer-v1", tenant="another-tenant"
    )
```

Run the fast suite now:

```bash
uv run ruff format app scripts tests alembic
uv run ruff check app scripts tests alembic
uv run mypy app scripts
uv run pytest tests/unit --cov=app --cov-report=term-missing
```

Read uncovered lines; do not chase 100% coverage mechanically. Failure paths with business risk
matter more than a getter executed only to raise the number.

## 4. Add one end-to-end integration test

This test uses the hashing adapter for speed, but uses real PostgreSQL vector operators, Redis
Search, HTTP multipart parsing, lifecycle transitions, and the outbox worker.

**File:** `policy-vault/tests/integration/test_api_flow.py`

```python
"""One vertical test through HTTP, pgvector, Redis vector cache, and the outbox."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# The application reads these values lazily when TestClient enters lifespan.
os.environ["EMBEDDING_PROVIDER"] = "hashing"
os.environ["WARM_EMBEDDING_MODEL"] = "false"

from app.infrastructure.container import get_container
from app.main import app

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 after starting PostgreSQL and Redis",
)
def test_document_search_cache_and_delete_lifecycle() -> None:
    unique_fact = f"Project codename {uuid4().hex} uses a 1200 USD learning budget."
    question = f"What budget is stated for {unique_fact.split()[2]}?"

    with TestClient(app) as client:
        upload = client.post(
            "/api/v1/documents",
            files={"file": ("policy.txt", unique_fact.encode(), "text/plain")},
        )
        assert upload.status_code == 201, upload.text
        document_id = upload.json()["document"]["id"]

        search = client.get("/api/v1/search", params={"query": unique_fact, "limit": 5})
        assert search.status_code == 200, search.text
        assert document_id in {hit["document_id"] for hit in search.json()}

        first_answer = client.post("/api/v1/ask", json={"question": question})
        second_answer = client.post("/api/v1/ask", json={"question": question})
        assert first_answer.status_code == 200, first_answer.text
        assert second_answer.status_code == 200, second_answer.text
        assert second_answer.json()["cache_hit"] is True

        deleted = client.delete(f"/api/v1/documents/{document_id}")
        assert deleted.status_code == 202, deleted.text
        assert deleted.json()["status"] == "DELETING"

        # Drain earlier local events too, so rerunning the test does not depend on a clean DB.
        worker = get_container().build_outbox_service()
        for _ in range(100):
            worker.process_one()
            final = client.get(f"/api/v1/documents/{document_id}")
            if final.json()["status"] == "DELETED":
                break
        assert final.json()["status"] == "DELETED"

        after_delete = client.get(
            "/api/v1/search", params={"query": unique_fact, "limit": 20}
        )
        assert document_id not in {
            hit["document_id"] for hit in after_delete.json()
        }
```

Run it only after services and migrations are ready:

```bash
docker compose up -d
uv run alembic upgrade head
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -vv
```

PowerShell:

```powershell
$env:RUN_INTEGRATION_TESTS = "1"
uv run pytest -m integration -vv
```

## 5. Add CI

The action revisions below are pinned to immutable commit SHAs verified on 2026-09-03. The uv
version is pinned as well; update it deliberately and let the lock file show dependency changes.

**File:** `policy-vault/.github/workflows/ci.yml`

```yaml
name: ci

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:0.8.6-pg17
        env:
          POSTGRES_DB: policy_vault
          POSTGRES_USER: policy_vault
          POSTGRES_PASSWORD: policy_vault
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U policy_vault -d policy_vault"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 20
      redis:
        image: redis:8.2-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 20

    env:
      DATABASE_URL: postgresql+psycopg://policy_vault:policy_vault@localhost:5432/policy_vault
      REDIS_URL: redis://localhost:6379/0
      EMBEDDING_PROVIDER: hashing
      WARM_EMBEDDING_MODEL: "false"
      RUN_INTEGRATION_TESTS: "1"

    steps:
      - name: Check out source
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1

      - name: Install uv
        uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0
        with:
          version: "0.12.9"
          enable-cache: true

      - name: Install locked environment
        run: |
          uv python install
          uv sync --locked --all-groups

      - name: Migrate database
        run: uv run alembic upgrade head

      - name: Quality gates
        run: |
          uv lock --check
          uv run ruff format --check app scripts tests alembic
          uv run ruff check app scripts tests alembic
          uv run mypy app scripts

      - name: Test
        run: uv run pytest --cov=app --cov-report=term-missing
```

The workflow does not run the external model. That keeps CI deterministic. Semantic model quality
belongs in an explicit evaluation job with versioned datasets, not a unit-test assertion such as
“these two English sentences must always score above 0.88.”

## Checkpoint

```bash
uv lock --check
uv run ruff format --check app scripts tests alembic
uv run ruff check app scripts tests alembic
uv run mypy app scripts
uv run pytest --cov=app --cov-report=term-missing
```

Commit:

```bash
git add tests .github pyproject.toml uv.lock
git commit -m "test: cover parser vector cache and deletion boundaries"
```

Continue with `17_BENCHMARK_RECALL_AND_LATENCY.md`.
