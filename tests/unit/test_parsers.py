from io import BytesIO

import pytest
from reportlab.pdfgen import canvas

from app.core.errors import InvalidDocumentError, OCRRequiredError, UnsupportedDocumentError
from app.infrastructure.parsers import ParserRegistry, PdfTextParser, Utf8TextParser


def make_pdf(pages: list[str]) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    for text in pages:
        if text:
            pdf.drawString(72, 720, text)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@pytest.fixture
def registry() -> ParserRegistry:
    return ParserRegistry((Utf8TextParser(), PdfTextParser(max_pages=3)))


def test_text_file_becomes_single_page(registry: ParserRegistry) -> None:
    parsed = registry.parse("notes.MD", "text/markdown", b"# Title\nbody")

    assert [(p.page_number, p.text) for p in parsed.pages] == [(1, "# Title\nbody")]
    assert parsed.metadata == {"parser": "utf8-text", "source_extension": ".md"}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"abc\x00def", "NULL"),
        (b"\xff\xfe\x00bad"[:2] + b"\xc3\x28", "UTF-8"),
        (b"  \n\t ", "no text"),
    ],
)
def test_text_file_rejects_bad_content(registry: ParserRegistry, data: bytes, message: str) -> None:
    with pytest.raises(InvalidDocumentError, match=message):
        registry.parse("bad.txt", "text/plain", data)


def test_unknown_extension_is_unsupported(registry: ParserRegistry) -> None:
    with pytest.raises(UnsupportedDocumentError):
        registry.parse("image.png", "image/png", b"\x89PNG")


def test_pdf_keeps_page_identity(registry: ParserRegistry) -> None:
    parsed = registry.parse("a.pdf", "application/pdf", make_pdf(["Alpha page", "Beta page"]))

    assert [p.page_number for p in parsed.pages] == [1, 2]
    assert "Alpha" in parsed.pages[0].text
    assert "Beta" in parsed.pages[1].text
    assert parsed.metadata == {"parser": "pypdf-text-layer", "pdf_pages": 2, "text_layer": True}


def test_pdf_without_text_layer_requires_ocr(registry: ParserRegistry) -> None:
    with pytest.raises(OCRRequiredError):
        registry.parse("scan.pdf", "application/pdf", make_pdf([""]))


def test_pdf_signature_is_checked(registry: ParserRegistry) -> None:
    with pytest.raises(InvalidDocumentError, match="signature"):
        registry.parse("fake.pdf", "application/pdf", b"GIF89a")


def test_pdf_page_limit_is_enforced(registry: ParserRegistry) -> None:
    with pytest.raises(InvalidDocumentError, match="limit"):
        registry.parse("big.pdf", "application/pdf", make_pdf(["x"] * 4))


def test_truncated_pdf_is_invalid(registry: ParserRegistry) -> None:
    with pytest.raises(InvalidDocumentError):
        registry.parse("cut.pdf", "application/pdf", b"%PDF-1.4\n1 0 obj\n<<")
