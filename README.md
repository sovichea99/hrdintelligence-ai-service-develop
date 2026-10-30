# HRD Intelligence AI Service

The AI service of **HRD Intelligence**, a platform for the Korea Software HRD Center. It answers questions in chat, either freely (general chat) or from the documents in a user's own folders (folder chat, using RAG: retrieval-augmented generation). All models and data stay on the center's own servers, because student, alumni and institutional data is sensitive.

> **Status:** WBS 7.1 (general chat with streaming, chat history in PostgreSQL, Keycloak login and role check, per-user session limit) is completed with limitations: verified against the real Keycloak, PostgreSQL and model on 2026-10-30. WBS 7.4 (PDF/DOCX text extraction and OCR) is completed with limitations. WBS 7.5 (chunking, embeddings and storage) is completed with limitations. WBS 7.6 (upload ingestion and status) is implemented; the real end-to-end check waits for the backend's `files` table. WBS 7.2, 7.3 and 7.7 to 7.9 are not started. See [WBS progress](#wbs-progress).

## Contents

[About the project](#about-the-project) · [Setup](#setup) · [Project structure](#project-structure) · [Database](#database) · [Chat streaming API](#chat-streaming-api) · [Document extraction](#document-extraction-python-module-no-http-endpoint-yet) · [Tests](#tests) · [Git workflow](#git-workflow) · [WBS progress](#wbs-progress) · [Known limitations](#known-limitations)

## About the project

### What this service does

| Feature | WBS | State |
|---|---|---|
| **General chat**: ask the language model anything; answers stream token by token; the conversation is saved and can be continued | 7.1, 7.7 | 7.1 implemented; UI not started |
| **Folder chat**: answers come from the documents in the chosen folder, with citations pointing to the source file and passage | 7.2, 7.3, 7.8 | not started |
| **Document processing**: read PDF and DOCX files, run OCR on scanned pages, split text into chunks | 7.4, 7.5 | 7.4 extraction + OCR implemented; 7.5 chunking implemented |
| **Indexing**: turn chunks into vectors and store them; report indexing status for each uploaded file | 7.5, 7.6 | 7.5 completed with limitations; 7.6 implemented, testing required |
| **End-to-end integration** with the gateway, the Spring services and the front end | 7.9 | not started |

Retrieval always respects permissions: a user only gets answers from files they own or that have been shared with them (viewer or editor).

### Where it fits

```
Front end ──► Spring Cloud Gateway ──► Spring Boot services (users, folders, files)
                      │
                      └──────────────► This service (FastAPI) ──► vLLM (chat model)
                                              │
Keycloak (login, JWT) ◄── verifies the token ─┤
PostgreSQL + pgvector ◄── chat history, vectors
```

- **Spring Cloud Gateway** receives requests from the front end and forwards them. **Keycloak** handles login and issues the JWT.
- The Spring Boot services own users, folders and files.
- **This service** verifies the Keycloak token itself, reads and writes the chat history (`chat_sessions`, `chat_messages`) in PostgreSQL, and talks to the model server. It never creates or alters database tables; the backend team owns the schema.

### Technology

| Area | Choice |
|---|---|
| API | Python 3.11, FastAPI, Server-Sent Events for streaming |
| Chat model | vLLM (OpenAI-compatible API), `google/gemma-4-E2B-it` |
| Database | PostgreSQL with SQLAlchemy 2.0 (async, `asyncpg`) |
| Vector search (planned) | pgvector in the same PostgreSQL, 1024-dimension vectors |
| Embeddings (planned) | BAAI/bge-m3 (multilingual) |
| Document extraction | pypdfium2 (PDF), python-docx (DOCX), Pillow (images) |
| OCR | PaddleOCR (in-process) or Surya (vision model on a vLLM server; reads Khmer) |
| Authentication | Keycloak JWT, RS256 only (PyJWT) |
| Tools | Poetry, pytest, Claude Code (`CLAUDE.md`, `.claude/`) |

### Team

The AI service (WBS 7) is built by the AI engineer of a three-person team. The backend team owns the gateway, login, database schema and the Spring services.

## Setup

Requires Python 3.11 and [Poetry](https://python-poetry.org/).

```bash
poetry install            # add --with ocr (PaddleOCR) and/or --with surya (Surya) to OCR scans and images
cp .env.example .env      # Windows PowerShell: Copy-Item .env.example .env
poetry run uvicorn app.main:app --reload --port 8080
```

Then edit `.env`:

| Variable | Meaning |
|---|---|
| `LLM_BASE_URL` | vLLM OpenAI-compatible base URL, ending in `/v1` |
| `LLM_MODEL` | exact model id (see `GET <LLM_BASE_URL>/models`) |
| `LLM_API_KEY` | API key if the server requires one. Ask the team lead privately. **Never commit `.env`.** |
| `DATABASE_URL` | PostgreSQL, `postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME` |
| `KEYCLOAK_ISSUER` | `https://KEYCLOAK_HOST/realms/REALM_NAME` (signing keys are fetched from `<issuer>/protocol/openid-connect/certs`) |
| `KEYCLOAK_JWKS_URL`, `KEYCLOAK_AUDIENCE` | optional |
| `HISTORY_MAX_MESSAGES`, `HISTORY_MAX_CHARS` | how much history is sent to the model (default 20 messages, 8000 characters) |
| `MAX_SESSIONS_PER_USER` | how many chat sessions one user may own (default 10); a new chat beyond it gets HTTP 409 |

The app reads `.env` only at startup, so restart uvicorn after changing it.

If `DATABASE_URL` or `KEYCLOAK_ISSUER` is empty the service still starts, but `/api/v1/chat/stream` answers **503**. Authentication is never skipped.

Health check: `curl http://localhost:8080/health`  
Interactive API docs: http://localhost:8080/docs (its "Try it out" button does not show streaming; use `curl -N`).

## Project structure

```
hrdintelligence-ai-service/
├── app/
│   ├── main.py                    create_app() factory and /health
│   ├── api/
│   │   ├── router.py              collects the endpoint routers under /api/v1
│   │   ├── deps.py                get_current_user: checks the JWT, then the users table
│   │   └── endpoints/chat.py      POST /api/v1/chat/stream (Server-Sent Events)
│   ├── core/
│   │   ├── config.py              settings read from environment variables / .env
│   │   └── security.py            Keycloak JWT verification (RS256 only)
│   ├── db/
│   │   ├── models.py              mappings of the existing tables (never creates tables)
│   │   └── session.py             async PostgreSQL engine and session factory
│   ├── document_processing/       extract_document(): PDF/DOCX/image text, OCR engines in ocr.py
│   ├── rag/
│   │   ├── chunking.py            split extracted pages into overlapping chunks (never across pages)
│   │   └── embeddings.py          Embedder interface; bge-m3 via an OpenAI-compatible server
│   ├── repositories/
│   │   ├── chat_repository.py    all chat database queries (always filtered by owner)
│   │   └── chunk_repository.py   all ai.document_chunks / ai.chunk_embeddings queries
│   ├── schemas/chat.py            request body of the chat endpoint
│   ├── services/
│   │   ├── chat_service.py        one chat turn: history, model call, saving
│   │   ├── indexing_service.py    index a file: chunk, embed, replace its chunks in one transaction
│   │   └── history.py             pure functions that build and trim the model messages
│   └── llm/
│       ├── client.py              async client for the vLLM OpenAI-compatible API
│       └── prompts.py             system prompts
├── scripts/try_indexing.py        try the 7.5 pipeline on one sample file and search it
├── scripts/check_real_db.py       check 7.5 storage in the real database (synthetic data, cleaned up)
├── tests/                         pytest: fake vLLM, temporary SQLite, self-signed tokens
│   ├── conftest.py                fixtures (fake model server, database, running app)
│   ├── helpers.py                 test keys and token builders
│   ├── fixtures/khmer_sample.png  synthetic Khmer image for the real Surya test
│   ├── test_chat_stream.py        endpoint behaviour, streaming timing, errors, ownership
│   ├── test_chunking.py           chunk sizes, overlap, page numbers, Khmer boundaries
│   ├── test_document_extraction.py  PDF/DOCX/image extraction, OCR engines, limits
│   ├── test_embeddings.py         embedding client against a fake server; opt-in real bge-m3 test
│   ├── test_indexing.py           storing chunks: metadata, re-indexing, failures (SQLite only)
│   ├── test_ingestion.py          upload worker: pending -> completed/failed, deleted files, requeue, logs
│   ├── test_storage.py            storage_url formats, local folder storage
│   ├── test_config.py             printing settings never shows secrets
│   ├── test_history.py            history building and trimming
│   └── test_security.py           token verification and forged-token cases
├── .claude/                       Claude Code settings, hooks, skills and reviewer agents
├── CLAUDE.md                      project rules and decisions for Claude Code
├── .env.example                   template for .env (copy it; never commit .env)
├── pyproject.toml / poetry.lock   dependencies (Poetry, Python 3.11)
└── README.md
```

How a request flows: `chat.py` (endpoint) → `deps.py` (who is the user?) → `chat_service.py` (what to ask the model) → `chat_repository.py` (database) and `llm/client.py` (model).

Folders for later tasks are added only when needed: `app/rag/` (embeddings, retrieval, citations) and `app/vector_store/`.

## Database

The service maps the **existing** tables `roles`, `users`, `chat_sessions` and `chat_messages` (schema `public`, see the ERD) and, as in the ERD, `ai.document_chunks` (chunk text) + `ai.chunk_embeddings` (one bge-m3 vector per chunk, pgvector) in schema `ai`, the AI service's own tables. It never creates or alters tables. The AI service deletes a file's chunks itself when the file is deleted. Chunks are sized in characters, so `token_count` is left empty; `ocr_confidence` is stored 0–100. ENUM columns are plain VARCHAR in the real `hrd_db` (checked 2026-10-29), so the models treat them as strings.

## Chat streaming API

`POST /api/v1/chat/stream`

```
Authorization: Bearer <Keycloak JWT>
{"message": "Hello", "session_id": "<uuid, optional>"}
```

Omit `session_id` to start a new general chat session; send the one you received to continue it. The server keeps the history, so send only the new message.

Response is Server-Sent Events:

```
event: session
data: {"session_id": "3f0c..."}

event: token
data: {"text": "Hel"}

event: done
data: {}
```

- `session` is always the first event.
- Tokens are text fragments, not whole words (Khmer words are split across several tokens). Clients must concatenate them.
- `done` is sent only after the answer is saved to the database.
- A cut-off answer is never saved as complete: the stream ends with `event: error` and the user's question stays in the history.

| Situation | Result |
|---|---|
| Missing, expired or invalid token | HTTP 401 |
| Valid token, but the account is unknown, inactive, or its role is not `admin` or `instructor` | HTTP 403 |
| `session_id` does not exist, is not a general chat, or belongs to another user | HTTP 404 |
| New chat (no `session_id`) while the user already owns the maximum number of sessions (`MAX_SESSIONS_PER_USER`, default 10) | HTTP 409, detail `"Your session has reached the limit"`; nothing is saved. Continuing an existing session still works |
| Invalid body (empty message, bad `session_id`) | HTTP 422 |
| Model returned an error or an empty answer (before the first token) | HTTP 502 |
| Model unreachable / auth service unreachable / service not configured | HTTP 503 |
| Could not save the message | HTTP 500 |
| Failure after streaming began | `event: error` then the stream ends |

On Windows PowerShell, quoting JSON inline is unreliable. Save the body to `body.json` and use:

```powershell
curl.exe -N -X POST http://localhost:8080/api/v1/chat/stream -H "Content-Type: application/json" -H "Authorization: Bearer $env:TOKEN" --data-binary "@body.json"
```

## Upload ingestion (WBS 7.6)

Spring stores the uploaded file in RustFS (S3-compatible) and creates a `files` row with `processing_status = 'pending'`.
With `INGESTION_ENABLED=true`, a background worker in this service picks those files up, one at a time:

```
pending -> processing -> completed            (chunks and vectors stored)
                      -> failed + reason      (processing_error, e.g. "Unsupported file type")
```

- Reads the file from `STORAGE_*` (RustFS: the S3 API address, not the web console; use a read-only key).
- Indexes PDF, DOCX, PNG and JPEG. TXT, MD, CSV, XLSX and PPTX are marked `failed` for now.
- Writes only `processing_status`, `processed_at` and `processing_error` of `files`; it needs that UPDATE grant.
- Removes the chunks of files that were soft-deleted or no longer exist.
- If RustFS or the embedding server is unreachable, the file goes back to `pending` and is retried; it is not failed.
- Only one worker runs at a time, even with several instances (PostgreSQL advisory lock). Files left in `processing` (the service stopped mid-file) go back to `pending` on start.
- Only `STORAGE_BUCKET` is read, whatever `storage_url` says: the official bucket `documents`. The other buckets (`profile-images`, `alumni-documents`, `reports`) are never read.
- Logs show file ids, counts and durations only, never file names, paths or document text.

## Document extraction (Python module, no HTTP endpoint yet)

`app.document_processing.extract_document(data: bytes)` returns per-page text:

- **PDF**: pages with a text layer are read directly; pages without one (scans) are rendered at `PDF_OCR_DPI` and OCR'd.
- **DOCX**: body paragraphs and tables in reading order; headings (English "Heading N" styles) become Markdown `#`.
- **PNG/JPEG**: OCR, with a confidence score (0–1).

The type is detected from the file content, not the name. Failures raise a `DocumentError` subclass
(unsupported, too large, corrupt, encrypted, OCR unavailable) whose message never contains document text.
Limits: `MAX_DOCUMENT_MB`, `MAX_PDF_PAGES`, `MAX_OCR_PAGES` (scanned pages per document), 50 MP per image,
200 MB unzipped per DOCX.

OCR runs on our own machines. Choose the engine with `OCR_ENGINE`:

| `OCR_ENGINE` | Install | Notes |
|---|---|---|
| `paddle` (default) | `poetry install --with ocr` | In-process. `OCR_LANGUAGE` picks the model (`en`, `korean`, ...). |
| `surya` | `poetry install --with surya` | Vision model that reads Khmer. Runs on an inference server: set `SURYA_INFERENCE_URL` (+ `SURYA_INFERENCE_API_KEY`) to a server hosting `datalab-to/surya-ocr-2` (e.g. vLLM on the GPU server). If unset, Surya starts a local `llama-server` itself (Mac: `brew install llama.cpp`) and downloads the model once. Licence: Apache-2.0 code; check the model weights' terms before deploying. |
| `none` | – | Any page that needs OCR fails the whole document. |

**Surya server: use `vllm/vllm-openai:v0.20.1`** (the version Surya 0.22 targets). vLLM 0.32.0 cut off the start
of every answer, so Surya could not parse it. Measured on an H100 with v0.20.1: about 1 s per page once warm.
`SURYA_INFERENCE_URL` must end in `/v1`, and `/health` must be reachable without login headers (no Cloudflare Access).

Extraction is synchronous and can be slow for scans (PaddleOCR measured about 29 s per page on a Mac CPU),
so call it from a background task.

**Offline servers:** on first use PaddleOCR downloads its models (about 130 MB) from Hugging Face into
`~/.paddlex/official_models` (move it with `PADDLE_PDX_CACHE_HOME`). For a server without internet,
copy that folder into the Docker image at build time. No documents are ever sent anywhere.

**Not extracted yet:** images, headers/footers, footnotes, text boxes and nested tables inside a DOCX;
password-protected DOCX files are reported as unsupported. A PDF page with 20+ characters of text is
never OCR'd, so a scan with a typed header loses the scanned part.

## Tests

```bash
poetry run pytest -v
RUN_OCR_TESTS=1 poetry run pytest tests/test_document_extraction.py -v -s     # real PaddleOCR (macOS/Linux)
RUN_SURYA_TESTS=1 poetry run pytest tests/test_document_extraction.py -v -s   # real Surya, reads a Khmer sample
RUN_EMBEDDING_TESTS=1 poetry run pytest tests/test_embeddings.py -v -s        # real bge-m3 (EMBEDDING_BASE_URL)
```

Tests never touch the real database. To check 7.5 storage in `hrd_db` by hand (vector round trip, then write and delete synthetic chunks):

```bash
poetry run python scripts/check_real_db.py
```

Try indexing on one sample file (extract, chunk, embed, store, search that file only, delete). Sample documents only:

```bash
poetry run python scripts/try_indexing.py ~/Downloads/sample.docx "What is the attendance rule?"
```

On Windows PowerShell: `$env:RUN_OCR_TESTS="1"; poetry run pytest tests/test_document_extraction.py -v -s` (same for `RUN_SURYA_TESTS`).
The Surya test uses `SURYA_INFERENCE_URL` / `SURYA_INFERENCE_API_KEY` from the environment or `.env`; without a
URL it starts a local `llama-server` and downloads a 2.7 GB model on first run.

Tests start a fake vLLM server and a temporary SQLite database, and sign their own JWTs, so no GPU, API key, Keycloak or PostgreSQL is needed. They include a timing test that proves tokens arrive incrementally and a test that closing the connection stops the model. Document tests use a fake OCR engine; the two real-OCR tests above are opt-in.

## Git workflow

- `main`: stable. `develop`: integration branch.
- Branch from `develop` as `feature/wbs-7-x-short-name`, open a pull request into `develop`.
- No direct pushes to `main` or `develop`. `develop` is merged into `main` once the end-to-end checks pass.

## WBS progress

- [x] 7.1 General chat endpoint and LLM streaming (completed with limitations: verified 2026-10-30 against the real Keycloak, `hrd_db` and vLLM; see Known limitations for the first-token delay)
- [ ] 7.2 Embeddings and vector retrieval
- [ ] 7.3 Folder-filtered retrieval and source citations
- [x] 7.4 PDF/DOCX extraction and OCR (completed with limitations: Khmer read exactly by Surya on the GPU server, ~1 s/page, but only on a synthetic sample; PaddleOCR ~29 s/page on CPU; Korean, encrypted PDFs and real scans untested; dev server reached through a temporary tunnel)
- [x] 7.5 Document chunking and vector indexing (completed with limitations: real writes to the ERD tables and one fictional sample DOCX verified; chunks sized in characters, not tokens; scanned PDFs, Korean and large files not yet run through indexing)
- [ ] 7.6 File ingestion and indexing status (implemented, testing required: tested with SQLite and a local folder; real RustFS read verified with a synthetic file; end to end waits for the backend's `files` table)
- [ ] 7.7 General AI chat interface
- [ ] 7.8 Folder AI chat interface and citations UI
- [ ] 7.9 End-to-end integration

## Known limitations

- Before the first token the user waits for the model's first token (about 1.9 s measured 2026-10-30) plus the time to save their message to the database. With a far-away development database that save is about 1.4 s, and tokens generated meanwhile arrive together; with the database next to the service it is negligible. Long answers then stream at the model's pace (516 tokens over 1.4 s measured).
- The model writes planning text before its answer (to be fixed in 7.1; needs a check against the real server).
- Khmer quality is only lightly tested (small model: `google/gemma-4-E2B-it`).
- The history limit is a character estimate, not a real token count.
- The session limit is checked without a database lock: two first messages sent at the same instant can exceed it by one.
- OCR (7.4): only a synthetic Khmer sample is verified; real scans and Korean are untested. Documents sent to the Surya server through a Cloudflare tunnel pass through Cloudflare, so use test documents only until the service runs on the same server.
