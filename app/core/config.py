"""Typed configuration loaded from ./env and process environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import DEFAULT_EMBEDDING_MODEL, EMBEDDING_DIMENSIONS


class Settings(BaseSettings):
    # Environment variables override .env; unknown keys are ignored so the same code works locally and in containers.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env:str = "development"
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+psycopg://policy_vault:policy_vault@localhost:5432/policy_vault"
    )
    redis_url: str = "redis://localhost:6379/0"
    upload_dir: Path = Path("data/uploads")



    # Field constraints reject unsafe or nonsensical runtime values immediately.
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=100, gt=0, le=1000)
    chunk_size: int = Field(default=800, ge=100)
    chunk_overlap: int = Field(default=120, ge=0)

    embedding_provider: str = "sentence-transformer"
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = EMBEDDING_DIMENSIONS
    warm_embedding_model: bool = True

    semantic_cache_enabled: bool = True
    semantic_cache_ttl_seconds: int = Field(default=3600, gt=0)
    semantic_cache_distance_threshold: float = Field(default=0.12, ge=0, le=2)
    redis_cache_index: str = "idx:semantic-cache"
    redis_cache_prefix: str = "semantic-cache:"

    outbox_poll_seconds: float = Field(default=2.0, gt=0)
    outbox_lease_seconds: int = Field(default=60, gt=0)


    @model_validator(mode="after")
    def validate_cross_field_invariants(self) -> "Settings":
        # Overlap must advance; otherwise a chunk loop can never terminate.
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        # Changing dimensions requires a PostgreSQL migration and Redis index rebuild,
        # because both systems store/search vectors with the same fixed length.
        if self.embedding_dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError("change vector schema before changing embedding dimensions")
        return self


@lru_cache
def get_settings() -> Settings:
    # lru_cache turns Settings() into a process-wide singleton after the first successful validation.
    # That avoids re-parsing env vars on every access and keeps config reads consistent.
    return Settings()