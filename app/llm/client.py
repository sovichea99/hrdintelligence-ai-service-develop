"""Thin async client for the local LLM server (vLLM, OpenAI-compatible API)."""

import logging
from collections.abc import AsyncIterator

import openai
from openai import AsyncOpenAI

from app.core.config import Settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """The LLM server answered with an error."""


class LLMUnavailableError(LLMError):
    """The LLM server could not be reached or timed out."""


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield text deltas as the model produces them."""
        s = self._settings
        try:
            stream = await self._client.chat.completions.create(
                model=s.llm_model,
                messages=messages,
                stream=True,
                temperature=s.llm_temperature,
                max_tokens=s.llm_max_tokens,
            )
            try:
                finished = False
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.delta.content:
                        yield choice.delta.content
                    if choice.finish_reason:
                        finished = True
                if not finished:
                    # The connection ended cleanly but the model never said it was done: the
                    # answer is cut off and must not be treated as complete.
                    raise LLMError("LLM stream ended without a finish reason")
            finally:
                await stream.close()
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            logger.warning("LLM server unreachable: %s", type(exc).__name__)
            raise LLMUnavailableError("LLM server unreachable") from exc
        except openai.APIStatusError as exc:
            logger.error("LLM server returned HTTP %s", exc.status_code)
            raise LLMError(f"LLM server returned HTTP {exc.status_code}") from exc
