import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.security import TokenVerifier
from app.llm.client import LLMClient

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    session_factory=None,
    token_verifier: TokenVerifier | None = None,
    llm_client: LLMClient | None = None,
    ingestion_service=None,
) -> FastAPI:
    """Build the app. The keyword arguments let tests inject their own parts."""
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)
    # These libraries log full request URLs (model and storage servers, bucket keys) at INFO/DEBUG
    for noisy in ("httpx", "httpcore", "botocore", "boto3", "s3transfer", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    engine = None
    database_url = settings.database_url.get_secret_value()
    if session_factory is None and database_url:
        from app.db.session import create_engine_and_factory

        engine, session_factory = create_engine_and_factory(database_url)

    if token_verifier is None and settings.keycloak_issuer:
        token_verifier = TokenVerifier(
            issuer=settings.keycloak_issuer,
            jwks_url=settings.keycloak_jwks_url or None,
            audience=settings.keycloak_audience or None,
        )

    if session_factory is None or token_verifier is None:
        logger.warning(
            "DATABASE_URL or KEYCLOAK_ISSUER is not set: the chat endpoint will answer 503 "
            "until both are configured"
        )

    if ingestion_service is None and settings.ingestion_enabled:
        ingestion_service = _build_ingestion_service(settings, session_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()
        worker = asyncio.create_task(ingestion_service.run(stop)) if ingestion_service else None
        yield
        if worker is not None:
            stop.set()
            try:
                await asyncio.wait_for(worker, timeout=10)
            except TimeoutError:  # mid-file: the file is requeued on the next start
                worker.cancel()
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.settings = settings
    app.state.llm_client = llm_client or LLMClient(settings)
    app.state.session_factory = session_factory
    app.state.token_verifier = token_verifier
    app.include_router(api_router)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _build_ingestion_service(settings: Settings, session_factory):
    """The background indexing worker (WBS 7.6), or None when it cannot run (fail closed)."""
    from app.rag.embeddings import OpenAICompatibleEmbedder
    from app.services.indexing_service import IndexingService
    from app.services.ingestion_service import IngestionService
    from app.storage import StorageError, get_file_storage

    if session_factory is None or not settings.embedding_base_url:
        logger.error("INGESTION_ENABLED is set but DATABASE_URL or EMBEDDING_BASE_URL is missing: worker not started")
        return None
    try:
        storage = get_file_storage(settings)
    except StorageError as exc:  # message names missing settings only, never values
        logger.error("Ingestion worker not started: %s", exc)
        return None
    except Exception as exc:  # e.g. an invalid STORAGE_ENDPOINT_URL: its message would show the URL
        logger.error("Ingestion worker not started: storage client could not be created (%s)", type(exc).__name__)
        return None
    indexing = IndexingService(OpenAICompatibleEmbedder(settings), session_factory, settings)
    return IngestionService(storage, indexing, session_factory, settings)


app = create_app()