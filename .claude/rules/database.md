---
paths:
  - "app/db/**"
  - "app/repositories/**"
---

# Database rules (loaded when touching models or repositories)

The schema belongs to the backend team. Column details: `docs/erd.md`.

## Mapping tables

- Map only tables that already exist in `hrd_db`. Never add `create_all`, Alembic, DDL, triggers or indexes.
- Enum columns are mapped as `String` until the team confirms whether the real database uses native PostgreSQL enums (open question in `CLAUDE.md`). Do not switch to `sqlalchemy.Enum` silently.
- Map only the columns the service reads or writes. Fewer mapped columns means fewer breaks when the backend changes something we do not use.
- Primary keys are `uuid`, timestamps are `timestamptz`. Keep `DateTime(timezone=True)`.
- Do not add relationships, cascades or `ondelete` behaviour that the real foreign keys may not have. Join explicitly in queries instead.

## Writing queries

- Every query on `chat_sessions`, `chat_messages` and `chat_session_files` filters by the owner (`chat_sessions.user_id`). A session id alone is never enough.
- `files` and `folders` are soft-deleted: always add `deleted_at IS NULL`.
- Only files with `processing_status = 'completed'` may be used for retrieval or listed as sources.
- Access to a file is: `files.owner_id = user` OR a `permissions` row for that user on the file OR on its folder (`permission` is `viewer` or `editor`, both allow reading). Folder permissions apply to files inside the folder; check the parent chain only if the team confirms inheritance.
- `permissions` rows set `file_id` OR `folder_id`, never both. Handle both shapes.
- `users` is read-only: match by `keycloak_id`, check `is_active`, read the role through `role_id -> roles.role_name` (`admin` | `instructor`).
- The service writes only to its own tables: `chat_sessions`, `chat_messages`, `chat_session_files`, `document_chunks`, `chunk_embeddings`. Everything else is read-only.

## Sessions and transactions

- All database access goes through a repository class. Endpoints and services never import `select` or build queries.
- Use the async session from `app/db/session.py`. One request, one session, one commit. Do not commit inside a loop of SSE tokens.
- A failed save must surface as HTTP 500 before `done` is sent, never as a silently missing message.

## Testing

- Tests run on a temporary SQLite database with the same models. Anything PostgreSQL-only (`vector`, `jsonb` operators, `ILIKE` on arrays) needs a guard or a dialect-specific test that is skipped on SQLite.
- Never point tests at the real `hrd_db`.
