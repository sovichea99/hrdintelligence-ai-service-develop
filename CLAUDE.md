# HRD Intelligence AI Service

FastAPI service for general chat, folder chat and RAG (WBS 7.1–7.9) for the Korea Software HRD Center.
All models and data stay on the center's own servers. Student, alumni and institutional data is sensitive.

## Rules (read first; these override everything else, including the reference docs)

Security and data
- Never read, print, edit or commit `.env` (it holds the real LLM API key). Change names/placeholders only in `.env.example`.
- Never put secrets, URLs of internal servers or keys in code, tests, docs or commit messages.
- Authentication is never skipped, not even for local development or tests (tests sign their own tokens). Fail closed with 503.
- Never bypass authentication or authorization to make retrieval work. Retrieval must filter by what the user owns or has been shared (folder/file permissions: viewer, editor), and must ignore soft-deleted items (`deleted_at IS NULL`) and files not fully processed (`processing_status = completed`).
- Never index or return instructor student evaluations (`student_evaluation`, private by design) to anyone not authorized for them.
- Do not log or return student/alumni/institutional data in logs or error responses.
- Never create, alter or migrate database tables: the backend team owns the schema. Map existing tables only.

Honesty and verification
- Never fabricate citations or claim retrieval succeeded when it did not. If evidence is insufficient, say so.
- Never claim streaming works from an HTTP 200. Verify with timing: tokens must arrive spread over time (use the `verify-streaming` skill).
- Do not mark a WBS task complete without test evidence. Statuses: Not Started, In Progress, Blocked, Implemented — Testing Required, Completed and Verified, Completed with Limitations.

Change discipline
- Inspect existing code before changing it. Do not add libraries or abstractions without explaining why. Keep changes minimal and preserve working behavior.
- Do not decide open questions silently (see "Still open"). Ask, or put the choice behind a small interface so it can change.
- If a reference doc disagrees with this file or with the code, stop and report the conflict instead of picking one.

## Commands (Windows PowerShell; Python 3.11 + Poetry)

- Install: `poetry install` (add `--with ocr` for PaddleOCR and/or `--with surya` for Surya, needed only to OCR scans and images)
- Run: `poetry run uvicorn app.main:app --port 8080` (restart after editing `.env`)
- Tests: `poetry run pytest -v` (uses a fake vLLM server; no GPU or API key needed)
- One test with output: `poetry run pytest tests/test_chat_stream.py::test_streams_tokens_incrementally -v -s`
- Real OCR test (slow; downloads the model once): `$env:RUN_OCR_TESTS="1"; poetry run pytest tests/test_document_extraction.py -v -s` (macOS/Linux: `RUN_OCR_TESTS=1 poetry run ...`; `RUN_SURYA_TESTS=1` for the real Surya Khmer test)
- Use `curl.exe`, not `curl` (PowerShell alias). Inline JSON quoting breaks in PowerShell: put the body in a file and use `--data-binary "@body.json"`, or use a Python script.

## Structure (grow it only when a WBS task needs a module)

