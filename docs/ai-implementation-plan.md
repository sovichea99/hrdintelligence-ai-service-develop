# AI Service Implementation Plan ("HRD Intelligence Sharing")

Source: *HRD Intelligence Sharing* (11-page sharing/planning document). It is a **build plan and design sketch**, not the final architecture. Several of its tool choices differ from the project documents; see "Conflicts" before using it.

## 1. Target flows

### RAG, offline ingestion (async)
Upload (Spring saves file to MinIO) -> Parse / OCR (PDF, image, Excel, text) -> Chunk (small pieces plus metadata) -> Embed (bge-m3, in batches) -> Store (pgvector and full-text).
A Redis queue feeds a Python worker. File status goes UPLOADED -> PROCESSING -> READY.

### RAG, online question to answer (streamed)
Question (text or voice) -> Authorize (Spring sets folder scope) -> Rewrite (standalone query) -> Hybrid search (vector, keyword, rerank) -> Agent harness (search, SQL, chart, mail) -> Local LLM (Qwen on vLLM) -> Output (text, chart, file, slides) -> Save (Spring stores history).
If the relevance score is low, answer "not found in your documents" instead of guessing.

### Agent harness (chat tool-using agent)
1. **Context builder**: user scope (role, folders, files), memory (recent turns + older summary), system prompt (answer only from context).
2. **Reasoning loop, max 6 steps**: Think (pick next tool or answer) -> Act (run one tool call) -> Observe (read result) -> Finish (cited answer plus cards). Observe returns to Think until the answer is complete or the step limit is hit.
3. **Tool registry, read-only by design**: Search docs (scoped hybrid RAG), Query data (read-only SQL views), Make output (chart, file, slides), Draft email (draft only, never send), Suggest action (buttons for next steps).
4. **Guardrails around every call**: scope filter (enforced in SQL), schema check (valid JSON, else retry), **no send tool** (Spring sends after approval), audit log (question, tools, sources).

### Scheduled / event agent flow
- Triggers, all handled by Spring Boot: Schedule (Quartz cron, admin editable), Event (attendance, grade, alumni form), Run now (admin button). Each agent has an enable switch; disabled agents skip silently.
- One pipeline for every agent: Collect (Spring SQL for the period) -> Detect (rules in code, auditable) -> Write (LLM summary or draft) -> Deliver (email or admin draft) -> Log (`agent_logs`). **Code decides what is wrong; the LLM only words it.** Failures retry, then log.
- Five agents: Weekly summary (Friday, attendance and extra hours to admins), Feedback summary (weekly, instructor notes to progress report), Alumni profile (every 6 months, email only, no AI needed), At-risk agent (event: attendance or grade drop, draft warning email), Alumni job alert (event: form submitted, notify admins). See `ai-and-agents.md`.
- A separate file `two_stage_system_architecture_multi_format_export_flow.md` is referenced by the source but was **not provided**.

## 2. Build phases (39 steps)

### Phase 1: Core AI chatbot
| Step | What | Tools | Method |
| --- | --- | --- | --- |
| 1 | Run a local LLM | Ollama | Download and run a suitable model locally |
| 2 | Python AI service | Python, FastAPI | API that receives a question and calls the LLM |
| 3 | Connect Spring Boot to Python | Spring Boot, RestClient | HTTP client sending questions to the Python service |
| 4 | Upload documents | Spring Boot, object storage | Validate files, store, save metadata |
| 5 | Extract content | PyMuPDF, openpyxl, python-docx, OCR | Text from PDFs, spreadsheets, Word, images |
| 6 | Chunk documents | Python | Smaller searchable sections, preserve source info |
| 7 | Embeddings | Ollama embedding model | Vectors for chunks |
| 8 | Store knowledge | PostgreSQL, pgvector | Chunks, metadata, embeddings |
| 9 | RAG retrieval | Python, pgvector | Embed question, retrieve relevant **authorized** chunks |
| 10 | Grounded answers | LLM, Python | Question + evidence to LLM, answer with source citations |

Result: users ask questions and get answers based on internal documents. Flow: upload -> extract -> chunk -> embed -> pgvector; question -> retrieve -> LLM -> answer + citations.

### Phase 2: Chat history and folder chat
| Step | What | Tools | Method |
| --- | --- | --- | --- |
| 11 | Store conversations | PostgreSQL, Spring Boot, MyBatis | Save sessions and messages |
| 12 | Manage history | Spring Boot, Next.js | Search, rename, delete, continue; show the 10 most recently updated sessions |
| 13 | Folders and organization | Spring Boot, PostgreSQL, object storage | Associate documents with folders, manage permissions |
| 14 | Folder-specific chat | Python, pgvector, Spring Boot | Restrict retrieval to authorized documents in the selected folder |
| 15 | Folder presentations | Python, python-pptx | Retrieve folder knowledge, slide outline, create PPTX |

Flow: open folder -> verify folder permission -> question -> retrieve only authorized folder content -> answer + citations -> save conversation.

### Phase 3: Data analysis, charts, files
| Step | What | Tools | Method |
| --- | --- | --- | --- |
| 16 | Connect AI to app data | Spring Boot, MyBatis | Authorized APIs for attendance, grades, courses |
| 17 | Analyze structured data | Python, SQL, pandas | Totals, averages, trends in deterministic code |
| 18 | Charts | Plotly or Matplotlib | Bar, line, donut |
| 19 | Data tables | Python, pandas | Tables for display or export |
| 20 | Downloadable files | openpyxl, ReportLab, python-docx, python-pptx | XLSX, PDF, DOCX, PPTX, TXT, MD |
| 21 | Rich responses | Python, Spring Boot, Next.js | Text, citations, chart data, tables, file references in one structured response |
| 22 | Voice input | faster-whisper or other local STT | Spoken question to text, then normal chat workflow |

