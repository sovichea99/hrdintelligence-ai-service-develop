"""All database access for chat. Every query that touches a session filters by the owner."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ChatSession, Role, User


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ChatRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_user_with_role(
        self, keycloak_id: uuid.UUID
    ) -> tuple[User, str | None] | None:
        """The user row and its role name (`roles.role_name`), or None if there is no such user.
        The role is None when `users.role_id` is NULL; callers must treat that as no access.
        `keycloak_id` is unique in the ERD, so more than one row is an error, not a choice."""
        stmt = (
            select(User, Role.role_name)
            .outerjoin(Role, Role.role_id == User.role_id)
            .where(User.keycloak_id == keycloak_id)
        )
        row = (await self._db.execute(stmt)).one_or_none()
        return None if row is None else (row[0], row[1])

    async def count_sessions(self, user_id: uuid.UUID) -> int:
        """All chat sessions the user owns (general and folder), for the per-user limit."""
        stmt = select(func.count()).select_from(ChatSession).where(ChatSession.user_id == user_id)
        return int((await self._db.execute(stmt)).scalar_one())

    async def get_general_session(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatSession | None:
        """Only the owner's general chat sessions. Anything else looks like "not found"."""
        stmt = select(ChatSession).where(
            ChatSession.session_id == session_id,
            ChatSession.user_id == user_id,
            ChatSession.chat_type == "general",
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def recent_messages(self, session_id: uuid.UUID, limit: int) -> list[ChatMessage]:
        """The latest `limit` messages, oldest first."""
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        rows = (await self._db.execute(stmt)).scalars().all()
        return list(reversed(rows))

    async def add_session(self, user_id: uuid.UUID, title: str) -> ChatSession:
        now = _now()
        session = ChatSession(
            session_id=uuid.uuid4(),
            title=title,
            chat_type="general",
            created_at=now,
            updated_at=now,
            user_id=user_id,
            folder_id=None,
        )
        self._db.add(session)
        # The models declare no relationship() (see .claude/rules/database.md), so SQLAlchemy
        # does not know a message depends on its session and may INSERT the message first;
        # the real chat_messages foreign key then fails. Flushing here makes the session row
        # exist before any message is added in the same transaction.
        await self._db.flush()
        return session

    def add_message(
        self,
        session_id: uuid.UUID,
        *,
        sender: str,
        content: str,
        input_type: str = "text",
    ) -> ChatMessage:
        message = ChatMessage(
            message_id=uuid.uuid4(),
            sender=sender,
            message_type="text",
            content=content,
            visualization=None,
            input_type=input_type,
            created_at=_now(),
            source=None,
            session_id=session_id,
            file_id=None,
        )
        self._db.add(message)
        return message

    async def touch_session(self, session_id: uuid.UUID) -> None:
        await self._db.execute(
            update(ChatSession).where(ChatSession.session_id == session_id).values(updated_at=_now())
        )
