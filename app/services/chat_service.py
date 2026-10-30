"""Chat business logic. In WBS 7.2/7.3 retrieval is inserted here, before the LLM call.

Order of a turn (see `start_turn`), chosen so a failed turn leaves nothing behind:
1. load the history of the caller's own session (404 if it is not theirs),
2. wait for the model's first token (LLM failures surface here, nothing is saved yet),
3. save the session and the user's message,
4. the caller streams the rest and then calls `save_answer` only if the answer completed.
"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.llm.client import LLMClient, LLMError
from app.llm.prompts import GENERAL_SYSTEM_PROMPT
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import ChatRequest
from app.services.history import HistoryMessage, build_model_messages, sender_to_role

TITLE_MAX_CHARS = 150  # chat_sessions.title is VARCHAR(150)


class SessionNotFoundError(Exception):
    """The session does not exist or belongs to someone else (deliberately indistinguishable)."""


class SessionLimitReachedError(Exception):
    """The user already owns the maximum number of chat sessions; one must be deleted first."""


@dataclass
class ChatTurn:
    session_id: uuid.UUID
    deltas: AsyncGenerator[str, None]  # every text fragment of the answer, the first one included


async def _chain(first: str, rest: AsyncIterator[str]) -> AsyncGenerator[str, None]:
    try:
        yield first
        async for delta in rest:
            yield delta
    finally:
        await rest.aclose()  # closes our request to the model if the client went away


def _title(message: str) -> str:
    return " ".join(message.split())[:TITLE_MAX_CHARS]


class ChatService:
    def __init__(
        self,
        llm: LLMClient,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._llm = llm
        self._session_factory = session_factory
        self._settings = settings

    async def start_turn(self, user_id: uuid.UUID, request: ChatRequest) -> ChatTurn:
        if request.session_id is None:
            await self._check_session_limit(user_id)
        history = await self._load_history(user_id, request.session_id)
        messages = build_model_messages(
            GENERAL_SYSTEM_PROMPT, history, request.message, self._settings.history_max_chars
        )

        deltas = self._llm.stream_chat(messages)
        try:
            first = await anext(deltas)
        except StopAsyncIteration:
            raise LLMError("the model returned no text") from None

        session_id = await self._save_user_message(user_id, request)
        return ChatTurn(session_id=session_id, deltas=_chain(first, deltas))

    async def save_answer(self, session_id: uuid.UUID, answer: str) -> None:
        async with self._session_factory() as db:
            repo = ChatRepository(db)
            repo.add_message(session_id, sender="ai", content=answer)
            await repo.touch_session(session_id)
            await db.commit()

    async def _check_session_limit(self, user_id: uuid.UUID) -> None:
        """Refuse a new session at the limit, before the model is called and anything is saved.
        Two first messages sent at the same instant can both pass this check (no lock): the
        limit may then be exceeded by one, which the team accepted over database locking."""
        async with self._session_factory() as db:
            count = await ChatRepository(db).count_sessions(user_id)
        if count >= self._settings.max_sessions_per_user:
            raise SessionLimitReachedError

    async def _load_history(
        self, user_id: uuid.UUID, session_id: uuid.UUID | None
    ) -> list[HistoryMessage]:
        if session_id is None:
            return []
        async with self._session_factory() as db:
            repo = ChatRepository(db)
            if await repo.get_general_session(session_id, user_id) is None:
                raise SessionNotFoundError
            rows = await repo.recent_messages(session_id, self._settings.history_max_messages)
        history = []
        for row in rows:
            role = sender_to_role(row.sender)
            if role and row.content:
                history.append(HistoryMessage(role, row.content))
        return history

    async def _save_user_message(self, user_id: uuid.UUID, request: ChatRequest) -> uuid.UUID:
        async with self._session_factory() as db:
            repo = ChatRepository(db)
            session_id = request.session_id
            if session_id is None:
                session_id = (await repo.add_session(user_id, _title(request.message))).session_id
            else:
                await repo.touch_session(session_id)
            repo.add_message(session_id, sender="user", content=request.message)
            await db.commit()
        return session_id
