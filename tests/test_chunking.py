import unicodedata

import pytest

from app.document_processing.models import ExtractedDocument, ExtractedPage
from app.rag.chunking import chunk_document, chunk_text


def doc(*page_texts: str) -> ExtractedDocument:
    pages = [ExtractedPage(i + 1, text, "text") for i, text in enumerate(page_texts)]
    return ExtractedDocument("pdf", pages)


def test_short_page_is_one_chunk():
    chunks = chunk_document(doc("Hello world."), max_chars=100, overlap_chars=10)
    assert [(c.chunk_index, c.page_number, c.text) for c in chunks] == [(0, 1, "Hello world.")]


def test_chunks_never_span_pages_and_keep_page_numbers():
    chunks = chunk_document(doc("First page.", "", "  \n ", "Fourth page."), 100, 10)
    assert [(c.chunk_index, c.page_number, c.text) for c in chunks] == [
        (0, 1, "First page."),
        (1, 4, "Fourth page."),  # empty and blank pages give no chunks
    ]


def test_empty_document_gives_no_chunks():
    assert chunk_document(ExtractedDocument("docx", []), 100, 10) == []


def test_chunks_respect_max_size_and_cover_all_text():
    sentences = [f"Sentence number {i} talks about attendance." for i in range(60)]
    text = " ".join(sentences)
    chunks = chunk_text(text, max_chars=200, overlap_chars=50)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    joined = " ".join(chunks)
    assert all(s in joined for s in sentences)  # nothing lost


def test_splits_at_sentence_ends_and_overlaps():
    sentences = [f"This is sentence {i:02d}." for i in range(20)]  # 21-22 chars each
    chunks = chunk_text(" ".join(sentences), max_chars=100, overlap_chars=30)
    for chunk in chunks:
        assert chunk.startswith("This is sentence") and chunk.endswith(".")
    for previous, current in zip(chunks, chunks[1:]):
        last_sentence = previous.rsplit("This is sentence", 1)[1]
        assert current.startswith("This is sentence" + last_sentence)  # repeated as overlap


def test_prefers_paragraph_boundaries():
    para_a = "A" * 60 + "."
    para_b = "B" * 60 + "."
    chunks = chunk_text(f"{para_a}\n\n{para_b}", max_chars=100, overlap_chars=0)
    assert chunks == [para_a, para_b]


def test_zero_overlap():
    words = " ".join(f"w{i:03d}" for i in range(100))
    chunks = chunk_text(words, max_chars=50, overlap_chars=0)
    assert " ".join(chunks).split() == words.split()  # each word exactly once


def test_whitespace_is_normalized():
    assert chunk_text("  a \t b  \n\n\n\n c \r\n d  ", 100, 0) == ["a b\n\nc\nd"]


def test_khmer_splits_at_khmer_sentence_marks():
    sentence = "សិស្សមានវត្តមានល្អណាស់។"  # Khmer sentence ending with "។", no spaces
    chunks = chunk_text(sentence * 10, max_chars=60, overlap_chars=0)
    assert len(chunks) > 1
    assert all(len(c) <= 60 for c in chunks)
    assert all(c.endswith("។") for c in chunks)
    assert "".join(chunks) == sentence * 10


def test_hard_cut_never_splits_a_khmer_letter_cluster():
    text = "សិស្សមានវត្តមាន" * 20  # no spaces, no sentence marks: must hard-cut
    chunks = chunk_text(text, max_chars=37, overlap_chars=0)
    assert "".join(chunks) == text
    for chunk in chunks:
        assert len(chunk) <= 37
        assert unicodedata.category(chunk[0])[0] != "M"  # no chunk starts with a vowel sign
        assert not chunk.endswith("្")  # no chunk ends with the subscript joiner


def sections(chunks) -> list[tuple[str | None, str]]:
    return [(c.section_title, c.text) for c in chunks]


def test_every_heading_starts_a_new_chunk_even_when_all_fits():
    text = "Report title\n\n# Scores\n\nSTU-1 | 92\nSTU-2 | 81\n\n# Counts\n\nLate: 3."
    assert sections(chunk_document(doc(text), max_chars=1500, overlap_chars=200)) == [
        (None, "Report title"),
        ("Scores", "# Scores\n\nSTU-1 | 92\nSTU-2 | 81"),
        ("Counts", "# Counts\n\nLate: 3."),
    ]


def test_heading_without_text_joins_the_next_section():
    text = "# Chapter 1\n## Attendance\n\nScan before 8:30."
    assert sections(chunk_document(doc(text), 1500, 200)) == [
        ("Attendance", "# Chapter 1\n## Attendance\n\nScan before 8:30.")
    ]


def test_long_section_is_split_and_every_part_keeps_the_title():
    body = " ".join(f"Rule {i} applies to every student." for i in range(20))
    chunks = chunk_document(doc(f"# Rules\n\n{body}\n\n# Other\n\nShort."), max_chars=200, overlap_chars=40)
    titles = [c.section_title for c in chunks]
    assert titles[-1] == "Other" and set(titles[:-1]) == {"Rules"} and len(titles) > 2
    assert all(len(c.text) <= 200 for c in chunks)


def test_section_title_continues_on_the_next_page():
    chunks = chunk_document(doc("# Allowances\n\nMeal allowance.", "Paid monthly."), 1500, 200)
    assert [(c.page_number, c.section_title) for c in chunks] == [(1, "Allowances"), (2, "Allowances")]


def test_page_ending_with_a_heading_keeps_it():
    chunks = chunk_document(doc("Text.\n\n# Next part"), 1500, 200)
    assert sections(chunks) == [(None, "Text."), ("Next part", "# Next part")]


def test_overlap_must_be_smaller_than_max():
    with pytest.raises(ValueError):
        chunk_document(doc("text"), max_chars=100, overlap_chars=100)
