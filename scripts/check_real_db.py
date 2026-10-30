"""Manual check that WBS 7.5 storage works against the REAL hrd_db (run by hand, not by pytest).

Tests never touch hrd_db (.claude/rules/database.md), so this lives here. It uses the
DATABASE_URL in .env and only synthetic data:

1. read-only: sends a 1024-number vector to pgvector and reads it back;
2. writes two made-up chunks with made-up vectors under a new random file id to
   ai.document_chunks + ai.chunk_embeddings, reads them back, then deletes them again
   (also when a step fails). No embedding server is called;
3. the ingestion worker lock (7.6): a second worker must not get it while the first holds it.

    poetry run python scripts/check_real_db.py

TEST_FILE_ID=<id of a test row in public.files> is needed only if document_chunks.file_id
gets a foreign key to files.
"""

import asyncio
import os
import sys
import uuid

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import bindparam, select, text

from app.core.config import get_settings
from app.db.models import ChunkEmbedding, DocumentChunk
from app.db.session import create_engine_and_factory
from app.document_processing.models import ExtractedDocument, ExtractedPage
from app.repositories.file_repository import WorkerLock
from app.services.indexing_service import IndexingService

DIM = 1024
SAMPLE = ExtractedDocument(
    "pdf",
    [
        ExtractedPage(1, "Typed first page.", "text"),
        ExtractedPage(2, "Scanned second page.", "ocr", 0.873),
    ],
)


class MadeUpVectors:
    """Stands in for bge-m3: this script checks the database, not the model."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(i + 1)] + [0.0] * (DIM - 1) for i in range(len(texts))]


async def run() -> int:
    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    if not database_url:
        print("Set DATABASE_URL in .env first.")
        return 1
    engine, factory = create_engine_and_factory(database_url)
    service = IndexingService(MadeUpVectors(), factory, settings)
    file_id = uuid.UUID(os.environ["TEST_FILE_ID"]) if os.environ.get("TEST_FILE_ID") else uuid.uuid4()
    step = "connect"
    try:
        step = "vector round trip (read-only)"
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            stmt = text("SELECT CAST(:v AS vector) <=> CAST(:v AS vector)").bindparams(
                bindparam("v", type_=VECTOR(DIM))
            )
            distance = (await conn.execute(stmt, {"v": [0.5] + [0.0] * (DIM - 1)})).scalar_one()
            await conn.rollback()
        print(f"1. Vector round trip through pgvector: OK (distance {distance:.1f})")

        step = "write chunks"
        count = await service.index_document(file_id, SAMPLE)
        step = "read chunks back"
        async with factory() as db:
            stmt = (
                select(DocumentChunk, ChunkEmbedding)
                .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.chunk_id)
                .where(DocumentChunk.file_id == file_id)
                .order_by(DocumentChunk.chunk_index)
            )
            stored = (await db.execute(stmt)).all()
        details = [
            (c.page_number, c.extraction_method, c.content_type, c.ocr_confidence, e.model_name, len(e.embedding))
            for c, e in stored
        ]
        if count != 2 or len(stored) != 2:
            print(f"2. Write and read back: FAILED (stored {count}, read {len(stored)})")
            return 1
        print(f"2. Wrote and read back {len(stored)} chunks with their vectors: OK")
        for page, method, content_type, confidence, model, dims in details:
            print(f"   page {page}: {method}, {content_type}, confidence {confidence}, {model}, {dims} numbers")

        step = "ingestion worker lock (7.6)"
        first, second = WorkerLock(engine), WorkerLock(engine)
        try:
            results = [await first.acquire(), await second.acquire()]
            await first.release()
            results.append(await second.acquire())
        finally:
            await first.release()
            await second.release()
        ok = results == [True, False, True]
        print(f"   ingestion worker lock: only one worker at a time: {'OK' if ok else f'FAILED {results}'}")
        return 0 if ok else 1
    except Exception as exc:
        print(f"Failed at '{step}': {type(exc).__name__}")  # never the message: it can hold host or user
        return 1
    finally:
        try:
            await service.delete_file(file_id)
            async with factory() as db:
                left = (await db.execute(
                    select(DocumentChunk.chunk_id).where(DocumentChunk.file_id == file_id)
                )).all()
            print(f"3. Cleaned up: {'OK' if not left else f'{len(left)} chunk(s) LEFT, delete them by hand'}")
        except Exception as exc:
            print(f"3. Clean-up failed: {type(exc).__name__}. Remove chunks with file_id {file_id} by hand.")
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
