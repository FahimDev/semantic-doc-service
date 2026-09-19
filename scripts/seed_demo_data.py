"""Load the demo corpus into PostgreSQL so the vector visualizations have something to show.

    uv run python -m scripts.seed_demo_data            # add demo documents that are missing
    uv run python -m scripts.seed_demo_data --reset    # delete demo documents, then re-add them

This is a demo shortcut, not the upload pipeline: it goes through the real parsers and ORM rows,
but chunks with a naive one-paragraph-per-chunk rule and embeds with the configured model.
"""

import argparse
import hashlib
import re
from pathlib import Path

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.constants import DEFAULT_KNOWLEDGE_BASE_ID
from app.domain.models import DocumentStatus, ParsedPage, TextChunk
from app.infrastructure.database import build_engine, build_session_factory
from app.infrastructure.orm import ChunkRow, DocumentRow
from app.infrastructure.parsers import ParserRegistry, PdfTextParser, Utf8TextParser
from app.infrastructure.repositories import KnowledgeBaseRepository
from scripts.demo_common import embed_texts

DEMO_DIR = Path("sample_data/demo")
STORAGE_PREFIX = "demo/"

# A paragraph runs from a non-blank character up to the next blank line.
PARAGRAPH = re.compile(r"\S.*?(?=\n\s*\n|\Z)", re.DOTALL)


def paragraph_chunks(page: ParsedPage) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    heading_start: int | None = None
    for match in PARAGRAPH.finditer(page.text):
        block = match.group().rstrip()
        if block.startswith("#"):
            # A heading alone says little, so it travels with the paragraph that follows it.
            heading_start = match.start() if heading_start is None else heading_start
            continue
        start = match.start() if heading_start is None else heading_start
        end = match.start() + len(block)
        heading_start = None
        chunks.append(TextChunk(page.page_number, len(chunks), start, end, page.text[start:end]))
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="delete demo documents first")
    args = parser.parse_args()

    settings = get_settings()
    registry = ParserRegistry((Utf8TextParser(), PdfTextParser(settings.max_pdf_pages)))
    engine = build_engine(settings.database_url)
    added = 0

    with build_session_factory(engine)() as session:
        if args.reset:
            # Chunks disappear with their documents through ON DELETE CASCADE.
            session.execute(delete(DocumentRow).where(DocumentRow.storage_key.like("demo/%")))
        existing = dict(
            session.execute(
                select(DocumentRow.storage_key, DocumentRow.sha256).where(
                    DocumentRow.storage_key.like("demo/%")
                )
            )
            .tuples()
            .all()
        )

        for path in sorted(DEMO_DIR.glob("*.md")):
            data = path.read_bytes()
            sha256 = hashlib.sha256(data).hexdigest()
            key = f"{STORAGE_PREFIX}{path.name}"
            if key in existing:
                if existing[key] != sha256:
                    raise SystemExit(f"{path.name} changed since it was loaded; use --reset")
                print(f"skip   {path.name} (already loaded)")
                continue

            parsed = registry.parse(path.name, "text/markdown", data)
            chunks = [chunk for page in parsed.pages for chunk in paragraph_chunks(page)]
            vectors = embed_texts([chunk.content for chunk in chunks])
            document = DocumentRow(
                knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                filename=path.name,
                content_type="text/markdown",
                storage_key=key,
                sha256=sha256,
                status=DocumentStatus.READY.value,
                page_count=len(parsed.pages),
                metadata_json=dict(parsed.metadata),
            )
            document.chunks = [
                ChunkRow(
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    content=chunk.content,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            session.add(document)
            added += 1
            print(f"added  {path.name}: {len(chunks)} chunks")

        if added or args.reset:
            # Searchable knowledge changed, so anything cached against the old version is stale.
            KnowledgeBaseRepository(session).bump_version(DEFAULT_KNOWLEDGE_BASE_ID)
        session.commit()

    engine.dispose()
    print(f"done: {added} document(s) added")


if __name__ == "__main__":
    main()
