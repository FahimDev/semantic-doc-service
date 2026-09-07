# 08 — Chunking, Embeddings, and File Storage

**Working directory:** `policy-vault/`  
**Build output:** page-aware passages, normalized vectors, and safe raw-file storage

## 1. Page-aware overlapping chunker

Chunking changes retrieval quality. Too large: one vector mixes unrelated ideas. Too small: the
passage loses context. Overlap protects meaning at boundaries but increases storage and duplicate
results.

This implementation never crosses a PDF page and preserves source character offsets.

**File:** `policy-vault/app/infrastructure/chunking.py`

```python
"""Deterministic page-local chunking with overlap and source offsets."""

from app.domain.models import ParsedDocument, TextChunk


class TextChunker:
    def __init__(self, chunk_size: int = 800, overlap: int = 120) -> None:
        if chunk_size < 100:
            raise ValueError("chunk_size must be at least 100")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be non-negative and smaller than chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split(self, document: ParsedDocument) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        chunk_index = 0
        for page in document.pages:
            text = page.text
            start = 0
            while start < len(text):
                end = self._choose_end(text, start)
                raw = text[start:end]
                left_trimmed = len(raw) - len(raw.lstrip())
                right_trimmed = len(raw.rstrip())
                content = raw.strip()
                if content:
                    content_start = start + left_trimmed
                    chunks.append(
                        TextChunk(
                            page_number=page.page_number,
                            chunk_index=chunk_index,
                            char_start=content_start,
                            char_end=start + right_trimmed,
                            content=content,
                        )
                    )
                    chunk_index += 1
                if end >= len(text):
                    break
                # Overlap repeats context, while the fallback guarantees forward progress.
                next_start = max(0, end - self.overlap)
                start = next_start if next_start > start else end
        return chunks

    def _choose_end(self, text: str, start: int) -> int:
        hard_end = min(start + self.chunk_size, len(text))
        if hard_end == len(text):
            return hard_end

        # Avoid tiny chunks by looking for a natural boundary only in the latter half.
        minimum = start + max(1, self.chunk_size // 2)
        window = text[minimum:hard_end]
        for separator in ("\n\n", ". ", "\n", " "):
            boundary = window.rfind(separator)
            if boundary != -1:
                return minimum + boundary + len(separator)
        return hard_end
```

## 2. Embedding adapters

`all-MiniLM-L6-v2` emits 384-dimensional vectors. We normalize output, making cosine similarity
and dot product rank equivalently. The test adapter uses feature hashing; it verifies plumbing but
is not a semantic model.

**File:** `policy-vault/app/infrastructure/embedding.py`

```python
"""Production semantic embeddings plus a dependency-light deterministic test fake."""

import hashlib
import math
import re
import threading
from collections.abc import Sequence
from typing import Any

import numpy as np

from app.core.errors import EmbeddingConfigurationError


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, dimensions: int) -> None:
        self._model_name = model_name
        self._dimensions = dimensions
        self._model: Any | None = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _load(self) -> Any:
        # Lazy loading keeps imports/tests fast; the FastAPI lifespan can warm it once.
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                    except ImportError as exc:
                        raise EmbeddingConfigurationError(
                            "sentence-transformers is not installed"
                        ) from exc
                    model = SentenceTransformer(self._model_name)
                    actual = model.get_sentence_embedding_dimension()
                    if actual != self._dimensions:
                        raise EmbeddingConfigurationError(
                            f"Model emits {actual} dimensions; schema expects {self._dimensions}"
                        )
                    self._model = model
        return self._model

    def warm_up(self) -> None:
        self._load()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        values = self._load().encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        # Float32 halves memory versus float64 and matches DB/cache index configuration.
        return np.asarray(values, dtype=np.float32).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class HashingEmbedder:
    """Deterministic fake for unit tests; never claim it provides semantic quality."""

    def __init__(self, dimensions: int = 384) -> None:
        self._dimensions = dimensions

    @property
    def name(self) -> str:
        return "hashing-test-embedder"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def warm_up(self) -> None:
        return None

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        values = [0.0] * self._dimensions
        for token in re.findall(r"\w+", text.casefold()):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self._dimensions
            values[bucket] += 1.0 if digest[0] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]
```

## 3. Atomic local storage adapter

The database stores a key, not an absolute path. A temporary file is fully flushed before
`os.replace`, preventing readers from seeing a partially written upload.

**File:** `policy-vault/app/infrastructure/storage.py`

```python
"""Local storage for the lab, replaceable later with S3-compatible object storage."""

import os
import tempfile
from pathlib import Path
from uuid import uuid4


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    def prepare(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, suffix: str) -> str:
        self.prepare()
        safe_suffix = suffix.lower() if suffix.lower() in {".txt", ".md", ".pdf"} else ".bin"
        storage_key = f"{uuid4().hex}{safe_suffix}"
        destination = self._resolve(storage_key)
        descriptor, temporary_name = tempfile.mkstemp(prefix="upload-", dir=self._root)
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(data)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            # Atomic rename within one filesystem exposes either no file or the complete file.
            os.replace(temporary_name, destination)
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        return storage_key

    def delete(self, storage_key: str) -> None:
        # missing_ok makes retrying a completed delete safe (idempotent).
        self._resolve(storage_key).unlink(missing_ok=True)

    def _resolve(self, storage_key: str) -> Path:
        candidate = (self._root / storage_key).resolve()
        # Never allow a storage key such as ../../secret to escape the upload directory.
        if candidate.parent != self._root:
            raise ValueError("Invalid storage key")
        return candidate
```

## Checkpoint

```bash
uv run ruff check app/infrastructure
uv run python -c "from pathlib import Path; from app.infrastructure.parsers import Utf8TextParser; from app.infrastructure.chunking import TextChunker; from app.infrastructure.embedding import HashingEmbedder; p=Path('sample_data/handbook.txt'); d=Utf8TextParser().parse(p.name,'text/plain',p.read_bytes()); c=TextChunker(200,30).split(d); v=HashingEmbedder().embed_documents([x.content for x in c]); print(len(c), len(v), len(v[0]))"
```

The last printed value must be `384`.

### Experiment

Repeat with chunk size `100`, `200`, and `800`. Record:

- number of chunks;
- repeated text caused by overlap;
- whether each chunk still answers one coherent question.

Commit:

```bash
git add app/infrastructure
git commit -m "feat: add chunk embedding and storage adapters"
```

Continue with `09_DOCUMENT_UPLOAD_USE_CASE.md`.
