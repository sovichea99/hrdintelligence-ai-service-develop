"""PDF extraction: use the text layer where a page has one, OCR the page image where not."""

import math

import pypdfium2 as pdfium

from app.core.config import Settings
from app.document_processing.errors import (
    CorruptDocumentError,
    DocumentTooLargeError,
    EncryptedDocumentError,
)
from app.document_processing.models import ExtractedDocument, ExtractedPage
from app.document_processing.ocr import OcrEngine

# A page with fewer characters than this is treated as scanned (a page number or
# stray header is not real content). Known gap: a scan with a typed header of 20+
# characters is read from its text layer only.
MIN_TEXT_CHARS = 20
# Caps the rendered image for oversized pages (e.g. posters) to protect memory.
MAX_RENDER_PIXELS = 25_000_000


def extract_pdf(data: bytes, settings: Settings, ocr: OcrEngine) -> ExtractedDocument:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise EncryptedDocumentError("PDF is password protected") from exc
        raise CorruptDocumentError("PDF could not be opened") from exc

    try:
        if len(pdf) > settings.max_pdf_pages:
            raise DocumentTooLargeError(
                f"PDF has {len(pdf)} pages; the limit is {settings.max_pdf_pages}"
            )
        doc = ExtractedDocument(file_type="pdf", pages=[])
        ocr_pages = 0
        for index in range(len(pdf)):
            page_number = index + 1
            try:
                text, image = _read_page(pdf[index], settings)
            except pdfium.PdfiumError as exc:
                raise CorruptDocumentError(f"PDF page {page_number} could not be read") from exc
            if image is None:
                doc.pages.append(ExtractedPage(page_number=page_number, text=text, method="text"))
                continue

            # OCR is slow (seconds per page), so one scanned PDF must not occupy the
            # shared OCR engine for hours.
            ocr_pages += 1
            if ocr_pages > settings.max_ocr_pages:
                raise DocumentTooLargeError(
                    f"more than {settings.max_ocr_pages} pages need OCR"
                )
            result = ocr.recognize(image)
            if not result.text.strip():
                doc.warnings.append(f"page {page_number}: no text found")
            doc.pages.append(
                ExtractedPage(
                    page_number=page_number,
                    text=result.text.strip(),
                    method="ocr",
                    ocr_confidence=result.confidence,
                )
            )
        return doc
    finally:
        pdf.close()


def _read_page(page: pdfium.PdfPage, settings: Settings):
    """Return (text, None) for a page with a text layer, else ("", rendered image)."""
    try:
        textpage = page.get_textpage()
        try:
            text = textpage.get_text_bounded().replace("\r\n", "\n").strip()
        finally:
            textpage.close()
        if len(text) >= MIN_TEXT_CHARS:
            return text, None

        width, height = page.get_size()  # PDF points, 72 per inch
        scale = settings.pdf_ocr_dpi / 72
        if width * height * scale**2 > MAX_RENDER_PIXELS:
            scale = math.sqrt(MAX_RENDER_PIXELS / (width * height))
        # to_pil() copies the pixels, so the image stays valid after the page closes.
        return "", page.render(scale=scale).to_pil()
    finally:
        page.close()
