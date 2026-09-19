import json
import re
from pathlib import Path

import numpy as np

from app.domain.models import ParsedPage
from scripts.seed_demo_data import paragraph_chunks
from scripts.visualize_vectors import fit_pca, write_html


def test_heading_travels_with_the_paragraph_after_it() -> None:
    text = "# Title\n\n## Leave\n\nTwenty one days.\n\n## Sick\n\nCall in early.\n"

    chunks = paragraph_chunks(ParsedPage(page_number=1, text=text))

    assert [c.content for c in chunks] == [
        "# Title\n\n## Leave\n\nTwenty one days.",
        "## Sick\n\nCall in early.",
    ]
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_chunk_offsets_slice_the_source_text() -> None:
    text = "First paragraph.\nStill first.\n\nSecond   \n\n\n\nThird."

    chunks = paragraph_chunks(ParsedPage(page_number=3, text=text))

    assert all(text[c.char_start : c.char_end] == c.content for c in chunks)
    assert [c.page_number for c in chunks] == [3, 3, 3]
    assert [c.content for c in chunks] == ["First paragraph.\nStill first.", "Second", "Third."]


def test_heading_without_body_is_dropped() -> None:
    assert [c.content for c in paragraph_chunks(ParsedPage(1, "Body.\n\n## Dangling"))] == ["Body."]


def test_pca_finds_the_dominant_direction() -> None:
    rng = np.random.default_rng(0)
    direction = rng.normal(size=384).astype(np.float32)
    matrix = np.outer(rng.normal(size=50), direction) + rng.normal(scale=0.01, size=(50, 384))

    projection = fit_pca(matrix.astype(np.float32))
    coords = projection.apply(matrix.astype(np.float32))

    assert projection.explained[0] > 0.99
    assert coords.shape == (50, 2)
    assert coords.dtype == np.float32


def test_written_page_survives_hostile_chunk_text(tmp_path: Path) -> None:
    payload = {"points": [{"text": "</script><script>alert(1)</script>"}], "note": "a </b> b"}

    out = tmp_path / "nested" / "map.html"
    write_html(payload, out)
    html = out.read_text(encoding="utf-8")

    embedded = re.search(r'id="data">(.*?)</script>', html, re.S)
    assert embedded is not None
    assert "__DATA__" not in html
    assert json.loads(embedded.group(1)) == payload
