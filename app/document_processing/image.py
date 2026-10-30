"""Image extraction (scanned pages, phone photos): validate, then OCR."""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.document_processing.errors import CorruptDocumentError, DocumentTooLargeError
from app.document_processing.models import ExtractedDocument, ExtractedPage, FileType
from app.document_processing.ocr import OcrEngine

# Larger than an A4 scan at 600 DPI (~35 MP). Rejecting bigger images protects
# memory from "decompression bombs" (small files that decode to huge bitmaps).
MAX_IMAGE_PIXELS = 50_000_000


def extract_image(data: bytes, file_type: FileType, ocr: OcrEngine) -> ExtractedDocument:
    try:
        image = Image.open(io.BytesIO(data))  # reads the header only
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise DocumentTooLargeError("image resolution exceeds the limit")
        image.load()
        image = ImageOps.exif_transpose(image)  # phone photos store rotation in EXIF
    except DocumentTooLargeError:
        raise
    except Image.DecompressionBombError as exc:  # Pillow's own, even larger limit
        raise DocumentTooLargeError("image resolution exceeds the limit") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise CorruptDocumentError("image could not be decoded") from exc

    result = ocr.recognize(image)
    doc = ExtractedDocument(
        file_type=file_type,
        pages=[
            ExtractedPage(
                page_number=1,
                text=result.text.strip(),
                method="ocr",
                ocr_confidence=result.confidence,
            )
        ],
    )
    if not result.text.strip():
        doc.warnings.append("page 1: no text found")
    return doc
