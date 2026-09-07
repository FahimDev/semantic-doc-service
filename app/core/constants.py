""" Schema-level constants share across layers.
Embedding dimensions are not a casual runtime option: PostgresSQL declares vector (384),
Redis declares DIM=384, and model must emit 384 values.
"""

from uuid import UUID

DEFAULT_KNOWLEDGE_BASE_ID = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSIONS = 384
SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".pdf"})