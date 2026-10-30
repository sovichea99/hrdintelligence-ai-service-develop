"""Try the WBS 7.5 pipeline on ONE sample file, then search it with a question.

extract (7.4) -> chunk -> embed with bge-m3 -> store in ai.document_chunks + ai.chunk_embeddings -> search -> delete

Uses the settings in .env (OCR engine, EMBEDDING_*, DATABASE_URL). SAMPLE DOCUMENTS ONLY:
the file's text goes to the OCR and embedding servers through the development tunnel.
The chunks are stored under a new random file id that matches no real file, and are deleted at
the end unless --keep is given. The search only looks at this file's chunks.

    poetry run python scripts/try_indexing.py path/to/sample.pdf "What is the attendance rule?"
    poetry run python scripts/try_indexing.py sample.docx "question" --top 5 --keep
    poetry run python scripts/try_indexing.py --delete <file id printed by --keep>
"""

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import ChunkEmbedding, DocumentChunk
from app.db.session import create_engine_and_factory
from app.document_processing import DocumentError, extract_document
from app.document_processing.ocr import get_ocr_engine
from app.rag.embeddings import EmbeddingError, OpenAICompatibleEmbedder
from app.services.indexing_service import IndexingService


def preview(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + " ..."


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    if not database_url or not settings.embedding_base_url:
        print("Set DATABASE_URL and EMBEDDING_BASE_URL in .env first.")
        return 1
    engine, factory = create_engine_and_factory(database_url)
    embedder = OpenAICompatibleEmbedder(settings)
    service = IndexingService(embedder, factory, settings)
    try:
        if args.delete:
            await service.delete_file(uuid.UUID(args.delete))
            print(f"Deleted the chunks of {args.delete}.")
            return 0

        data = Path(args.file).read_bytes()
        file_id = uuid.uuid4()

        start = time.monotonic()
        document = await asyncio.to_thread(extract_document, data, settings, get_ocr_engine(settings))
        methods = sorted({p.method for p in document.pages})
        print(f"1. Extracted {len(document.pages)} page(s) as {document.file_type} "
              f"({', '.join(methods)}) in {time.monotonic() - start:.1f}s")
        for warning in document.warnings:
            print("   warning:", warning)

        start = time.monotonic()
        count = await service.index_document(file_id, document)
        print(f"2. Chunked, embedded and stored {count} chunk(s) in {time.monotonic() - start:.1f}s "
              f"(file id {file_id})")
        if count == 0:
            print("   No text found, nothing to search.")
            return 0

        question_vector = (await embedder.embed([args.question]))[0]
        distance = ChunkEmbedding.embedding.cosine_distance(question_vector)
        stmt = (
            select(DocumentChunk, distance.label("distance"))
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.chunk_id)
            .where(DocumentChunk.file_id == file_id, ChunkEmbedding.model_name == settings.embedding_model_name)
            .order_by(distance)
            .limit(args.top)
        )
        async with factory() as db:
            results = (await db.execute(stmt)).all()

        print(f'3. Top {len(results)} chunk(s) for: "{args.question}"  (similarity: 1 = same meaning)')
        for rank, (chunk, dist) in enumerate(results, 1):
            where = f"page {chunk.page_number}"
            if chunk.section_title:
                where += f', section "{chunk.section_title}"'
            if chunk.extraction_method != "text":
                where += f", {chunk.extraction_method} confidence {chunk.ocr_confidence}/100"
            print(f"\n   #{rank}  similarity {1 - dist:.3f}  chunk {chunk.chunk_index}  ({where})")
            print("   " + preview(chunk.content))

        if args.keep:
            print(f"\nKept. Remove later with: --delete {file_id}")
        else:
            await service.delete_file(file_id)
            print("\n4. Deleted this file's chunks again.")
        return 0
    except (DocumentError, EmbeddingError) as exc:
        print(f"Failed: {type(exc).__name__}: {exc}")  # these messages never contain document text
        return 1
    except Exception as exc:
        print(f"Failed: {type(exc).__name__}")  # other messages can hold connection details
        return 1
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", nargs="?", help="sample PDF, DOCX, PNG or JPEG")
    parser.add_argument("question", nargs="?", help="question to search the file with")
    parser.add_argument("--top", type=int, default=3, help="how many chunks to show (default 3)")
    parser.add_argument("--keep", action="store_true", help="keep the chunks instead of deleting them")
    parser.add_argument("--delete", metavar="FILE_ID", help="only delete the chunks of this file id")
    args = parser.parse_args()
    if not args.delete and not (args.file and args.question):
        parser.error("give a file and a question, or --delete FILE_ID")
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
