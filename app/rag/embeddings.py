"""Text embeddings behind one small interface (WBS 7.5; 7.2 reuses it to embed questions).

- OpenAICompatibleEmbedder: bge-m3 on an OpenAI-compatible server (vLLM /v1/embeddings).
  An in-process engine can be added behind the same interface if a deployment needs one.

Only exception types and status codes are logged: the texts are document content.
"""

import logging
from typing import Protocol

import openai
from openai import AsyncOpenAI

from app.core.config import Settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """The embedding server answered with an error or an unusable result."""


class EmbeddingUnavailableError(EmbeddingError):
    """The embedding server is not configured, could not be reached or timed out."""


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One vector per text, in the same order."""
        ...


class OpenAICompatibleEmbedder:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = (
            AsyncOpenAI(
                base_url=settings.embedding_base_url,
                api_key=settings.embedding_api_key.get_secret_value(),
                timeout=settings.embedding_timeout_seconds,
                max_retries=settings.embedding_max_retries,
            )
            if settings.embedding_base_url
            else None
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._client is None:
            raise EmbeddingUnavailableError("embedding server not configured (EMBEDDING_BASE_URL)")
        size = self._settings.embedding_batch_size
        vectors: list[list[float]] = []
        for start in range(0, len(texts), size):
            vectors.extend(await self._embed_batch(texts[start : start + size]))
        return vectors

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        s = self._settings
        try:
            response = await self._client.embeddings.create(
                model=s.embedding_model, input=batch, encoding_format="float"
            )
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            logger.warning("Embedding server unreachable: %s", type(exc).__name__)
            raise EmbeddingUnavailableError("embedding server unreachable") from exc
        except openai.APIStatusError as exc:
            logger.error("Embedding server returned HTTP %s", exc.status_code)
            raise EmbeddingError(f"embedding server returned HTTP {exc.status_code}") from exc

        data = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in data] != list(range(len(batch))):
            logger.error("Embedding server returned %d vectors for %d texts", len(data), len(batch))
            raise EmbeddingError("embedding server returned the wrong number of vectors")
        for item in data:
            if len(item.embedding) != s.embedding_dimension:
                logger.error(
                    "Embedding has %d dimensions, expected %d",
                    len(item.embedding),
                    s.embedding_dimension,
                )
                raise EmbeddingError("embedding has the wrong dimension")
        return [item.embedding for item in data]