**Important:** use SQL or Python to calculate numbers; let the LLM only explain results. Flow: question -> identify data -> retrieve authorized records -> calculate -> LLM explains -> text + tables + charts -> file if requested.

### Phase 4: Email and suggested actions
| Step | What | Tools | Method |
| --- | --- | --- | --- |
| 23 | Identify actions | LLM, Python | Propose follow-up actions |
| 24 | Draft emails | LLM, Python | Recipients, subject, body from authorized evidence |
| 25 | Review and approve | Spring Boot, Next.js | Show proposed action, require explicit user confirmation |
| 26 | Send emails | SMTP or authorized provider | Send approved messages, record outcome |
| 27 | Audit actions | Spring Boot, PostgreSQL | Who approved, what was sent, when, success |

Example rule: if attendance is below an **approved** threshold the chatbot may explain and suggest an intervention. It must not invent the threshold or send sensitive messages without authorization.

### Phase 5: Scheduled and event-triggered agents
A. Common infrastructure
| Step | What | Tools | Method |
| --- | --- | --- | --- |
| 28 | Agent configurations | Spring Boot, PostgreSQL, Next.js | Create, enable, disable, configure, manually run agents |
| 29 | Scheduled execution | Spring Scheduler or Quartz | Run at configured times; persistent scheduling where reliability requires |
| 30 | Event processing | Spring application events or a durable message broker | Trigger agents on business events |
| 31 | AI task executor | Python, FastAPI | Reuse retrieval, analysis, summarization, file generation |
| 32 | Track executions | PostgreSQL, Spring Boot | Status, timestamps, results, errors, retries |
| 33 | Email delivery | Existing email service | Send approved or explicitly pre-authorized automated reports |

B. The five agents (trigger and main work)
- Weekly Summary: every Friday; retrieve attendance and extra-hours data, calculate metrics, summarize, email administrators.
- Feedback Summary: weekly; retrieve instructor notes, summarize student progress and issues, generate a report.
- Alumni Profile: every six months; retrieve eligible alumni contacts, generate employment-update emails, send per configured workflow.
- At-Risk Agent: attendance or grade event; evaluate approved risk criteria, retrieve context, draft an administrator warning email.
- Alumni Job Alert: alumni career update event; detect the submitted update and notify administrators.

Execution flow: Trigger (schedule or business event) -> create agent run -> retrieve authorized data -> calculate/summarize -> generate report or action -> apply approval rules -> send/notify/save -> record execution result.
The scheduler and event listener decide **when** a task runs. Python and the LLM do the AI work. Spring Boot stays responsible for application permissions and business operations.

### Phase 6: Security, testing, deployment
| Step | What | Tools | Method |
| --- | --- | --- | --- |
| 34 | Access control | Spring Security, Keycloak | Authenticate and verify permissions before retrieving data or executing actions |
| 35 | Protect retrieval | Spring Boot, PostgreSQL, pgvector | Authorization filters on document and folder searches |
| 36 | Evaluate RAG | Python, test datasets | Retrieval accuracy, citation correctness, missing-answer behavior, prompt-injection resistance |
| 37 | Agent reliability | Automated tests, execution logs | Duplicate events, retries, failures, scheduling, approval requirements |
| 38 | Containerize | Docker, Docker Compose | Package services |
| 39 | Monitor and back up | Logging, monitoring, PostgreSQL and object-storage backups | Failures, resource usage, recovery |

## 3. Recommended implementation order
1. Basic AI: LLM -> Python API -> Spring Boot integration
2. Document RAG: upload -> extract -> chunk -> embed -> retrieve -> answer with citations
3. Chat management: history -> search -> rename -> delete -> continue
4. Folder chatbot: folders -> permissions -> isolated retrieval
5. AI outputs: data analysis -> charts -> tables -> file generation
6. AI actions: suggested actions -> email drafts -> approval -> sending
7. Automation: agent configuration -> scheduler -> event triggers -> agent execution
8. Production readiness: security -> evaluation -> monitoring -> deployment

## 4. Conflicts with the other project docs (do not resolve silently)
1. **Ollama vs vLLM.** This plan's phases name Ollama for the LLM and embeddings; its own flow diagram says Qwen on vLLM and bge-m3. The project overview and the service rules say vLLM + BGE-M3. Treat Ollama as a prototyping suggestion only.
2. **Who owns chat history.** This plan says Spring Boot stores sessions/messages (MyBatis, "Spring stores history"); the AI-service `CLAUDE.md` decision says the FastAPI service reads and writes `chat_sessions`/`chat_messages` itself. Confirm with the backend team.
3. **Who sets retrieval scope.** The diagram has Spring set the folder scope and enforce authorization; the service rules require the AI service to filter retrieval by ownership and permissions itself. Both can be true (defense in depth) but pick the primary.
4. **MyBatis vs Spring Data JPA.** This plan names MyBatis; the overview lists Spring Data JPA.
5. **Infrastructure not in the stack list:** MinIO (object storage), Redis (ingestion queue), Quartz (scheduler), keyword/full-text search and reranking (hybrid search), faster-whisper (STT), Plotly/Matplotlib, ReportLab. Confirm before adding dependencies.
6. **Model:** diagram says Qwen; the verified dev server runs `google/gemma-4-E2B-it`.
7. **Alumni Profile agent:** this plan says "email only, no AI needed" in the diagram but "generate employment-update emails" in the phase table.
8. **Chat sessions:** "10 most recently updated sessions" here vs "recent 10 sessions" and a hard limit of 10 (user must delete one) in the workflow doc.