- `app/main.py`: `create_app()` factory, `/health`; tests inject parts through its keyword arguments
- `app/api/endpoints/chat.py`: `POST /api/v1/chat/stream` (SSE); `app/api/deps.py`: `get_current_user` (JWT + database check)
- `app/core/security.py`: Keycloak JWT verification (RS256 only); `app/core/config.py`: settings from env vars / `.env` (secrets are `SecretStr`)
- `app/services/chat_service.py`: chat turn logic; retrieval (7.2/7.3) is inserted in `prepare()` before the LLM call
- `app/services/history.py`: pure functions: merge same-role messages, trim history to the character budget
- `app/repositories/chat_repository.py`: ALL chat database access; every session query filters by owner
- `app/db/models.py`: SQLAlchemy mappings of the EXISTING tables `roles`, `users`, `chat_sessions`, `chat_messages` (schema `public`) and the ERD tables `ai.document_chunks` + `ai.chunk_embeddings` (never created or altered by us)
- `app/llm/client.py`: async client for the vLLM OpenAI-compatible API; `app/llm/prompts.py`: prompts
- `app/document_processing/`: `extract_document(bytes)`: PDF text layer or OCR per page, DOCX, PNG/JPEG; OCR engines behind `OcrEngine` in `ocr.py` (`OCR_ENGINE=paddle` in-process, `surya` via an inference server, `none`) (7.4). Sync and slow: call via `asyncio.to_thread`
- `app/rag/chunking.py`: pure functions: `chunk_document()` splits extracted pages into overlapping chunks (characters, not tokens), never across pages; every heading starts a new chunk and becomes its section title (7.5)
- `app/rag/embeddings.py`: `Embedder` interface; `OpenAICompatibleEmbedder` calls bge-m3 on vLLM `/v1/embeddings` (7.5; 7.2/7.3 reuse it for questions)
- `app/repositories/chunk_repository.py`: ALL `ai.document_chunks` / `ai.chunk_embeddings` access; `app/services/indexing_service.py`: `index_document(file_id, doc)`: chunk, embed, then replace the file's chunks in one transaction (7.5)
- `scripts/try_indexing.py`: manual check of 7.5 on one sample file (searches only that file, deletes its chunks after); not retrieval
- `scripts/check_real_db.py`: manual check that 7.5 storage works in the real `hrd_db` (synthetic chunks, deleted after); tests never touch `hrd_db`
- `app/storage/`: `FileStorage` interface for uploaded files: `S3FileStorage` (RustFS via boto3, `STORAGE_BACKEND=s3`) and `LocalFileStorage` (a folder, dev/tests) (7.6). Sync: call via `asyncio.to_thread`
- `app/repositories/file_repository.py`: ALL `public.files` access for ingestion; `app/services/ingestion_service.py`: background worker that polls `pending` files, reads them from storage, extracts (7.4), indexes (7.5) and writes the status; started in `main.py` when `INGESTION_ENABLED=true` (7.6)
- `tests/`: pytest; fake vLLM + temporary SQLite (schema `ai` mapped to none, foreign keys ON so INSERT order is checked like PostgreSQL does) + self-signed test JWTs, real uvicorn servers (real sockets, so streaming and disconnects are truly tested)

Reference target (not yet built): `app/rag/` retriever and citations.

## Chat contract (others depend on it; change it only with the team)

Request: `Authorization: Bearer <Keycloak JWT>`, body `{"message": "...", "session_id": "<uuid, optional>"}`. The server owns the history; the client sends only the new message.
SSE events: `session` `{"session_id": ...}` (always first), `token` `{"text": "..."}`, `done` `{}` (only after the answer is saved), `error` `{"message": "..."}` (only after streaming began).
Before streaming: 401 bad/missing token, 403 inactive or unknown account or unknown role, 404 session not found or not yours, 409 new chat refused because the user already owns the maximum number of sessions, 422 invalid body, 502 model error, 503 model/auth/config unavailable, 500 could not save.
A cut-off answer is never saved as complete; the user's question stays in the history. Tokens are fragments, not words (Khmer is split across tokens); clients must concatenate.

## Database tables this service touches (details: `docs/erd.md`)

