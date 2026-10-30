"""Index one file for retrieval (WBS 7.5): chunk its extracted text, embed the chunks, store them
in ai.document_chunks (text) and ai.chunk_embeddings (vectors), as in the ERD.

Order, chosen so a failure never leaves a file half-indexed:
1. chunk and embed everything first (embedding failures surface here, the database is untouched),
2. in ONE transaction, delete the file's old chunks and insert the new ones.
If step 2 fails the transaction rolls back and the old chunks stay.

Called by the ingestion worker (7.6) for files Spring registered in public.files (Spring checks
upload rights). Errors (EmbeddingError, SQLAlchemyError) propagate so 7.6 can record a status.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.document_processing.models import ExtractedDocument
from app.rag.chunking import chunk_document
from app.rag.embeddings import Embedder
from app.repositories.chunk_repository import ChunkRepository

# extraction_method stored for OCR pages, per OCR engine (ERD enum; "ocr_surya" still to be added to it)
_OCR_METHODS = {"paddle": "ocr_paddle", "surya": "ocr_surya"}


class IndexingService:
    def __init__(
        self,
        embedder: Embedder,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._embedder = embedder
        self._session_factory = session_factory
        self._settings = settings

    async def index_document(self, file_id: uuid.UUID, document: ExtractedDocument) -> int:
        """Replace the file's chunks; returns how many were stored (0 for a file with no text)."""
        s = self._settings
        chunks = chunk_document(document, s.chunk_max_chars, s.chunk_overlap_chars)
        vectors = await self._embedder.embed([chunk.text for chunk in chunks])

        async with self._session_factory() as db:
            repo = ChunkRepository(db)
            await repo.delete_file_chunks(file_id)
            await repo.add_chunks(
                file_id,
                chunks,
                vectors,
                # OCR_ENGINE=none never yields OCR pages, so the fallback is never stored
                ocr_method=_OCR_METHODS.get(s.ocr_engine, "text"),
                model_name=s.embedding_model_name,
            )
            await db.commit()
        return len(chunks)

    async def delete_file(self, file_id: uuid.UUID) -> None:
        """Remove a deleted file's chunks and their vectors."""
        async with self._session_factory() as db:
            await ChunkRepository(db).delete_file_chunks(file_id)
            await db.commit()
