"""Ingestion worker (WBS 7.6): pending file -> storage -> extract -> index -> status.

Temporary SQLite database, a local storage folder and a fake embedder; no servers needed.
"""

import asyncio
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from docx import Document
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.models import DocumentChunk, File
from app.main import create_app
from app.repositories.file_repository import FileRepository
from app.services.indexing_service import IndexingService
from app.services.ingestion_service import IngestionService
from app.storage import LocalFileStorage
from tests.conftest import _run, sqlite_engine
from tests.test_indexing import FakeEmbedder

SECRET_TEXT = "Student Sok Dara scored 97 in IT"


def docx_bytes(*paragraphs: str) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def storage_dir(tmp_path):
    folder = tmp_path / "storage"
    folder.mkdir()
    return folder


@pytest.fixture
def make_service(db_url, storage_dir):
    engines = []

    def _make(embedder=None, **overrides) -> IngestionService:
        engine = sqlite_engine(db_url)
        engines.append(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        values = {"_env_file": None, "storage_backend": "local", "storage_local_root": str(storage_dir),
                  "ingestion_poll_seconds": 0.05, "ocr_engine": "none"}
        settings = Settings(**(values | overrides))
        indexing = IndexingService(embedder or FakeEmbedder(), factory, settings)
        return IngestionService(LocalFileStorage(str(storage_dir)), indexing, factory, settings)

    yield _make
    for engine in engines:
        asyncio.run(engine.dispose())


def add_file(db_url, storage_dir, data: bytes | None, *, extension="docx", status="pending",
             deleted=False, uploaded_minutes_ago=0, key=None) -> uuid.UUID:
    file_id = uuid.uuid4()
    key = key or f"uploads/{file_id}.{extension}"
    if data is not None:
        path = storage_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    now = datetime.now(timezone.utc)

    async def fn(s):
        s.add(File(file_id=file_id, extension=extension, size_bytes=len(data or b""), storage_url=key,
                   processing_status=status, processed_at=None, processing_error=None,
                   uploaded_at=now - timedelta(minutes=uploaded_minutes_ago),
                   deleted_at=now if deleted else None))
        await s.commit()

    asyncio.run(_run(db_url, fn))
    return file_id


def file_row(db_url, file_id) -> File:
    async def fn(s):
        return (await s.execute(select(File).where(File.file_id == file_id))).scalar_one()

    return asyncio.run(_run(db_url, fn))


def chunk_count(db_url, file_id) -> int:
    async def fn(s):
        return len((await s.execute(select(DocumentChunk).where(DocumentChunk.file_id == file_id))).all())

    return asyncio.run(_run(db_url, fn))


def test_pending_file_is_indexed_and_marked_completed(db_url, storage_dir, make_service):
    file_id = add_file(db_url, storage_dir, docx_bytes("Students must scan in before 8:30."))
    assert asyncio.run(make_service().process_next()) is True
    row = file_row(db_url, file_id)
    assert (row.processing_status, row.processing_error) == ("completed", None)
    assert row.processed_at is not None
    assert chunk_count(db_url, file_id) == 1


def test_nothing_pending_does_nothing(db_url, storage_dir, make_service):
    add_file(db_url, storage_dir, docx_bytes("Done already."), status="completed")
    assert asyncio.run(make_service().process_next()) is False


@pytest.mark.parametrize(
    "extension, data, error",
    [
        ("xlsx", b"PK\x03\x04 spreadsheet", "Unsupported file type"),
        ("pptx", b"PK\x03\x04 slides", "Unsupported file type"),
        ("txt", b"plain text", "Unsupported file type"),
        ("pdf", b"this is not a pdf", "only PDF, DOCX, PNG and JPEG are supported"),
        ("docx", docx_bytes(""), "No text found in the file"),
    ],
    # Short ids: the default id embeds the DOCX bytes, which makes the test's PYTEST_CURRENT_TEST
    # environment variable exceed the 32767-character limit on Windows and errors at setup.
    ids=["xlsx", "pptx", "txt", "pdf", "docx"],
)
def test_unusable_files_are_marked_failed_with_a_safe_reason(db_url, storage_dir, make_service, extension, data, error):
    file_id = add_file(db_url, storage_dir, data, extension=extension)
    asyncio.run(make_service().process_next())
    row = file_row(db_url, file_id)
    assert (row.processing_status, row.processing_error) == ("failed", error)
    assert row.processed_at is not None
    assert chunk_count(db_url, file_id) == 0


def test_file_missing_from_storage_is_marked_failed(db_url, storage_dir, make_service):
    file_id = add_file(db_url, storage_dir, None)
    asyncio.run(make_service().process_next())
    assert file_row(db_url, file_id).processing_error == "file not found in storage"


def test_file_larger_than_the_limit_is_not_downloaded(db_url, storage_dir, make_service):
    file_id = add_file(db_url, storage_dir, docx_bytes("x"))

    async def grow(s):
        row = (await s.execute(select(File).where(File.file_id == file_id))).scalar_one()
        row.size_bytes = 2 * 1024 * 1024
        await s.commit()

    asyncio.run(_run(db_url, grow))
    asyncio.run(make_service(max_document_mb=1).process_next())
    assert file_row(db_url, file_id).processing_error == "File is larger than the allowed size"


def test_embedding_server_down_puts_the_file_back_to_pending(db_url, storage_dir, make_service):
    file_id = add_file(db_url, storage_dir, docx_bytes("First version."))
    asyncio.run(make_service().process_next())
    assert chunk_count(db_url, file_id) == 1

    async def reupload(s):  # Spring sets the file back to pending after a new upload
        row = (await s.execute(select(File).where(File.file_id == file_id))).scalar_one()
        row.processing_status = "pending"
        await s.commit()

    asyncio.run(_run(db_url, reupload))

    class Down(FakeEmbedder):
        async def embed(self, texts):
            from app.rag.embeddings import EmbeddingUnavailableError

            raise EmbeddingUnavailableError("embedding server unreachable")

    assert asyncio.run(make_service(Down()).process_next()) is False  # back off before retrying
    row = file_row(db_url, file_id)
    assert (row.processing_status, row.processing_error, row.processed_at) == ("pending", None, None)
    assert chunk_count(db_url, file_id) == 1  # old chunks untouched (status is not "completed", so not used)

    asyncio.run(make_service().process_next())  # server back: indexed normally
    assert file_row(db_url, file_id).processing_status == "completed"


def test_storage_unreachable_puts_the_file_back_to_pending(db_url, storage_dir, make_service):
    from app.storage import StorageUnavailableError

    file_id = add_file(db_url, storage_dir, docx_bytes("Waiting for storage."))
    service = make_service()

    class Unreachable:
        def read(self, storage_url, max_bytes):
            raise StorageUnavailableError("storage unreachable")

    service._storage = Unreachable()
    assert asyncio.run(service.process_next()) is False
    assert file_row(db_url, file_id).processing_status == "pending"


@pytest.mark.parametrize("change", ["reuploaded", "deleted"])
def test_file_changed_while_indexing_keeps_springs_status(db_url, storage_dir, make_service, change):
    """Spring may reset the file to pending (new upload) or delete it while we index the old bytes:
    then our result must not overwrite Spring's change."""
    file_id = add_file(db_url, storage_dir, docx_bytes("Old version."))
    service = make_service()
    original = service._indexing.index_document

    async def index_then_spring_changes_the_file(fid, document):
        count = await original(fid, document)

        async def fn(s):
            row = (await s.execute(select(File).where(File.file_id == fid))).scalar_one()
            if change == "reuploaded":
                row.processing_status = "pending"
            else:
                row.deleted_at = datetime.now(timezone.utc)
            await s.commit()

        await _run(db_url, fn)
        return count

    service._indexing.index_document = index_then_spring_changes_the_file
    asyncio.run(service.process_next())
    row = file_row(db_url, file_id)
    if change == "reuploaded":
        assert row.processing_status == "pending"  # will be indexed again with the new bytes
    else:
        assert row.processing_status == "processing" and row.deleted_at is not None
        assert asyncio.run(service.remove_deleted_files()) == 1  # its chunks go next round


def test_oldest_pending_file_goes_first_and_each_file_is_claimed_once(db_url, storage_dir, make_service):
    newer = add_file(db_url, storage_dir, docx_bytes("newer"), uploaded_minutes_ago=1)
    older = add_file(db_url, storage_dir, docx_bytes("older"), uploaded_minutes_ago=10)

    async def claim_three(s):
        repo = FileRepository(s)
        claimed = [await repo.claim_next_pending() for _ in range(3)]
        await s.commit()
        return claimed

    first, second, third = asyncio.run(_run(db_url, claim_three))
    assert (first.file_id, second.file_id, third) == (older, newer, None)
    assert file_row(db_url, older).processing_status == "processing"


def test_soft_deleted_pending_file_is_not_processed(db_url, storage_dir, make_service):
    file_id = add_file(db_url, storage_dir, docx_bytes("deleted before indexing"), deleted=True)
    assert asyncio.run(make_service().process_next()) is False
    assert file_row(db_url, file_id).processing_status == "pending"


def test_chunks_of_deleted_or_removed_files_are_cleaned_up(db_url, storage_dir, make_service):
    service = make_service()
    kept = add_file(db_url, storage_dir, docx_bytes("keep me"))
    deleted = add_file(db_url, storage_dir, docx_bytes("delete me"))
    removed = add_file(db_url, storage_dir, docx_bytes("remove me"))
    for _ in range(3):
        asyncio.run(service.process_next())

    async def soft_delete_and_remove(s):
        (await s.execute(select(File).where(File.file_id == deleted))).scalar_one().deleted_at = datetime.now(timezone.utc)
        await s.delete((await s.execute(select(File).where(File.file_id == removed))).scalar_one())
        await s.commit()

    asyncio.run(_run(db_url, soft_delete_and_remove))
    assert asyncio.run(service.remove_deleted_files()) == 2
    assert [chunk_count(db_url, f) for f in (kept, deleted, removed)] == [1, 0, 0]


def test_files_left_processing_are_requeued_on_start(db_url, storage_dir, make_service):
    stuck = add_file(db_url, storage_dir, docx_bytes("stuck"), status="processing")
    assert asyncio.run(make_service().requeue_unfinished()) == 1
    assert file_row(db_url, stuck).processing_status == "pending"


def test_worker_loop_indexes_files_until_stopped(db_url, storage_dir, make_service):
    files = [add_file(db_url, storage_dir, docx_bytes(f"File {i}.")) for i in range(2)]
    stuck = add_file(db_url, storage_dir, docx_bytes("Interrupted earlier."), status="processing")

    async def run_until_done():
        engine = sqlite_engine(db_url)
        stop = asyncio.Event()
        task = asyncio.create_task(make_service().run(stop))
        try:
            for _ in range(100):
                await asyncio.sleep(0.05)
                async with async_sessionmaker(engine)() as s:
                    statuses = (await s.execute(select(File.processing_status))).scalars().all()
                if statuses and all(status == "completed" for status in statuses):
                    break
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=5)
            await engine.dispose()

    asyncio.run(run_until_done())
    assert [file_row(db_url, f).processing_status for f in [*files, stuck]] == ["completed"] * 3