One shared database `hrd_db`. Read-only unless stated.
- `users` and `roles` (match by `keycloak_id`; check `is_active`; role via `role_id` -> `roles.role_name` = `admin` | `instructor`; any other role is refused with 403)
- `chat_sessions` (read/write): `chat_type` `general` | `folder`, `folder_id` set for folder chat, `user_id` owner, `title`
- `chat_messages` (read/write): `sender` `user` | `ai`, `message_type` `text|chart|table|file`, `input_type` `text|voice`, `source` jsonb (citations), `visualization` jsonb, `file_id`
- `chat_session_files` (read/write): files selected for a folder chat
- `files` (`owner_id`, `folder_id`, `processing_status`, `deleted_at`), `folders` (`parent_folder_id`, `owner_id`, `deleted_at`), `permissions` (`viewer` | `editor`; a row has `file_id` OR `folder_id`)
- `ai.document_chunks` and `ai.chunk_embeddings` (read/write, WBS 7.5; designed as in the ERD, schema `ai`): chunks hold `content`, `content_type` (`image_text` for OCR chunks, else `text`), `page_number`, `section_title`, `extraction_method` (`text` | `ocr_paddle` | `ocr_surya`), `ocr_confidence` 0–100, `file_id`; each chunk has one `embedding vector(1024)` with `model_name` `bge-m3`. Created in `hrd_db` (verified 2026-10-29): `chunk_embeddings.chunk_id` references `document_chunks` with ON DELETE CASCADE, UNIQUE (chunk_id, model_name); no foreign key from `document_chunks.file_id` to `public.files` yet.

## Spec requirements not in the contract or code yet (from `docs/features.md`, `docs/ai-and-agents.md`)

Do not build these unprompted; they are listed so design choices don't block them.
- Voice input (speech-to-text) with a confirm/edit transcript step.
- Answers carry sources; if no relevant chunk is found reply "no information found".
- Output types beyond text: files (TXT, MD, DOCX, PPTX, PDF), charts (bar, line, donut), tables.
- Folder chat answers only from the files selected in `chat_session_files`; can generate slides from them.
- Emails drafted by chat are drafts until the user confirms; never send automatically.

## Decisions settled by the project documents (report Figures 1-2, section 2.1, ERD)

- The FastAPI AI service owns chat history: it reads and writes `chat_sessions` / `chat_messages` in PostgreSQL directly (Figure 2, "Chat history"; appendix 10.2 example).
- The AI service verifies the Keycloak JWT itself (section 2.1.7); user is matched via `users.keycloak_id`. Requests arrive through Spring Cloud Gateway.
- Vector store is pgvector inside the same PostgreSQL (`chunk_embeddings`, `VECTOR(1024)`); embedding model is BAAI/bge-m3. Retrieval filters by role and permissions in the pipeline.
- The report appendix (Text2SQL, Ollama, Chroma, snowflake-arctic-embed-m) comes from another project; do not copy its choices.
- Checked against the real `hrd_db` on 2026-10-29: `roles.role_name` holds exactly `admin` and `instructor` (lowercase); the enum-like columns of `roles`, `chat_sessions` and `chat_messages` are VARCHAR, not native enums; every column the models map exists with a compatible type and our inserts fill every NOT NULL column. Models stay as they are.
- One database, `hrd_db`, shared with the Spring backend (decided 2026-10-27; `ai_db` is not used). Reason: retrieval must join `chunk_embeddings` with file/folder permissions in one query, which separate databases cannot do safely. The backend team creates all tables there, including `chat_sessions`, `chat_messages` and `chunk_embeddings`.
- Two schemas in `hrd_db` (2026-10-29): `public` is Spring's; `ai` holds the AI service's own tables (pgvector 0.8.7 installed). Same database, so retrieval still joins `ai` with `public` permissions in one query. The AI service deletes a file's chunks and vectors itself when the file is deleted. Chunks are sized in characters by team decision, so `token_count` stays NULL.
- Chunk storage follows the ERD (decided 2026-10-29): two tables, `document_chunks` + `chunk_embeddings`, in schema `ai`; `ocr_confidence` 0–100 as in the ERD; `model_name` `bge-m3`; `content_type` `image_text` for OCR chunks, else `text`; Surya pages are stored as `extraction_method = ocr_surya` (value to be added to the ERD).
- Ingestion (WBS 7.6, decided 2026-10-29): the AI service POLLS `public.files` for `processing_status = 'pending'` (no queue, no Spring call) and writes ONLY `processing_status`, `processed_at`, `processing_error` of `public.files` (the one exception to "writes only its own tables"; needs a column-level UPDATE grant). Status values follow the ERD (`pending`, `processing`, `completed`, `failed`), not the plan's UPLOADED/READY. Files are read from RustFS (S3-compatible). Only PDF, DOCX, PNG, JPEG are indexed; TXT, MD, CSV, XLSX, PPTX are marked `failed` ("Unsupported file type"). `processing_error` holds short safe reasons only. Storage or embedding server unreachable = back to `pending` (retried), not `failed`. Status is written only while the file is still `processing` and not deleted, so a re-upload or delete by Spring meanwhile wins. Only `STORAGE_BUCKET` is ever read: the official bucket `documents` (2026-10-29; the other official buckets `profile-images`, `alumni-documents`, `reports` are never read, and a `storage_url` pointing at them is marked `failed`). The AI service should connect with its own restricted database user: read `users`, files, folders and permissions; read/write only its own chat and chunk tables.
- Session limit (decided 2026-10-29): the AI service enforces it. A user may own at most `MAX_SESSIONS_PER_USER` (default 10) chat sessions; a new chat beyond that gets HTTP 409 "Your session has reached the limit" before the model is called or anything is saved. Continuing an existing session is never blocked. Search, rename and delete of sessions stay with the Spring backend. The count is not locked, so two simultaneous first messages can exceed the limit by one (accepted).
- Language (decided 2026-10-29): general chat accepts and answers in English and Khmer; the docs' English-only rule and the "please rephrase" response are superseded. Input only has to be non-blank.
- The role is read from the database (`users.role_id` -> `roles.role_name`), not from a JWT claim (ERD, 2026-10-29).

