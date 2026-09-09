"""Schema-level constants shared across layers.

Embedding dimensions are not a casual runtime option: PostgreSQL declares
vector(384), Redis declares DIM=384, and the embedding model must emit exactly
384 values so every layer agrees on the same vector shape.
"""

from uuid import UUID

# This is a stable sentinel UUID used as the default knowledge base identifier.
# The all-zero prefix makes it obvious this value is synthetic, while still being a valid UUID.
DEFAULT_KNOWLEDGE_BASE_ID = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
# 384 is the output size of this model, and it must match both pgvector and Redis index settings.
EMBEDDING_DIMENSIONS = 384
# https://redis.io/docs/latest/develop/use-cases/semantic-cache/redis-py/
SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".pdf"})