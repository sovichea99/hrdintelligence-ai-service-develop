"""Indexing: chunk -> embed -> store in ai.document_chunks + ai.chunk_embeddings,
on a temporary SQLite database with a fake embedder. The real hrd_db is checked by hand with
scripts/check_real_db.py (tests never touch it)."""

import asyncio
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.models import ChunkEmbedding, DocumentChunk
from app.document_processing.models import ExtractedDocument, ExtractedPage
from app.rag.embeddings import EmbeddingError
from app.services.indexing_service import IndexingService
from tests.conftest import _run, sqlite_engine

DIM = 1024


class FakeEmbedder:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.fail:
            raise EmbeddingError("embedding server returned HTTP 500")
        return [[float(i)] + [0.0] * (DIM - 1) for i in range(len(texts))]


def settings(**overrides) -> Settings:
    values = {"_env_file": None, "chunk_max_chars": 100, "chunk_overlap_chars": 20}
    return Settings(**(values | overrides))


@pytest.fixture
def service_for(db_url):
    engines = []

    def _make(embedder, **overrides) -> IndexingService:
        engine = sqlite_engine(db_url)
        engines.append(engine)
        return IndexingService(embedder, async_sessionmaker(engine, expire_on_commit=False), settings(**overrides))

    yield _make
    for engine in engines:
        asyncio.run(engine.dispose())


def rows(db_url, file_id) -> list[tuple[DocumentChunk, ChunkEmbedding]]:
    """The file's chunks with their vectors, in chunk order."""

    async def fn(s):
        stmt = (
            select(DocumentChunk, ChunkEmbedding)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.chunk_id)
            .where(DocumentChunk.file_id == file_id)
            .order_by(DocumentChunk.chunk_index)
        )
        return [tuple(r) for r in (await s.execute(stmt)).all()]

    return asyncio.run(_run(db_url, fn))


def table_counts(db_url) -> tuple[int, int]:
    async def fn(s):
        chunks = (await s.execute(text("SELECT count(*) FROM document_chunks"))).scalar_one()
        vectors = (await s.execute(text("SELECT count(*) FROM chunk_embeddings"))).scalar_one()
        return chunks, vectors

    return asyncio.run(_run(db_url, fn))


DOCX = ExtractedDocument(
    "docx",
    [ExtractedPage(1, "# Attendance policy\n\nStudents must scan in before 8:30.\n\n# Allowances\n\nMeal allowance is paid monthly.", "text")],
)
SCAN = ExtractedDocument(
    "pdf",
    [
        ExtractedPage(1, "Typed first page.", "text"),
        ExtractedPage(2, "", "ocr", None),
        ExtractedPage(3, "Scanned third page.", "ocr", 0.873),
    ],
)


def test_stores_every_chunk_and_its_vector_as_in_the_erd(db_url, service_for):
    file_id = uuid.uuid4()
    count = asyncio.run(service_for(FakeEmbedder()).index_document(file_id, SCAN))
    stored = rows(db_url, file_id)
    assert count == len(stored) == 2
    chunks = [chunk for chunk, _ in stored]
    assert [(c.chunk_index, c.page_number, c.content) for c in chunks] == [
        (0, 1, "Typed first page."),
        (1, 3, "Scanned third page."),
    ]
    assert [c.extraction_method for c in chunks] == ["text", "ocr_paddle"]  # OCR_ENGINE=paddle (default)
    assert [c.content_type for c in chunks] == ["text", "image_text"]
    assert chunks[0].ocr_confidence is None
    assert chunks[1].ocr_confidence == pytest.approx(87.3)  # ERD: 0..100
    assert all(c.token_count is None and c.metadata_ is None for c in chunks)
    vectors = [vector for _, vector in stored]
    assert all(v.model_name == "bge-m3" for v in vectors)
    assert [v.embedding[0] for v in vectors] == [0.0, 1.0] and len(vectors[0].embedding) == DIM


def test_surya_pages_are_stored_as_ocr_surya(db_url, service_for):
    file_id = uuid.uuid4()
    asyncio.run(service_for(FakeEmbedder(), ocr_engine="surya").index_document(file_id, SCAN))
    assert [c.extraction_method for c, _ in rows(db_url, file_id)] == ["text", "ocr_surya"]


def test_section_titles_come_from_headings(db_url, service_for):
    file_id = uuid.uuid4()
    asyncio.run(service_for(FakeEmbedder(), chunk_max_chars=60, chunk_overlap_chars=0).index_document(file_id, DOCX))
    assert [(c.section_title, c.content) for c, _ in rows(db_url, file_id)] == [
        ("Attendance policy", "# Attendance policy\n\nStudents must scan in before 8:30."),
        ("Allowances", "# Allowances\n\nMeal allowance is paid monthly."),
    ]


def test_reindexing_replaces_old_chunks_and_vectors_and_leaves_other_files_alone(db_url, service_for):
    file_a, file_b = uuid.uuid4(), uuid.uuid4()
    service = service_for(FakeEmbedder())
    asyncio.run(service.index_document(file_a, SCAN))
    asyncio.run(service.index_document(file_b, SCAN))
    new = ExtractedDocument("pdf", [ExtractedPage(1, "New version.", "text")])
    asyncio.run(service.index_document(file_a, new))
    assert [c.content for c, _ in rows(db_url, file_a)] == ["New version."]
    assert len(rows(db_url, file_b)) == 2
    assert table_counts(db_url) == (3, 3)  # no orphan vectors left behind


def test_failed_embedding_keeps_the_old_chunks(db_url, service_for):
    file_id = uuid.uuid4()
    asyncio.run(service_for(FakeEmbedder()).index_document(file_id, SCAN))
    with pytest.raises(EmbeddingError):
        asyncio.run(service_for(FakeEmbedder(fail=True)).index_document(file_id, DOCX))
    assert len(rows(db_url, file_id)) == 2


def test_failed_save_keeps_the_old_chunks(db_url, service_for):
    file_id = uuid.uuid4()
    asyncio.run(service_for(FakeEmbedder()).index_document(file_id, SCAN))

    class WrongCount(FakeEmbedder):  # one vector too few: saving fails after the delete
        async def embed(self, texts):
            return (await super().embed(texts))[:-1]

    with pytest.raises(ValueError):
        asyncio.run(service_for(WrongCount()).index_document(file_id, DOCX))
    assert [c.content for c, _ in rows(db_url, file_id)] == ["Typed first page.", "Scanned third page."]
    assert table_counts(db_url) == (2, 2)


def test_document_without_text_removes_old_chunks_and_calls_no_model(db_url, service_for):
    file_id = uuid.uuid4()
    asyncio.run(service_for(FakeEmbedder()).index_document(file_id, SCAN))
    embedder = FakeEmbedder()
    empty = ExtractedDocument("pdf", [ExtractedPage(1, "   ", "ocr", None)])
    assert asyncio.run(service_for(embedder).index_document(file_id, empty)) == 0
    assert rows(db_url, file_id) == []
    assert table_counts(db_url) == (0, 0)
    assert embedder.calls == [[]]  # embed([]) makes no request (see test_embeddings)


def test_delete_file_removes_its_chunks_and_vectors(db_url, service_for):
    file_id = uuid.uuid4()
    service = service_for(FakeEmbedder())
    asyncio.run(service.index_document(file_id, SCAN))
    asyncio.run(service.delete_file(file_id))
    assert table_counts(db_url) == (0, 0)