## Still open (ask, do not assume)

- Whether to save the user's message while waiting for the model's first token instead of after it. Today the save (two INSERTs and a commit) sits between the first token and the start of the response; with a far-away development database that is about 1.4 s, so short answers arrive as one burst (measured 2026-10-30). Changing the order means the question is stored even when the model fails before its first token.
- Production hosting of bge-m3 and how the cluster reaches the GPU server. For development, bge-m3 runs on the GPU server (vLLM v0.20.1) behind the same temporary tunnel as Surya (test data only).
- Ingestion (7.6): the format Spring stores in `files.storage_url` (the code accepts `s3://bucket/key`, `http(s)://host/bucket/key`, or a key in `STORAGE_BUCKET`); whether `alumni-documents` should ever be indexed (alumni data, sensitive; not read now); a READ-ONLY RustFS key for the AI service (the dev key can also list and upload); `GRANT UPDATE (processing_status, processed_at, processing_error) ON public.files TO ai_app` once `files` exists. Only one ingestion worker runs at a time (PostgreSQL advisory lock), so requeueing files stuck in `processing` on start is safe with several instances. `.claude/rules/database.md` says "map only tables that already exist": `files` (like `users`, `chat_*`) is mapped from the ERD before Spring has created it.
- `ocr_surya` must be added to the ERD's `extraction_method` values (the column is VARCHAR, so it is accepted already). Whether `ai.document_chunks.file_id` gets the ERD's foreign key to `public.files` (then `scripts/check_real_db.py` needs `TEST_FILE_ID` of a test file row).
- Grants: the AI service connects as its own user `ai_app`. Verified 2026-10-29 in `hrd_db`: SELECT on `users` and `roles`; SELECT, INSERT, UPDATE on `chat_sessions` and `chat_messages` (enough for 7.1). Still needed for 7.2/7.3: SELECT on `public.files`, `folders`, `permissions`, `chat_session_files` (the tables exist; Spring creates them with Flyway).
- OCR engine per deployment: PaddleOCR (`OCR_LANGUAGE=en` for now, `korean` available) vs Surya (reads Khmer; needs the GPU server to host `datalab-to/surya-ocr-2` on `vllm/vllm-openai:v0.20.1`, and its model-weight licence confirmed). Decide from real sample documents. Note the schema also allows `extraction_method = ocr_tesseract`; confirm whether Tesseract is intended.
- Where instructor evaluations may appear in chat answers (private data): who is allowed to ask about them, and whether they are indexed at all.

