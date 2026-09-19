from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make_settings(**overrides: Any) -> Settings:
    # _env_file=None keeps a developer's local .env from leaking into the test.
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_defaults_are_valid() -> None:
    settings = make_settings()

    assert settings.chunk_overlap < settings.chunk_size
    assert settings.embedding_dimensions == 384


def test_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(ValidationError, match="chunk_overlap"):
        make_settings(chunk_size=200, chunk_overlap=200)


def test_embedding_dimensions_are_locked_to_schema() -> None:
    with pytest.raises(ValidationError, match="vector schema"):
        make_settings(embedding_dimensions=768)
