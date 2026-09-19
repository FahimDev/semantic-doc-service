"""Helpers shared by the demo scripts (seeding and visualization)."""

from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from app.core.config import get_settings


@lru_cache
def _model() -> Any:
    # Imported lazily: loading torch takes seconds and is pointless for --help or --reset.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embedding_model)


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    # Unit-length vectors make cosine distance and inner product rank identically.
    vectors = _model().encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
    return [[float(value) for value in vector] for vector in vectors]