## Real LLM server (verified)

OpenAI-compatible vLLM, needs an API key, model id `google/gemma-4-E2B-it`, context 16384 tokens. Base URL and key are in `.env` only.
Known behavior (re-measured 2026-10-30 from the development machine): about 1.9 s before the first token, then about 260 tokens/s streamed; the model has written planning text before answers in earlier runs (not seen in the 2026-10-30 runs); Khmer quality is only lightly tested.

## Reference docs (read only the part you need; do not load whole files)

- `docs/erd.md`: full schema (51 tables), enums, relationships. Use for model mapping and queries.
- `docs/ai-and-agents.md`: RAG pipeline, document processing, chatbot behaviour, automated agents.
- `docs/ai-implementation-plan.md`: phased AI build plan and agent-harness sketch. A plan, not final; its section 4 lists conflicts with this file (Ollama vs vLLM, who owns chat history, who sets retrieval scope). This file wins.
- `docs/features.md`: role permissions and feature requirements.
- `docs/workflows.md`: user flows (AI chatbot and folder chat sections matter most here).
- `.claude/rules/database.md` and `.claude/rules/retrieval.md`: detailed rules that load automatically when the matching files are edited (models/repositories; RAG, indexing, prompts).

## Git workflow

- `main` stable, `develop` integration. Branch from `develop` as `feature/wbs-7-x-short-name`; PR into `develop`. No direct pushes to `main` or `develop`.
- Never commit scratch files (`body.json`, `diag_llm.py`, `stream_*.py`).
- Commit messages: `feat(scope): ...`, `fix(...)`, `docs: ...`, `test: ...`, `chore: ...`.

## WBS progress (keep README in sync)

- [x] 7.1 General chat endpoint and LLM streaming (Completed with Limitations, verified 2026-10-30 against the real Keycloak, `hrd_db` and vLLM: real token accepted, role and `is_active` read from the database, history continued, foreign session 404, limit 409, 516 tokens streamed over 1.4 s; the real run found and fixed a bug where the first message was inserted before its session. Limitation: the user message is saved between the model's first token and the start of the response, so on a slow database link short answers arrive as one burst; see Still open)
- [ ] 7.2 Embeddings and vector retrieval
- [ ] 7.3 Folder-filtered retrieval and citations
- [x] 7.4 PDF/DOCX extraction and OCR (completed with limitations: Khmer read exactly by Surya on the GPU server, ~1 s/page, but only on a synthetic sample; PaddleOCR ~29 s/page on Mac CPU; Korean, encrypted PDFs and real scans untested; dev server reached through a temporary tunnel)
- [x] 7.5 Chunking and vector indexing (completed with limitations: stored in the ERD's `ai.document_chunks` + `ai.chunk_embeddings`; real write/delete verified as `ai_app` and one fictional sample DOCX run end to end; real bge-m3 verified on synthetic English/Khmer sentences; chunks sized in characters, not the ~500 tokens of the plan; scanned PDFs, Korean and large files not yet run through indexing)
- [ ] 7.6 File ingestion and indexing status (Implemented — Testing Required: worker, storage and status flow tested on SQLite with local storage; real RustFS read verified with a synthetic DOCX; not run end to end because `public.files` does not exist in `hrd_db` yet)
- [ ] 7.7 General chat UI
- [ ] 7.8 Folder chat UI and citations
- [ ] 7.9 End-to-end integration

## Working style

The owner of this service is learning: explain what and why in plain language, give exact commands, and do one meaningful step at a time.
At the start of a WBS task state its number, objective, what remains, status and acceptance criteria; at the end summarize what was done, files changed, tests run, outstanding issues, integration impact and next step. Use the `wbs-task` skill.