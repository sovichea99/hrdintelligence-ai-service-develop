"""SQLAlchemy mappings for the EXISTING tables (see the ERD).

This service never creates or alters these tables: the schema is owned by the backend team.
Only the columns this service uses are declared. Spring's tables are in the `public` schema;
the AI service's own tables are in the `ai` schema of the same database.

Assumption to confirm with the schema owner: ENUM columns are mapped as plain strings, which is
right when they are VARCHAR (Spring/JPA `EnumType.STRING`). If they are native PostgreSQL enum
types, inserts will fail and these columns need `Enum(..., name=..., create_type=False)`.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import BigInteger, JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    role_name: Mapped[str] = mapped_column(String)  # "admin" | "instructor"


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    keycloak_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_active: Mapped[bool | None] = mapped_column(Boolean)
    role_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("roles.role_id"))


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(150))
    chat_type: Mapped[str] = mapped_column(String)  # "general" | "folder"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"))
    folder_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    sender: Mapped[str] = mapped_column(String)  # "user" | "ai"
    message_type: Mapped[str] = mapped_column(String)  # "text" | "chart" | "table" | "file"
    content: Mapped[str | None] = mapped_column(Text)
    visualization: Mapped[dict | None] = mapped_column(JsonType)
    input_type: Mapped[str] = mapped_column(String)  # "text" | "voice"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[dict | None] = mapped_column(JsonType)  # citations, from 7.3 on
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.session_id"))
    file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class File(Base):
    """Uploaded file (Spring's `files`). The AI service only reads it, except the three
    processing_* columns that ingestion (WBS 7.6) writes."""

    __tablename__ = "files"

    file_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    extension: Mapped[str] = mapped_column(String)  # "txt" | "md" | "xlsx" | "csv" | "pdf" | "docx" | "pptx" | "png" | "jpeg"
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_url: Mapped[str] = mapped_column(Text)
    processing_status: Mapped[str] = mapped_column(String)  # "pending" | "processing" | "completed" | "failed"
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_error: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunk(Base):
    """One searchable passage of a file (WBS 7.5, ERD `document_chunks`). The AI service deletes a
    file's chunks itself when the file is deleted (7.6)."""

    __tablename__ = "document_chunks"
    __table_args__ = {"schema": "ai"}

    chunk_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(20))  # "text" | "title" | "table" | "image_text"
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(255))
    token_count: Mapped[int | None] = mapped_column(Integer)  # not filled: chunks are sized in characters
    # "text" | "ocr_paddle" | "ocr_tesseract" | "ocr_surya" (ocr_surya still to be added to the ERD)
    extraction_method: Mapped[str] = mapped_column(String(20))
    ocr_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2, asdecimal=False))  # 0..100, OCR only
    metadata_: Mapped[dict | None] = mapped_column("metadata", JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    file_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class ChunkEmbedding(Base):
    """The vector of one chunk (WBS 7.5, ERD `chunk_embeddings`)."""

    __tablename__ = "chunk_embeddings"
    __table_args__ = {"schema": "ai"}

    embedding_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(1024))
    model_name: Mapped[str] = mapped_column(String(50))  # "bge-m3"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai.document_chunks.chunk_id"))
