"""Request schema for the chat endpoints (shared contract with backend/frontend)."""

import uuid

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """One new user message. Omit `session_id` to start a new conversation; send the id from the
    `session` event to continue it. The conversation history is kept by this service."""

    message: str = Field(max_length=8000)
    session_id: uuid.UUID | None = None

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value
