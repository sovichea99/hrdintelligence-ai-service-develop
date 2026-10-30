"""Extraction results. Page numbers are kept so citations (WBS 7.3) can point to a page."""

from dataclasses import dataclass, field
from typing import Literal

FileType = Literal["pdf", "docx", "png", "jpeg"]
ExtractionMethod = Literal["text", "ocr"]


@dataclass
class ExtractedPage:
    page_number: int  # 1-based; a DOCX has no pages and is returned as page 1
    text: str
    method: ExtractionMethod
    ocr_confidence: float | None = None  # mean recognition score 0..1, OCR pages only


@dataclass
class ExtractedDocument:
    file_type: FileType
    pages: list[ExtractedPage]
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)
