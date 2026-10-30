"""Application settings, loaded from environment variables / .env.

Never hardcode secrets here. Real values live in `.env` (git-ignored);
`.env.example` documents the names. Secrets are SecretStr, so printing Settings (logs, failing
test asserts) shows "**********"; read them with `.get_secret_value()` only where they are used.
"""

from functools import lru_cache
from typing import Literal

from pydantic import NonNegativeInt, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "HRD Intelligence AI Service"
    log_level: str = "INFO"

    # vLLM exposes an OpenAI-compatible API under /v1
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: SecretStr = SecretStr("not-needed")  # vLLM ignores it unless started with --api-key
    llm_model: str = "CHANGE_ME_MODEL_NAME"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 1

    # Conversation history sent to the model: at most this many stored messages, trimmed (oldest
    # first) to this many characters. The model context is 16384 tokens and Khmer uses many tokens
    # per character, so the character budget is deliberately conservative. Tune after testing.
    history_max_messages: int = 20
    history_max_chars: int = 8000

    # A user may own at most this many chat sessions (docs/features.md). A new chat beyond the
    # limit is refused with HTTP 409 before anything is saved; continuing an old one always works.
    max_sessions_per_user: PositiveInt = 10

    # Existing PostgreSQL database (schema owned by the backend team), async driver,
    # e.g. postgresql+asyncpg://user:password@host:5432/dbname. Empty = chat answers 503.
    database_url: SecretStr = SecretStr("")  # holds the database password

    # Keycloak JWT verification. Empty issuer = chat answers 503 (authentication is never skipped).
    keycloak_issuer: str = ""
    keycloak_jwks_url: str = ""  # optional; defaults to <issuer>/protocol/openid-connect/certs
    keycloak_audience: str = ""  # optional; checked only when set

    # Document extraction (WBS 7.4). OCR runs on our machines; "none" disables it.
    ocr_engine: Literal["paddle", "surya", "none"] = "paddle"
    ocr_language: str = "en"  # PaddleOCR only; Surya detects the language itself
    # Surya runs on an inference server. Unset: Surya starts a local one (llama.cpp on a Mac).
    surya_inference_url: str | None = None
    surya_inference_api_key: SecretStr = SecretStr("EMPTY")
    max_document_mb: PositiveInt = 50
    max_pdf_pages: PositiveInt = 500
    max_ocr_pages: PositiveInt = 100  # OCR takes seconds per page; caps one document's cost
    pdf_ocr_dpi: PositiveInt = 200

    # Chunking (WBS 7.5). Measured in characters, not tokens: bge-m3 accepts 8192 tokens, so size
    # only affects search quality. Khmer uses more tokens per character than English. Tune after testing.
    chunk_max_chars: PositiveInt = 1500
    chunk_overlap_chars: NonNegativeInt = 200

    # Embeddings (WBS 7.5): bge-m3 on an OpenAI-compatible server (vLLM), URL ending in /v1.
    # Empty = indexing answers "unavailable". Dimension must match the VECTOR(1024) column.
    embedding_base_url: str = ""
    embedding_api_key: SecretStr = SecretStr("EMPTY")
    embedding_model: str = "BAAI/bge-m3"
    embedding_model_name: str = "bge-m3"  # stored in ai.chunk_embeddings.model_name (ERD default)
    embedding_dimension: PositiveInt = 1024
    embedding_batch_size: PositiveInt = 32
    embedding_timeout_seconds: float = 60.0
    embedding_max_retries: int = 1

    # Uploaded files (WBS 7.6). "s3": RustFS or any S3-compatible store; "local": a folder (dev/tests).
    # storage_url may be "s3://bucket/key", "http(s)://host/bucket/key" or a key in storage_bucket.
    storage_backend: Literal["s3", "local"] = "s3"
    storage_endpoint_url: str = ""  # S3 API address (not the web console)
    storage_bucket: str = ""
    storage_access_key: SecretStr = SecretStr("")  # read-only key for the AI service
    storage_secret_key: SecretStr = SecretStr("")
    storage_region: str = "us-east-1"  # S3 clients need one; RustFS ignores it
    storage_local_root: str = ""
    storage_timeout_seconds: float = 30.0

    # Ingestion worker (WBS 7.6): polls public.files for processing_status = 'pending'.
    # Off by default; needs DATABASE_URL, storage and the embedding server.
    ingestion_enabled: bool = False
    ingestion_poll_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
