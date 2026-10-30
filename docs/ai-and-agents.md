# AI Chatbot, RAG & Automated Agents

## 1. Architecture
- Local LLM served with **vLLM** (organizational data stays in the local/private environment). Service is **Python + FastAPI**.
- **RAG**: embed question, vector search over authorized docs only, rank/pick top chunks, build prompt (question + context), generate with Local LLM, check the answer is grounded, attach sources.
- **Embeddings**: BGE-M3 (`BAAI/bge-m3`), 1024 dims, stored in PostgreSQL `pgvector` (`chunk_embeddings.embedding vector(1024)`).
- **Document processing**: PaddleOCR (text detect/recognize, confidence, multilingual, local), PP-StructureV3 (titles/paragraphs/tables, output Markdown/JSON, better chunking), Surya (structure detection, Khmer support). Result goes to `document_chunks` (`content_type`: text, title, table, image_text; `extraction_method`: text, ocr_paddle, ocr_tesseract; `ocr_confidence` 0–100).
- **External data**: RDA API (attendance, names, check-in/out) and Assessment API (students, scores, staff, class, course, org chart).

## 2. Chatbot behaviour
- Language: English. Input: text or voice (speech-to-text; user confirms transcript, can edit or re-record). Empty or non-English input gets "please rephrase".
- Actions: answer queries, generate summaries/insights, write/send emails (needs user confirmation; also delete email with confirm), generate charts and tables.
- Output: text with sources; files (TXT, MD, DOCX, PPTX, PDF) with preview and download; charts (bar, line, donut) and data tables exportable as images.
- If no relevant data is found: reply that no information was found.
- **Chat history**: recent 10 sessions kept. At the limit the user must delete an old session (or the oldest) to create a new one. Search, rename, delete, continue past sessions.
- **General AI chat**: scope is all data the user owns or that is shared with them, plus authorized HRD data per role (admin: students, attendance, scores, allowances, alumni, policies; instructor: authorized data only).
- **Folder-specific AI chat**: isolated session in a folder (`chat_sessions.chat_type = folder`, `folder_id` set; selected files in `chat_session_files`). Answers strictly from selected files. Can generate slides from folder documents (e.g. lesson notes).
- Tables: `chat_sessions`, `chat_messages` (`message_type`: text, chart, table, file; `visualization` jsonb; `source` jsonb; `input_type`: text, voice), `chat_session_files`.

## 3. Automated AI agents (Admin; Instructor sees a limited list)
Admin can enable/disable each agent, pause/resume, edit schedule, and "Run Now" in addition to automatic runs. Agent page: agent list, enabled toggle, agent info (status, type, schedule, recipients, output), flow board (trigger, AI step, AI step, actions), live log, recent runs table (started, agent, status, summary), reports page (report, source, generated, period, status; filter by type and period; export PDF/Excel with section choice).

| Agent (`agent_code`) | Type | What it does |
| --- | --- | --- |
| `weekly_summary` | Scheduled | Friday email to admins covering student attendance and extra hours; saves a PDF to Reports. Table `weekly_summaries`. |
| `feedback_summary` | Scheduled | Weekly student progress/issue report from instructor evaluations; per-student trend (improving, stable, declining, needs_support). Tables `ai_reports`, `report_student_summaries`. |
| `alumni_profile` | Scheduled | Every 6 months emails alumni asking for latest job details (creates `profile_update_requests` with `trigger_type = ai_scheduled`). |
| `at_risk` | Trigger | When attendance or grades drop, drafts warning emails for admin to review/edit and confirm send. Table `draft_emails` (`email_type = at_risk_warning`). |
| `alumni_job_alert` | Trigger | Notifies admins when alumni submit career/industry updates. |

Run lifecycle: `agent_logs.status` running, succeeded, failed; `triggered_by` schedule, event, manual; `retry_count`. Per-agent config in `agent_configurations` (one per agent: `cron_expression` for scheduled, `trigger_event` for trigger agents, `recipients`: all_admins, hrd_admin, all_alumni). Per-user opt-in in `user_agent_settings`.

## 4. Safety rules to keep in code
- Retrieval must filter by what the current user owns or has been shared (`files.owner_id`, `permissions`) before vector search.
- Student evaluations are private (`student_evaluation.is_private`); never expose them to students or to unauthorized roles through the chatbot.
- Emails drafted by the chatbot or agents are never sent without explicit user confirmation.
