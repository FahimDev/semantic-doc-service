from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.application.ports import DocumentParser
from app.core.errors import InvalidDocumentError, OCRRequiredError, UnsupportedDocumentError
from app.domain.models import ParsedDocument, ParsedPage

# https://www.securitywizardry.com/images/packets/other/pdf/Magic-Byte-Colour.pdf

# ============================================================================
# NO INHERITANCE HERE - Uses "Structural Typing" / Protocol Pattern
# ============================================================================
# Utf8TextParser does NOT inherit from DocumentParser. Instead, it implements
# the DocumentParser Protocol (see app/application/ports.py).
#
# Why? Because DocumentParser is a Protocol (structural typing), not a base class.
# Protocols say: "If your class has these methods/attributes with these signatures,
# you satisfy my contract." This is duck-typing enforced by type checkers.
#
# Benefits:
# - Loose coupling: Utf8TextParser doesn't depend on DocumentParser at runtime
# - Multiple implementations can satisfy the protocol independently
# - No circular imports, simpler code structure
# - Python's type checker (mypy/Pylance) verifies the contract statically
#
# This class must have:
#   - name: str (attribute)
#   - supports(filename, content_type, data) -> bool (method)
#   - parse(filename, content_type, data) -> ParsedDocument (method)
# ============================================================================

class Utf8TextParser:
    """
    Parses plain text and Markdown files (UTF-8 encoded only).
    
    This class satisfies the DocumentParser Protocol without explicit inheritance.
    It handles the extraction of text content from .txt and .md files.
    """
    
    # Class attribute: The name/identifier for this parser (used for logging/metadata)
    name = "utf8-text"
    
    # Class attribute: File extensions this parser can handle (immutable set)
    # frozenset is used for safety—can't accidentally modify the set
    extensions = frozenset({".txt", ".md"})

    def supports(self, filename: str, content_type: str, data: bytes) -> bool:
        """
        Determines if this parser can handle the given file.
        
        This method is the first gate: it's called to check if a document should
        be processed by Utf8TextParser or routed to another parser.
        
        Args:
            filename: The original filename (e.g., "document.txt")
            content_type: MIME type like "text/plain" or "text/markdown"
                         (intentionally unused here; we rely on extension)
            data: Raw bytes of the file (intentionally unused here)
            
        Returns:
            bool: True if the file extension matches our supported extensions
            
        Logic:
        - Extracts file extension from filename (e.g., ".txt" from "file.txt")
        - Converts to lowercase for case-insensitive comparison
        - Returns True only if extension is in our extensions set
        
        Note: We ignore content_type and data because checking the file extension
              is sufficient. Actual validation (UTF-8 encoding, content presence)
              happens later in parse().
        """
        # The 'del' statements prevent warnings about unused parameters
        # (we intentionally ignore content_type and data in this method)
        del content_type, data  
        return Path(filename).suffix.lower() in self.extensions

    def parse(self, filename: str, content_type: str, data: bytes) -> ParsedDocument:
        """
        Parses a UTF-8 text/markdown file and returns a structured document.
        
        This method performs the actual parsing: it validates the content,
        decodes bytes to text, and wraps it in a ParsedDocument object.
        
        Args:
            filename: The original filename (used to extract extension metadata)
            content_type: MIME type (intentionally unused here)
            data: Raw file bytes to decode and parse
            
        Returns:
            ParsedDocument: A structured object containing:
                - pages: A tuple of ParsedPage objects (one page for plain text)
                - metadata: Dictionary with parser name and source extension
                
        Raises:
            InvalidDocumentError: If any validation fails:
                - File contains NULL bytes (\x00)
                - File is not valid UTF-8 encoded text
                - File is empty or contains only whitespace
        """
        # We don't use content_type in text parsing; file extension determines the parser
        del content_type

        # ============================================================
        # VALIDATION STEP 1: Check for NULL bytes
        # ============================================================
        # NULL bytes indicate binary data or corrupted files
        # Plain text/markdown should never contain \x00 characters
        if b"\x00" in data:
            raise InvalidDocumentError("Text files must not contain NULL bytes.")

        # ============================================================
        # VALIDATION STEP 2: Decode bytes to UTF-8 text
        # ============================================================
        # Attempts to decode the raw bytes as UTF-8
        # If decoding fails, the file is not valid UTF-8 text
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            # Convert the low-level decoding error into our domain error
            raise InvalidDocumentError("Text and Markdown files must be UTF-8 encoded.") from exc

        # ============================================================
        # VALIDATION STEP 3: Check that document has actual content
        # ============================================================
        # Strip whitespace and check if anything meaningful remains
        # Empty files or files with only spaces/newlines are rejected
        if not text.strip():
            raise InvalidDocumentError("The document contains no text")

        # ============================================================
        # SUCCESS: Create and return ParsedDocument
        # ============================================================
        # For plain text/markdown, treat the entire content as a single "page"
        # (unlike PDFs which are multi-page; this simplifies the data model)
        return ParsedDocument(
            # pages: tuple of ParsedPage objects (one page for text files)
            # page_number=1 because text files are treated as single-page documents
            pages=(ParsedPage(page_number=1, text=text),),
            
            # metadata: dictionary storing parser info for audit/logging
            # parser: which parser processed this (useful when multiple parsers exist)
            # source_extension: original file extension (for reference/validation)
            metadata={
                "parser": self.name,
                "source_extension": Path(filename).suffix.lower()
            },
        )

