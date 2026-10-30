"""Index uploaded files in the background (WBS 7.6).

Spring creates each `files` row with processing_status = "pending". This worker polls for them:

    pending -> processing -> completed            (chunks and vectors stored, 7.5)
                          -> failed + reason      (processing_error: short and safe)

One file at a time: claim it, read its bytes from storage, extract the text (7.4), index it (7.5),
record the result. Chunks of soft-deleted or removed files are deleted on every round, because
ai.document_chunks has no foreign key to public.files. Logs hold file ids, counts and durations
only: never file names, storage paths or document text.
"""

import asyncio
import logging
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.document_processing import DocumentError, extract_document
from app.document_processing.ocr import get_ocr_engine
from app.rag.embeddings import EmbeddingError, EmbeddingUnavailableError
from app.repositories.file_repository import ClaimedFile, FileRepository, WorkerLock
from app.services.indexing_service import IndexingService
from app.storage import FileStorage, StorageError, StorageUnavailableError

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {"pdf", "docx", "png", "jpeg"}  # what extract_document reads (7.4)


class _Failed(Exception):
    """Indexing failed for a reason that is safe to store in processing_error."""


class _Retry(Exception):
    """A server we depend on is unreachable: put the file back to "pending" and try later, so an
    outage does not fail every waiting file for good."""


class IngestionService:
    def __init__(
        self,
        storage: FileStorage,
        indexing: IndexingService,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._storage = storage
        self._indexing = indexing
        self._session_factory = session_factory
        self._settings = settings

    async def run(self, stop: asyncio.Event) -> None:
        """Poll until `stop` is set. Errors are logged (type only) and the loop goes on.
        Only the worker holding the WorkerLock does anything; others wait as stand-ins."""
        lock = WorkerLock(self._session_factory.kw.get("bind"))
        started = waiting_logged = False
        try:
            while not stop.is_set():
                worked = False
                try:
                    if await lock.acquire():
                        if not started:
                            requeued = await self.requeue_unfinished()
                            started = True
                            logger.info("Ingestion worker started (%d unfinished file(s) requeued)", requeued)
                        await self.remove_deleted_files()
                        worked = await self.process_next()
                    elif not waiting_logged:
                        waiting_logged = True
                        logger.info("Another ingestion worker is running; this one waits")
                except Exception as exc:  # e.g. the database is briefly unreachable: retry next round
                    logger.error("Ingestion round failed: %s", type(exc).__name__)
                if not worked:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=self._settings.ingestion_poll_seconds)
                    except TimeoutError:
                        pass
        finally:
            await lock.release()
        logger.info("Ingestion worker stopped")

    async def requeue_unfinished(self) -> int:
        async with self._session_factory() as db:
            count = await FileRepository(db).requeue_processing()
            await db.commit()
        return count

    async def remove_deleted_files(self) -> int:
        async with self._session_factory() as db:
            file_ids = await FileRepository(db).file_ids_to_unindex()
        for file_id in file_ids:
            await self._indexing.delete_file(file_id)
            logger.info("Removed chunks of deleted file %s", file_id)
        return len(file_ids)

    async def process_next(self) -> bool:
        """Index one pending file. Returns False when there was nothing to do."""
        async with self._session_factory() as db:
            file = await FileRepository(db).claim_next_pending()
            await db.commit()
        if file is None:
            return False

        start = time.monotonic()
        try:
            chunks = await self._index(file)
        except _Retry as exc:
            await self._finish(file.file_id, retry=True)
            logger.warning("File %s put back to pending: %s", file.file_id, exc)
            return False  # wait a poll interval before trying again
        except _Failed as exc:
            await self._finish(file.file_id, error=str(exc))
            logger.warning("File %s failed: %s", file.file_id, exc)
        else:
            await self._finish(file.file_id)
            logger.info("File %s indexed: %d chunk(s) in %.1fs", file.file_id, chunks, time.monotonic() - start)
        return True

    async def _index(self, file: ClaimedFile) -> int:
        s = self._settings
        if file.extension.lower() not in SUPPORTED_EXTENSIONS:
            raise _Failed("Unsupported file type")
        max_bytes = s.max_document_mb * 1024 * 1024
        if file.size_bytes > max_bytes:
            raise _Failed("File is larger than the allowed size")
        try:
            data = await asyncio.to_thread(self._storage.read, file.storage_url, max_bytes)
            document = await asyncio.to_thread(extract_document, data, s, get_ocr_engine(s))
            chunks = await self._indexing.index_document(file.file_id, document)
        except StorageUnavailableError as exc:
            raise _Retry("storage unreachable") from exc
        except EmbeddingUnavailableError as exc:
            raise _Retry("embedding server unavailable") from exc
        except (StorageError, DocumentError) as exc:  # their messages are written to be safe
            raise _Failed(str(exc)) from exc
        except EmbeddingError as exc:
            raise _Failed("Embedding failed") from exc
        except Exception as exc:
            logger.error("Indexing file %s failed: %s", file.file_id, type(exc).__name__)
            raise _Failed("Internal error while indexing") from exc
        if chunks == 0:
            raise _Failed("No text found in the file")
        return chunks

    async def _finish(self, file_id: uuid.UUID, error: str | None = None, *, retry: bool = False) -> None:
        async with self._session_factory() as db:
            repo = FileRepository(db)
            if retry:
                written = await repo.release(file_id)
            elif error is None:
                written = await repo.mark_completed(file_id)
            else:
                written = await repo.mark_failed(file_id, error)
            await db.commit()
        if not written:  # a new upload reset it to pending (indexed again next round) or it was deleted
            logger.info("File %s changed while it was indexed; status left as it is", file_id)
