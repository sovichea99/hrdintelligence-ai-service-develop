"""Embedding client against a fake OpenAI-compatible embedding server (real sockets)."""

import logging
import math
import os

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.rag.embeddings import EmbeddingError, EmbeddingUnavailableError, OpenAICompatibleEmbedder
from tests.conftest import ServerThread, free_port

DIM = 8


def build_fake_embedding_server() -> FastAPI:
    """Model name picks the behaviour: "fail" -> HTTP 500, "wrong-dim" -> 3 numbers,
    "missing" -> one vector too few, "shuffled" -> items in reverse order."""
    fake = FastAPI()
    fake.state.batches = []

    @fake.post("/v1/embeddings")
    async def embeddings(request: Request):
        body = await request.json()
        model, texts = body["model"], body["input"]
        fake.state.batches.append(texts)
        if model == "fail":
            return JSONResponse({"error": {"message": "boom"}}, status_code=500)
        dim = 3 if model == "wrong-dim" else DIM
        # Deterministic vector: first number is the text's length, so tests can check order
        data = [
            {"object": "embedding", "index": i, "embedding": [float(len(t))] + [0.0] * (dim - 1)}
            for i, t in enumerate(texts)
        ]
        if model == "missing":
            data = data[:-1]
        if model == "shuffled":
            data.reverse()
        return {
            "object": "list",
            "data": data,
            "model": model,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    return fake


@pytest.fixture(scope="module")
def fake_embeddings():
    server = ServerThread(build_fake_embedding_server(), free_port())
    server.start()
    yield server
    server.stop()


@pytest.fixture(autouse=True)
def clear_batches(fake_embeddings):
    fake_embeddings.app.state.batches.clear()


def embedder(base_url: str, model: str = "test-embed", batch_size: int = 32):
    settings = Settings(
        _env_file=None,
        embedding_base_url=base_url,
        embedding_api_key="test-key",
        embedding_model=model,
        embedding_dimension=DIM,
        embedding_batch_size=batch_size,
        embedding_timeout_seconds=5,
        embedding_max_retries=0,
    )
    return OpenAICompatibleEmbedder(settings)


TEXTS = ["a", "bb", "ccc", "dddd", "eeeee"]


async def test_one_vector_per_text_in_order(fake_embeddings):
    vectors = await embedder(f"{fake_embeddings.url}/v1").embed(TEXTS)
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert all(len(v) == DIM for v in vectors)


async def test_sends_batches(fake_embeddings):
    vectors = await embedder(f"{fake_embeddings.url}/v1", batch_size=2).embed(TEXTS)
    assert fake_embeddings.app.state.batches == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]


async def test_reordered_response_is_put_back_in_order(fake_embeddings):
    vectors = await embedder(f"{fake_embeddings.url}/v1", "shuffled").embed(TEXTS)
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]


async def test_no_texts_makes_no_request(fake_embeddings):
    assert await embedder(f"{fake_embeddings.url}/v1").embed([]) == []
    assert fake_embeddings.app.state.batches == []


async def test_wrong_dimension_is_an_error(fake_embeddings):
    with pytest.raises(EmbeddingError, match="dimension"):
        await embedder(f"{fake_embeddings.url}/v1", "wrong-dim").embed(TEXTS)


async def test_missing_vector_is_an_error(fake_embeddings):
    with pytest.raises(EmbeddingError, match="number"):
        await embedder(f"{fake_embeddings.url}/v1", "missing").embed(TEXTS)


async def test_server_error_does_not_leak_text(fake_embeddings, caplog):
    secret = "Student Sok Dara, ID 12345"
    with caplog.at_level(logging.DEBUG, logger="app"), pytest.raises(EmbeddingError) as info:
        await embedder(f"{fake_embeddings.url}/v1", "fail").embed([secret])
    assert not isinstance(info.value, EmbeddingUnavailableError)
    assert "500" in str(info.value)
    assert secret not in str(info.value)
    assert secret not in caplog.text


async def test_unreachable_server_is_unavailable():
    with pytest.raises(EmbeddingUnavailableError):
        await embedder(f"http://127.0.0.1:{free_port()}/v1").embed(TEXTS)


async def test_not_configured_is_unavailable():
    with pytest.raises(EmbeddingUnavailableError, match="not configured"):
        await embedder("").embed(TEXTS)


# --------------------------------------------------------------------------- real bge-m3


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


@pytest.mark.skipif(os.environ.get("RUN_EMBEDDING_TESTS") != "1", reason="set RUN_EMBEDDING_TESTS=1")
async def test_real_bge_m3():
    # Like the service: EMBEDDING_* from env vars or .env. Synthetic sentences only.
    configured = Settings()
    if not configured.embedding_base_url:
        # pytest.fail, not assert: a failing assert prints the Settings object, secrets included
        pytest.fail("set EMBEDDING_BASE_URL")
    texts = [
        "The student submitted the homework on time.",
        "The learner handed in the assignment before the deadline.",
        "Phnom Penh is very hot in April.",
        "សិស្សបានប្រគល់កិច្ចការផ្ទះទាន់ពេល។",  # Khmer: the student handed in the homework on time
    ]
    vectors = await OpenAICompatibleEmbedder(configured).embed(texts)
    assert all(len(v) == 1024 for v in vectors)
    similar, unrelated = cosine(vectors[0], vectors[1]), cosine(vectors[0], vectors[2])
    khmer = cosine(vectors[0], vectors[3])
    print(f"similar {similar:.3f}, unrelated {unrelated:.3f}, English-Khmer same meaning {khmer:.3f}")
    assert similar > unrelated
    assert khmer > unrelated  # bge-m3 is multilingual: same meaning across languages is close
