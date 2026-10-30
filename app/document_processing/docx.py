"""DOCX extraction: body paragraphs and tables in reading order.

Not extracted: embedded images, headers/footers, footnotes, text boxes and nested
tables. Headings are recognized by the English style names "Heading 1".."Heading 9".
"""

import io
import zipfile

import docx
from docx.table import Table

from app.document_processing.errors import CorruptDocumentError, DocumentTooLargeError
from app.document_processing.models import ExtractedDocument, ExtractedPage

# A DOCX is a zip. Checking the unpacked size first stops "zip bombs" (a tiny file
# that expands to gigabytes) before python-docx loads it into memory. Real DOCX
# files with many images stay well under this.
MAX_UNZIPPED_BYTES = 200 * 1024 * 1024


def extract_docx(data: bytes) -> ExtractedDocument:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            unzipped = sum(info.file_size for info in archive.infolist())
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        raise CorruptDocumentError("DOCX could not be opened") from exc
    if unzipped > MAX_UNZIPPED_BYTES:
        raise DocumentTooLargeError("DOCX expands beyond the size limit")

    try:
        document = docx.Document(io.BytesIO(data))
        blocks = [_block_text(block) for block in document.iter_inner_content()]
    except Exception as exc:  # malformed XML or package parts; parser errors vary
        raise CorruptDocumentError("DOCX could not be parsed") from exc

    text = "\n\n".join(b for b in blocks if b)
    return ExtractedDocument(
        file_type="docx",
        pages=[ExtractedPage(page_number=1, text=text, method="text")],
    )


def _block_text(block) -> str:
    if isinstance(block, Table):
        return _table_text(block)
    text = block.text.strip()
    style = block.style.name if block.style is not None else ""
    # Keep headings visible as Markdown so chunking (WBS 7.5) can split on them.
    if text and style.startswith("Heading "):
        level = style.removeprefix("Heading ")
        if level.isdigit():
            return f"{'#' * int(level)} {text}"
    return text


def _table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells: list[str] = []
        seen = []
        for cell in row.cells:
            # A merged cell is returned once per column it spans; keep one copy.
            # Compare the underlying XML element, not the text, so two real cells
            # with equal values ("Yes | Yes") are both kept.
            if any(cell._tc is tc for tc in seen):
                continue
            seen.append(cell._tc)
            cells.append(cell.text.strip())
        rows.append(" | ".join(cells))
    return "\n".join(r for r in rows if r.strip(" |"))