def test_logs_hold_ids_not_names_paths_or_text(db_url, storage_dir, make_service, caplog):
    key = "uploads/Sok Dara transcript.docx"
    ok = add_file(db_url, storage_dir, docx_bytes(SECRET_TEXT), key=key)
    bad = add_file(db_url, storage_dir, b"not a pdf " + SECRET_TEXT.encode(), extension="pdf", key="uploads/Sok Dara.pdf")
    with caplog.at_level(logging.DEBUG, logger="app"):
        service = make_service()
        asyncio.run(service.process_next())
        asyncio.run(service.process_next())
    assert str(ok) in caplog.text and str(bad) in caplog.text
    for secret in ("Sok Dara", "transcript", "uploads/"):
        assert secret not in caplog.text
    assert "Sok Dara" not in (file_row(db_url, bad).processing_error or "")


async def test_app_starts_and_stops_the_worker(db_url):
    class Recorder:
        def __init__(self):
            self.started = self.stopped = False

        async def run(self, stop):
            self.started = True
            await stop.wait()
            self.stopped = True

    recorder = Recorder()
    app = create_app(Settings(_env_file=None), ingestion_service=recorder)
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.05)
        assert recorder.started and not recorder.stopped
    assert recorder.stopped


def test_worker_is_not_built_without_database_or_embedding_server(caplog):
    with caplog.at_level(logging.ERROR, logger="app"):
        create_app(Settings(_env_file=None, ingestion_enabled=True))
    assert "worker not started" in caplog.text
