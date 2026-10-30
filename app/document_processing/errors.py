"""Extraction errors. Messages are safe to show: they never contain document content."""


class DocumentError(Exception):
    """The document could not be extracted."""


class UnsupportedFileTypeError(DocumentError):
    """The file is not a PDF, DOCX, PNG or JPEG."""


class DocumentTooLargeError(DocumentError):
    """The file exceeds a size, page or pixel limit."""


class CorruptDocumentError(DocumentError):
    """The file claims a supported type but cannot be parsed."""


class EncryptedDocumentError(DocumentError):
    """The PDF is password protected."""


class OcrUnavailableError(DocumentError):
    """OCR is needed but disabled or not installed."""
