"""Turn uploaded files (PDF, DOCX, PNG/JPEG) into per-page text (WBS 7.4)."""

from app.document_processing.errors import (
    CorruptDocumentError,
    DocumentError,
    DocumentTooLargeError,
    EncryptedDocumentError,
    OcrUnavailableError,
    UnsupportedFileTypeError,
)
from app.document_processing.extractor import detect_file_type, extract_document
from app.document_processing.models import ExtractedDocument, ExtractedPage

__all__ = [
    "CorruptDocumentError",
    "DocumentError",
    "DocumentTooLargeError",
    "EncryptedDocumentError",
    "ExtractedDocument",
    "ExtractedPage",
    "OcrUnavailableError",
    "UnsupportedFileTypeError",
    "detect_file_type",
    "extract_document",
]
