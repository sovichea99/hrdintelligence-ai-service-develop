"""All database access to public.files for ingestion (WBS 7.6).

The AI service reads `files` and writes ONLY processing_status, processed_at and processing_error
(team decision 2026-10-29; needs a column-level UPDATE grant for ai_app).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import exists, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.db.models import DocumentChunk, File

logger = logging.getLogger(__name__)

ERROR_MAX_CHARS = 255
WORKER_LOCK_KEY = 7_060_001  # pg advisory lock id: "ingestion worker" (WBS 7.6)


@dataclass(frozen=True)
class ClaimedFile:
    file_id: uuid.UUID
    extension: str
    storage_url: str
    size_bytes: int


class FileRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def claim_next_pending(self) -> ClaimedFile | None:
        """Atomically move the oldest pending, not deleted file to "processing" and return it.
        SKIP LOCKED (PostgreSQL) lets several workers claim different files at the same time."""
        next_file = (
            select(File.file_id)
            .where(File.processing_status == "pending", File.deleted_at.is_(None))
            .order_by(File.uploaded_at)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            update(File)
            .where(File.file_id == next_file, File.processing_status == "pending")
            .values(processing_status="processing", processing_error=None, processed_at=None)
            .returning(File.file_id, File.extension, File.storage_url, File.size_bytes)
        )
        row = (await self._db.execute(stmt)).one_or_none()
        return ClaimedFile(*row) if row else None

    async def mark_completed(self, file_id: uuid.UUID) -> bool:
        return await self._set_status(file_id, "completed", None, finished=True)

    async def mark_failed(self, file_id: uuid.UUID, error: str) -> bool:
        """`error` must be a short, safe reason: never document text, file names or secrets."""
        return await self._set_status(file_id, "failed", error[:ERROR_MAX_CHARS], finished=True)

    async def release(self, file_id: uuid.UUID) -> bool:
        """Back to "pending" to be tried again later (storage or embedding server unreachable)."""
        return await self._set_status(file_id, "pending", None, finished=False)

    async def requeue_processing(self) -> int:
        """Files left in "processing" by a worker that stopped mid-file go back to "pending".
        Only called while holding the WorkerLock, so no other worker can be mid-file."""
        stmt = (
            update(File)
            .where(File.processing_status == "processing", File.deleted_at.is_(None))
            .values(processing_status="pending")
        )
        return (await self._db.execute(stmt)).rowcount

    async def file_ids_to_unindex(self) -> list[uuid.UUID]:
        """Files that still have chunks but were soft-deleted or no longer exist."""
        live_file = exists().where(File.file_id == DocumentChunk.file_id, File.deleted_at.is_(None))
        stmt = select(DocumentChunk.file_id).where(~live_file).distinct()
        return list((await self._db.execute(stmt)).scalars())

    async def _set_status(self, file_id: uuid.UUID, status: str, error: str | None, *, finished: bool) -> bool:
        """Only while the file is still ours: "processing" and not deleted. False when Spring changed
        it meanwhile (a new upload set it back to "pending", or it was deleted): then nothing is written."""
        result = await self._db.execute(
            update(File)
            .where(File.file_id == file_id, File.processing_status == "processing", File.deleted_at.is_(None))
            .values(
                processing_status=status,
                processed_at=datetime.now(timezone.utc) if finished else None,
                processing_error=error,
            )
        )
        return result.rowcount == 1


class WorkerLock:
    """Lets only ONE ingestion worker run across all processes and servers (PostgreSQL advisory
    lock, held by a dedicated connection; closing it releases the lock). Other databases (SQLite
    in tests) have no such lock: there the lock is always granted."""

    def __init__(self, engine: AsyncEngine | None) -> None:
        self._engine = engine
        self._conn: AsyncConnection | None = None
        self._held = False

    async def acquire(self) -> bool:
        if self._held:
            return True
        if self._engine is None or self._engine.dialect.name != "postgresql":
            self._held = True
            return True
        if self._conn is None:
            self._conn = await self._engine.connect()
        result = await self._conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK_KEY})
        self._held = bool(result.scalar_one())
        await self._conn.commit()
        return self._held

    async def release(self) -> None:
        """Unlock explicitly: close() only returns the connection to the pool, where it (and the
        lock) would stay alive. If the process dies, the database ends the lock with the connection."""
        held, self._held = self._held, False
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            if held:
                await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": WORKER_LOCK_KEY})
                await conn.commit()
        finally:
            await conn.close()
