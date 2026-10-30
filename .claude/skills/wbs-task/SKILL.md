---
name: wbs-task
description: Work on one WBS 7.x task of the AI service end to end (explain, inspect, design, implement, test, verify, report). Use when starting or continuing a WBS task such as "start 7.2".
---

Work on: $ARGUMENTS

Follow this order. Do not skip steps and do not do the next WBS task in the same go.

## 1. Announce
State the WBS number and name, its objective in plain language, what remains to be done, the current status, and the acceptance criteria. Statuses: Not Started, In Progress, Blocked, Implemented — Testing Required, Completed and Verified, Completed with Limitations.

## 2. Check open decisions
Read the "Still open (ask, do not assume)" and "Decisions settled" sections of CLAUDE.md. If this task depends on an open item (embedding host, database access and grants, auth claims, ENUM column types, OCR engine), ask the user instead of guessing. If they cannot answer, put the choice behind a small interface and say so.

## 3. Inspect before changing
Read the files this task touches (use Glob/Grep). Say what already works and what is missing. Do not rewrite working code.
Then open only the reference docs this task needs, not whole files: the tables involved in `docs/erd.md` (for retrieval and ingestion tasks: `files`, `folders`, `permissions`, `document_chunks`, `chunk_embeddings`; for chat tasks: `chat_sessions`, `chat_messages`, `chat_session_files`), the relevant part of `docs/ai-and-agents.md` or `docs/workflows.md`. `docs/ai-implementation-plan.md` is a plan, not final architecture. If a doc conflicts with CLAUDE.md or the code, stop and report the conflict; CLAUDE.md wins until the user decides.

## 4. Design
Describe the data flow, the new or changed files, request/response shapes and which modules later tasks will reuse. Keep the streaming contract in CLAUDE.md stable. Do not design in features from "Spec requirements not in the contract or code yet" unless this task asks for them.

## 5. Implement the minimum
Create or modify only what this task needs. Include input validation, error handling, logging without sensitive data, and authorization checks where data access is involved (ownership and permissions, `deleted_at IS NULL`, `processing_status = completed`). Never create or alter database tables: map existing ones only. Explain any new library before adding it.

## 6. Test
Add tests. Run `poetry run pytest -v`. For streaming use the `verify-streaming` skill. Report real output, not expectations.

## 7. Verify and report
Tick an acceptance criterion only with evidence. If something could not be verified (for example the real LLM server was unreachable), say so and use "Implemented — Testing Required" or "Completed with Limitations".
Finish with: what was accomplished, files changed, tests run and results, outstanding issues, integration impact (contract, tables used, env variable names, doc conflicts found), next step. Update the WBS checklist in README.md and CLAUDE.md.
