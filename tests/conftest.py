"""Test fixtures: a fake vLLM server, a temporary database, and a real running copy of our app.

Real uvicorn servers (not TestClient) are used, so streaming and client disconnects are tested
over actual sockets, which is the only way to prove tokens arrive incrementally.
The database is a temporary SQLite file created from the models; the real service never creates
tables (the backend team owns the schema).
"""

import asyncio
import json
import socket
import threading
import time
import uuid
from dataclasses import dataclass

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.security import TokenVerifier
from app.db.models import Base, ChatMessage, ChatSession, Role, User
from app.main import create_app
from tests.helpers import ISSUER, PUBLIC_KEY, make_token

WORDS = ["Hello", " from", " the", " fake", " LLM"]
GAP_SECONDS = 0.3


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerThread:
    def __init__(self, app: FastAPI, port: int) -> None:
        self.port = port
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("test server did not start")
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def app(self) -> FastAPI:
        return self.server.config.app


# --------------------------------------------------------------------------- fake vLLM


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _chunk(model: str, content: str | None, finish: str | None = None) -> dict:
    delta = {"content": content} if content is not None else {}
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def build_fake_vllm() -> FastAPI:
    """Model name picks the behaviour: "fail" -> HTTP 500, "empty" -> no text,
    "die-midstream" -> stream ends after two tokens without a finish reason."""
    fake = FastAPI()
    fake.state.last_body = None
    fake.state.cancelled = False

    @fake.post("/v1/chat/completions")
    async def completions(request: Request):
        body = await request.json()
        fake.state.last_body = body
        model = body.get("model")
        if model == "fail":
            return JSONResponse({"error": {"message": "boom"}}, status_code=500)

        async def gen():
            try:
                if model == "empty":
                    yield _sse(_chunk(model, None, "stop"))
                    yield "data: [DONE]\n\n"
                    return
                for i, word in enumerate(WORDS):
                    yield _sse(_chunk(model, word))
                    if model == "die-midstream" and i == 1:
                        return
                    await asyncio.sleep(GAP_SECONDS)
                yield _sse(_chunk(model, None, "stop"))
                yield "data: [DONE]\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                fake.state.cancelled = True  # the client (our service) went away
                raise

        return StreamingResponse(gen(), media_type="text/event-stream")

    return fake


@pytest.fixture(scope="session")
def fake_vllm():
    server = ServerThread(build_fake_vllm(), free_port())
    server.start()
    yield server
    server.stop()


# --------------------------------------------------------------------------- database


def sqlite_engine(url: str):
    """SQLite has no schemas: tables of the `ai` schema are created without one. Foreign keys are
    switched on, as SQLite ignores them by default and PostgreSQL enforces them."""
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine.execution_options(schema_translate_map={"ai": None})


async def _run(url: str, fn):
    engine = sqlite_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await fn(session)
    finally:
        await engine.dispose()


async def _create_schema(url: str) -> None:
    engine = sqlite_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


def read_sessions(url: str) -> list[ChatSession]:
    async def fn(s):
        return list((await s.execute(select(ChatSession))).scalars())

    return asyncio.run(_run(url, fn))


def read_messages(url: str) -> list[ChatMessage]:
    async def fn(s):
        rows = await s.execute(select(ChatMessage).order_by(ChatMessage.created_at))
        return list(rows.scalars())

    return asyncio.run(_run(url, fn))


@dataclass
class TestUser:
    __test__ = False  # not a pytest test class

    user_id: uuid.UUID
    keycloak_id: uuid.UUID
    is_active: bool = True
    role: str | None = "instructor"  # None: users.role_id is NULL (no role at all)

    @property
    def token(self) -> str:
        return make_token(self.keycloak_id)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@dataclass
class Users:
    alice: TestUser  # admin
    bob: TestUser  # instructor
    carol: TestUser  # inactive account
    dave: TestUser  # active, but without a role
    erin: TestUser  # active, with a role the service does not know ("student")


@pytest.fixture
def db_url(tmp_path) -> str:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    asyncio.run(_create_schema(url))
    return url


@pytest.fixture
def users(db_url) -> Users:
    u = Users(
        alice=TestUser(uuid.uuid4(), uuid.uuid4(), role="admin"),
        bob=TestUser(uuid.uuid4(), uuid.uuid4(), role="instructor"),
        carol=TestUser(uuid.uuid4(), uuid.uuid4(), is_active=False),
        dave=TestUser(uuid.uuid4(), uuid.uuid4(), role=None),
        erin=TestUser(uuid.uuid4(), uuid.uuid4(), role="student"),
    )
    role_ids = {name: uuid.uuid4() for name in ("admin", "instructor", "student")}

    async def fn(s):
        for name, role_id in role_ids.items():
            s.add(Role(role_id=role_id, role_name=name))
        for t in (u.alice, u.bob, u.carol, u.dave, u.erin):
            s.add(
                User(
                    user_id=t.user_id,
                    keycloak_id=t.keycloak_id,
                    is_active=t.is_active,
                    role_id=role_ids.get(t.role),
                )
            )
        await s.commit()

    asyncio.run(_run(db_url, fn))
    return u


# --------------------------------------------------------------------------- our app


@pytest.fixture
def make_app_server(fake_vllm, db_url):
    """Start our app against the fake vLLM and the temporary database."""
    started: list[ServerThread] = []
    engines = []

    def _make(
        model: str = "test-model",
        base_url: str | None = None,
        configured: bool = True,
        max_sessions: int = 10,
    ) -> ServerThread:
        settings = Settings(
            _env_file=None,  # hermetic: ignore the developer's real .env
            llm_base_url=base_url or f"{fake_vllm.url}/v1",
            llm_api_key="test-key",
            llm_model=model,
            llm_max_retries=0,
            llm_timeout_seconds=5,
            database_url=db_url if configured else "",
            max_sessions_per_user=max_sessions,
        )
        verifier = (
            TokenVerifier(issuer=ISSUER, key_resolver=lambda token: PUBLIC_KEY)
            if configured
            else None
        )
        # The app gets a session factory whose SQLite connections enforce foreign keys, like
        # PostgreSQL does. Letting the app build its own engine from the URL would leave them off
        # and hide INSERT-order bugs (a message written before its session).
        session_factory = None
        if configured:
            engine = sqlite_engine(db_url)
            engines.append(engine)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
        server = ServerThread(
            create_app(settings, session_factory=session_factory, token_verifier=verifier),
            free_port(),
        )
        server.start()
        started.append(server)
        return server

    yield _make
    for s in started:
        s.stop()
    for engine in engines:
        asyncio.run(engine.dispose())