class PdfTextParser:
    """Extract an existing text layer page-by-page; deliberately does not hide OCR."""
    name = "pypdf-text-layer"

    def __init__(self, max_pages: int = 100) -> None:
        self.max_pages = max_pages

    def supports(self, filename: str, content_type: str, data: bytes) -> bool:
        del content_type, data
        return Path(filename).suffix.lower() == ".pdf"

    def parse(self, filename: str, content_type: str, data: bytes) -> ParsedDocument:
        del filename, content_type
        
        # ============================================================
        # EARLY VALIDATION: PDF Signature (Magic Bytes) Check
        # ============================================================
        # ALL valid PDF files MUST start with the magic bytes: b"%PDF-"
        # followed by a version number like %PDF-1.4
        #
        # WHY THIS CHECK?
        # 1. Security: Rejects files renamed to .pdf but are actually binaries
        #    (e.g., an image renamed from .jpg to .pdf, or malicious files)
        # 2. Performance: Fails fast BEFORE attempting deep PDF parsing
        #    (PdfReader would spend time/CPU on invalid data otherwise)
        # 3. User feedback: Gives clear error message before parsing attempts
        #
        # WHEN DOES THIS HAPPEN?
        # - User uploads a file claiming it's a PDF
        # - We check the first 5 bytes of raw data
        # - If they don't match b"%PDF-", it's definitely not a PDF
        # - This is called "magic byte" validation (file format fingerprinting)
        #
        # EXAMPLE:
        # - Valid: b"%PDF-1.4%..." → passes (has correct signature)
        # - Invalid: b"GIF89a..." → rejected (it's a GIF image)
        # - Invalid: b"\x89PNG..." → rejected (it's a PNG image)
        if not data.startswith(b"%PDF-"):
            raise InvalidDocumentError("A .pdf upload must have a valid PDF signature")
        try:
            # ============================================================
            # PARSE PDF: PdfReader(BytesIO(data), strict=False)
            # ============================================================
            # This line creates a PDF parser object. Let's break it down:
            #
            # BytesIO(data) - WHY IS IT NEEDED?
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # • data is bytes (raw file content in memory)
            # • PdfReader expects a FILE-LIKE OBJECT, not raw bytes
            # • BytesIO converts bytes into a file-like stream interface
            #
            # What is a "file-like object"?
            # - Has methods: .read(), .seek(), .tell() like a real file
            # - Allows PdfReader to read incrementally (streaming)
            # - Avoids holding entire PDF in memory at once
            #
            # Example:
            #   data = b"%PDF-1.4..." (1000 bytes of PDF content)
            #   BytesIO(data) → creates an in-memory file object
            #   PdfReader can then .seek() to different positions and .read()
            #
            # strict=False - WHY IS IT NEEDED?
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # • PDFs are complex; many real-world PDFs have minor format violations
            # • strict=True: Would reject ANY deviation from PDF spec (too rigid)
            # • strict=False: Allows PdfReader to be lenient, skip minor issues
            #
            # With strict=False:
            # - Recovers text even from slightly malformed PDFs
            # - Still validates critical structures (won't parse garbage)
            # - Trades perfect spec compliance for practical robustness
            #
            # Without it (strict=True):
            # - Many real PDFs would fail to parse
            # - Users get "PDF could not be parsed" errors for valid documents
            #
            # Result: 'reader' is a PdfReader object that can extract text/pages
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise InvalidDocumentError("Encrypted PDFs are not supported")
            if len(reader.pages) > self.max_pages:
                raise InvalidDocumentError(
                    f"PDF has {len(reader.pages)} pages; limit is {self.max_pages}"
                )
            # Never merge pages here: page identity is evidence for citations.
            pages = tuple(
                ParsedPage(page_number=index, text=(page.extract_text() or ""))
                for index, page in enumerate(reader.pages, start=1)
            )
        except InvalidDocumentError:
            raise
        except (PdfReadError, ValueError, TypeError, KeyError) as exc:
            raise InvalidDocumentError("The PDF could not be parsed safely") from exc

        if not pages:
            raise InvalidDocumentError("The PDF has no pages")
        if not any(page.text.strip() for page in pages):
            # Empty extraction is not silently accepted as a searchable document.
            raise OCRRequiredError(
                "The PDF has no usable text layer; add an OCR parser for scanned documents"
            )
        return ParsedDocument(
            pages=pages,
            metadata={"parser": self.name, "pdf_pages": len(pages), "text_layer": True},
        )

class ParserRegistry:
    def __init__(self, parsers: tuple[DocumentParser, ...]) -> None:
        self._parsers = parsers

    def parse(self, filename: str, content_type: str, data: bytes) -> ParsedDocument:
        for parser in self._parsers:
            if parser.supports(filename, content_type, data):
                return parser.parse(filename, content_type, data)
        raise UnsupportedDocumentError("Only .txt, .md, and text-based .pdf are supported")