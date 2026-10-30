"""Split extracted documents into overlapping chunks for embedding (WBS 7.5).

Pure functions. A chunk never spans two pages, so every chunk keeps the page number that
citations (WBS 7.3) point to. Text is split at the largest natural boundary that fits:
paragraph, line, sentence, space, and only as a last resort inside a word (never inside a
Khmer letter cluster). Khmer writes words without spaces and ends sentences with "។" or "៕".

Every Markdown heading ("# Title", as DOCX headings are extracted) starts a new chunk, so a chunk
holds one section and records its title. A heading with no text under it is kept together with
the next section; text before the first heading of a page keeps the previous page's title.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.document_processing.models import ExtractedDocument, ExtractionMethod


@dataclass(frozen=True)
class Chunk:
    chunk_index: int  # 0-based position within the document
    page_number: int
    text: str
    section_title: str | None = None
    extraction_method: ExtractionMethod = "text"
    ocr_confidence: float | None = None  # of the page the chunk comes from


_SEPARATORS = [
    re.compile(r"\n\s*\n"),  # paragraphs
    re.compile(r"\n"),  # lines
    re.compile(r"[.!?។៕]+\s*"),  # sentences
    re.compile(r"\s+"),  # spaces (between words in English/Korean, between phrases in Khmer)
]
_KHMER_COENG = "្"  # joins the next consonant to the previous one: never cut after it
_HEADING = re.compile(r"^#{1,6} +(.+)$", re.MULTILINE)
_MAX_TITLE_CHARS = 255  # section_title is VARCHAR(255)


def chunk_document(document: ExtractedDocument, max_chars: int, overlap_chars: int) -> list[Chunk]:
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")
    chunks: list[Chunk] = []
    title: str | None = None  # a section continues on the following pages until the next heading
    for page in document.pages:
        for title, section in _sections(_normalize(page.text), title):
            for text in chunk_text(section, max_chars, overlap_chars):
                chunks.append(
                    Chunk(
                        len(chunks),
                        page.page_number,
                        text,
                        title,
                        page.method,
                        page.ocr_confidence,
                    )
                )
    return chunks


def chunk_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Chunks of at most max_chars; each starts with up to overlap_chars from the previous one."""
    text = _normalize(text)
    if not text:
        return []
    return _merge(_pieces(text, max_chars, 0), max_chars, overlap_chars)


def _sections(text: str, title: str | None) -> list[tuple[str | None, str]]:
    """Split text before every heading: (title, section text). Text before the first heading
    keeps `title`. A heading with nothing under it is put in front of the next section."""
    starts = [m.start() for m in _HEADING.finditer(text)]
    bounds = sorted({0, *starts, len(text)})
    sections: list[tuple[str | None, str]] = []
    pending = ""  # headings with no text of their own
    for start, end in zip(bounds, bounds[1:]):
        part = text[start:end]
        heading = _HEADING.match(part)
        if heading:
            title = heading.group(1).strip()[:_MAX_TITLE_CHARS]
            if not part[heading.end() :].strip():
                pending += part
                continue
        if part.strip() or pending:
            sections.append((title, pending + part))
        pending = ""
    if pending:  # the page ends with headings only
        sections.append((title, pending))
    return sections


def _normalize(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pieces(text: str, max_chars: int, level: int) -> list[str]:
    """Split text into pieces of at most max_chars; joined back together they equal the input."""
    if len(text) <= max_chars:
        return [text]
    if level == len(_SEPARATORS):
        return _hard_cut(text, max_chars)
    pieces: list[str] = []
    for part in _split_after(text, _SEPARATORS[level]):
        pieces.extend(_pieces(part, max_chars, level + 1))
    return pieces


def _split_after(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Split text after each match, keeping the separator at the end of the piece before it."""
    parts, start = [], 0
    for match in pattern.finditer(text):
        if match.end() > start:
            parts.append(text[start : match.end()])
            start = match.end()
    if start < len(text):
        parts.append(text[start:])
    return parts


def _hard_cut(text: str, max_chars: int) -> list[str]:
    parts, start = [], 0
    while len(text) - start > max_chars:
        end = start + max_chars
        # Move back so a combining mark (Khmer vowel signs, accents) stays with its base letter
        while end > start + 1 and (
            unicodedata.category(text[end])[0] == "M" or text[end - 1] == _KHMER_COENG
        ):
            end -= 1
        parts.append(text[start:end])
        start = end
    parts.append(text[start:])
    return parts


def _merge(pieces: list[str], max_chars: int, overlap_chars: int) -> list[str]:
    """Pack pieces into chunks; the pieces at the end of a chunk are repeated at the start of the next."""
    chunks: list[str] = []
    window: list[str] = []
    size = 0
    for piece in pieces:
        if window and size + len(piece) > max_chars:
            chunks.append("".join(window).strip())
            while window and (size > overlap_chars or size + len(piece) > max_chars):
                size -= len(window.pop(0))
        window.append(piece)
        size += len(piece)
    if window:
        chunks.append("".join(window).strip())
    return [c for c in chunks if c]
