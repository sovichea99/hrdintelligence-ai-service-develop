"""Entry point: detect the file type from its content and dispatch to an extractor.

Extraction is synchronous and CPU-heavy (OCR can take seconds per page). From async
code, call it via `asyncio.to_thread(extract_document, ...)` so the server stays responsive.
"""

import io
import logging
import time
import zipfile

from app.core.config import Settings, get_settings
from app.document_processing.docx import extract_docx
from app.document_processing.errors import (
    CorruptDocumentError,
    DocumentTooLargeError,
    UnsupportedFileTypeError,
)
from app.document_processing.image import extract_image
from app.document_processing.models import ExtractedDocument, FileType
from app.document_processing.ocr import OcrEngine, get_ocr_engine
from app.document_processing.pdf import extract_pdf

logger = logging.getLogger(__name__)


def detect_file_type(data: bytes) -> FileType | None:
    """Identify the type by magic bytes; file names and extensions can lie.

    Exact signatures at offset 0 are checked before the looser PDF search, so a PNG
    or DOCX that happens to contain "%PDF-" near its start is not misread as a PDF.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"PK\x03\x04"):  # zip: DOCX, but also XLSX, PPTX, plain zips
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" in archive.namelist():
                    return "docx"
        except (zipfile.BadZipFile, ValueError, OSError):
            pass
        return None
    if b"%PDF-" in data[:1024]:  # the spec allows junk before the header
        return "pdf"
    return None


def extract_document(
    data: bytes,
    settings: Settings | None = None,
    ocr: OcrEngine | None = None,
) -> ExtractedDocument:
    """Extract per-page text. Raises a DocumentError subclass on failure.

    Logs only type, page counts and timing: never text or file names, which may
    contain student data.
    """
    settings = settings or get_settings()
    if not data:
        raise CorruptDocumentError("file is empty")
    if len(data) > settings.max_document_mb * 1024 * 1024:
        raise DocumentTooLargeError(f"file exceeds {settings.max_document_mb} MB")

    file_type = detect_file_type(data)
    if file_type is None:
        raise UnsupportedFileTypeError("only PDF, DOCX, PNG and JPEG are supported")

    ocr = ocr or get_ocr_engine(settings)
    start = time.monotonic()
    if file_type == "pdf":
        doc = extract_pdf(data, settings, ocr)
    elif file_type == "docx":
        doc = extract_docx(data)
    else:
        doc = extract_image(data, file_type, ocr)

    logger.info(
        "Extracted %s: %d page(s), %d via OCR, %d warning(s) in %.2fs",
        file_type,
        len(doc.pages),
        sum(p.method == "ocr" for p in doc.pages),
        len(doc.warnings),
        time.monotonic() - start,
    )
    return doc
