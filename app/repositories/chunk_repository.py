"""All database access for ai.document_chunks and ai.chunk_embeddings (WBS 7.5).

Writes are per file. Callers (7.6) must check that the user may upload/edit the file first;
reads for retrieval (7.2/7.3) must join with the permission tables.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChunkEmbedding, DocumentChunk
from app.rag.chunking import Chunk


class ChunkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def delete_file_chunks(self, file_id: uuid.UUID) -> None:
        """Embeddings first, so this works whether or not the foreign key cascades."""
        file_chunks = select(DocumentChunk.chunk_id).where(DocumentChunk.file_id == file_id)
        await self._db.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(file_chunks)))
        await self._db.execute(delete(DocumentChunk).where(DocumentChunk.file_id == file_id))

    async def add_chunks(
        self,
        file_id: uuid.UUID,
        chunks: list[Chunk],
        vectors: list[list[float]],
        *,
        ocr_method: str,
        model_name: str,
    ) -> None:
        """ocr_method is the extraction_method stored for OCR pages, e.g. "ocr_paddle".

        The chunks are flushed before their vectors: each vector row points at its chunk
        (foreign key), and without a relationship() SQLAlchemy does not order the inserts.
        """
        now = datetime.now(timezone.utc)
        if len(chunks) != len(vectors):
            raise ValueError("one vector per chunk is required")
        rows = []
        for chunk in chunks:
            is_ocr = chunk.extraction_method == "ocr"
            rows.append(DocumentChunk(
                chunk_id=uuid.uuid4(),
                chunk_index=chunk.chunk_index,
                content=chunk.text,
                content_type="image_text" if is_ocr else "text",
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                token_count=None,
                extraction_method=ocr_method if is_ocr else "text",
                # extraction gives 0..1; the ERD stores 0..100
                ocr_confidence=None if chunk.ocr_confidence is None else round(chunk.ocr_confidence * 100, 2),
                metadata_=None,
                created_at=now,
                file_id=file_id,
            ))
        self._db.add_all(rows)
        await self._db.flush()
        self._db.add_all(
            ChunkEmbedding(
                embedding_id=uuid.uuid4(),
                embedding=vector,
                model_name=model_name,
                created_at=now,
                chunk_id=row.chunk_id,
            )
            for row, vector in zip(rows, vectors)
        )

    async def count_file_chunks(self, file_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(DocumentChunk.file_id == file_id)
        return (await self._db.execute(stmt)).scalar_one()
