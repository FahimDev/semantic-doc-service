"""Render the chunk embeddings stored in pgvector as an interactive 2-D map.

    uv run python -m scripts.visualize_vectors
    uv run python -m scripts.visualize_vectors --query "how many vacation days do I get" --open
    uv run python -m scripts.visualize_vectors --projector

The page is one self-contained HTML file (no server, no network). With --query, the question is
embedded, PostgreSQL ranks the chunks by cosine distance (the same `<=>` operator search will
use), and the top hits are drawn on the map. --projector also writes TSV files that
https://projector.tensorflow.org can load to explore the raw 384 dimensions with UMAP or t-SNE.
"""

import argparse
import json
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import DEFAULT_KNOWLEDGE_BASE_ID
from app.domain.models import DocumentStatus
from app.infrastructure.database import build_engine, build_session_factory
from app.infrastructure.orm import ChunkRow, DocumentRow
from scripts.demo_common import embed_texts

TEMPLATE = Path(__file__).with_name("vector_map.html")
DEFAULT_OUT = Path("data/visualizations/vector_map.html")
# Hue x shape gives 12 distinguishable marks; documents beyond that fold into one "Other" series.
MAX_SERIES = 12


@dataclass(frozen=True, slots=True)
class ChunkPoint:
    filename: str
    page_number: int
    chunk_index: int
    content: str
    embedding: NDArray[np.float32]


def load_chunks(session: Session) -> list[ChunkPoint]:
    rows = session.execute(
        select(
            DocumentRow.filename,
            ChunkRow.page_number,
            ChunkRow.chunk_index,
            ChunkRow.content,
            ChunkRow.embedding,
        )
        .join(DocumentRow, DocumentRow.id == ChunkRow.document_id)
        .where(
            DocumentRow.knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID,
            DocumentRow.status == DocumentStatus.READY.value,
        )
        .order_by(DocumentRow.filename, ChunkRow.page_number, ChunkRow.chunk_index)
    ).all()
    return [
        ChunkPoint(name, page, index, content, np.asarray(embedding, dtype=np.float32))
        for name, page, index, content, embedding in rows
    ]


def nearest_chunks(
    session: Session, query_vector: list[float], k: int
) -> list[tuple[str, int, float]]:
    """Ask PostgreSQL for the k closest chunks; returns (filename, chunk_index, distance)."""
    distance = ChunkRow.embedding.cosine_distance(query_vector).label("distance")
    rows = session.execute(
        select(DocumentRow.filename, ChunkRow.chunk_index, distance)
        .join(DocumentRow, DocumentRow.id == ChunkRow.document_id)
        .where(
            DocumentRow.knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID,
            DocumentRow.status == DocumentStatus.READY.value,
        )
        .order_by(distance)
        .limit(k)
    ).all()
    return [(name, index, float(value)) for name, index, value in rows]


@dataclass(frozen=True, slots=True)
class Projection:
    mean: NDArray[np.float32]
    axes: NDArray[np.float32]  # (2, dimensions): the two directions with the most variance
    explained: tuple[float, float]

    def apply(self, vectors: NDArray[np.float32]) -> NDArray[np.float32]:
        return ((vectors - self.mean) @ self.axes.T).astype(np.float32)


def fit_pca(matrix: NDArray[np.float32]) -> Projection:
    """Principal component analysis via SVD; linear, deterministic, and dependency-free."""
    mean = matrix.mean(axis=0)
    _, singular, components = np.linalg.svd(matrix - mean, full_matrices=False)
    variance = singular**2
    share = variance / variance.sum()
    return Projection(mean, components[:2], (float(share[0]), float(share[1])))


def build_payload(
    points: list[ChunkPoint], query: str | None, top_k: int, session: Session
) -> dict[str, Any]:
    filenames = sorted({point.filename for point in points})
    # Colors follow the document, not its row, so a filtered view never repaints the survivors.
    series_of = {name: min(index, MAX_SERIES) for index, name in enumerate(filenames)}
    labels = [*filenames[:MAX_SERIES]]
    if len(filenames) > MAX_SERIES:
        labels.append(f"Other ({len(filenames) - MAX_SERIES} documents)")

    matrix = np.stack([point.embedding for point in points])
    projection = fit_pca(matrix)
    coords = projection.apply(matrix)

    payload: dict[str, Any] = {
        "explained": projection.explained,
        "series": [
            {"label": label, "count": sum(series_of[p.filename] == i for p in points)}
            for i, label in enumerate(labels)
        ],
        "points": [
            {
                "x": float(xy[0]),
                "y": float(xy[1]),
                "s": series_of[point.filename],
                "doc": point.filename,
                "page": point.page_number,
                "chunk": point.chunk_index,
                "text": point.content,
            }
            for point, xy in zip(points, coords, strict=True)
        ],
        "query": None,
    }

    if query:
        query_vector = embed_texts([query])[0]
        position = {(p.filename, p.chunk_index): i for i, p in enumerate(points)}
        hits = nearest_chunks(session, query_vector, top_k)
        query_xy = projection.apply(np.asarray([query_vector], dtype=np.float32))[0]
        payload["query"] = {
            "text": query,
            "x": float(query_xy[0]),
            "y": float(query_xy[1]),
            "hits": [
                {"point": position[(name, index)], "distance": distance}
                for name, index, distance in hits
            ],
        }
    return payload


def write_html(payload: dict[str, Any], out: Path) -> None:
    # "</" would let chunk text close the <script> element early.
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", data), encoding="utf-8")


def write_projector_files(points: list[ChunkPoint], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    vectors = ("\t".join(f"{value:.6f}" for value in point.embedding) for point in points)
    (directory / "vectors.tsv").write_text("\n".join(vectors) + "\n", encoding="utf-8")
    metadata = ["document\tchunk\ttext"]
    for point in points:
        text = " ".join(point.content.split())[:200]
        metadata.append(f"{point.filename}\t{point.chunk_index}\t{text}")
    (directory / "metadata.tsv").write_text("\n".join(metadata) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--query", help="embed this text and show its nearest chunks")
    parser.add_argument("--top-k", type=int, default=5, help="hits to highlight (default 5)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"default {DEFAULT_OUT}")
    parser.add_argument(
        "--projector", action="store_true", help="also write TSVs for the projector"
    )
    parser.add_argument("--open", action="store_true", help="open the result in a browser")
    args = parser.parse_args()

    engine = build_engine(get_settings().database_url)
    with build_session_factory(engine)() as session:
        points = load_chunks(session)
        if len(points) < 3:
            raise SystemExit(
                f"Found {len(points)} chunk(s); a map needs at least 3. "
                "Load some with: uv run python -m scripts.seed_demo_data"
            )
        payload = build_payload(points, args.query, args.top_k, session)
    engine.dispose()

    write_html(payload, args.out)
    documents = len({point.filename for point in points})
    print(
        f"{len(points)} chunks from {documents} document(s); PCA keeps "
        f"{sum(payload['explained']):.0%} of the variance"
    )
    print(f"map:       {args.out.resolve().as_uri()}")
    if args.projector:
        directory = args.out.parent / "projector"
        write_projector_files(points, directory)
        print(f"projector: {directory.resolve()} (vectors.tsv + metadata.tsv)")
    if args.query:
        for rank, hit in enumerate(payload["query"]["hits"], start=1):
            chunk = payload["points"][hit["point"]]
            print(f"  {rank}. d={hit['distance']:.3f}  {chunk['doc']} #{chunk['chunk']}")
    if args.open:
        webbrowser.open(args.out.resolve().as_uri())


if __name__ == "__main__":
    main()
