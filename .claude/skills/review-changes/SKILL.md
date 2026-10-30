---
name: review-changes
description: Review the current uncommitted and staged changes against this project's rules before committing or opening a PR.
---

## Current changes

!`git status --short`

!`git diff HEAD`

Review the changes above for:

- bugs and regressions, especially in streaming and error handling
- unnecessary or unrelated changes (the project prefers minimal diffs)
- missing or weak tests (does a streaming change have a timing test?)
- violations of the rules in CLAUDE.md
- changes to the chat contract (request body, SSE event names and order, status codes) that other teams depend on
- secrets, API keys, internal URLs or scratch files (`body.json`, `diag_llm.py`, `stream_*.py`, `.env`) being committed; untracked files in `git status` that should or should not be added
- sensitive student, alumni or institutional data in logs or error responses
- missing authorization filtering anywhere data is retrieved (ownership and permissions, `deleted_at IS NULL`, `processing_status = completed`)
- database changes: any DDL, `create_all`, migration, or access to tables beyond those CLAUDE.md lists (the backend team owns the schema)
- private instructor evaluations being indexed or exposed
- features that the reference docs describe but the task did not ask for (session limit, voice, charts, email sending)
- edits to `docs/*.md` or `CLAUDE.md` that contradict each other or the code
- fabricated or unverifiable citations; claims of success that were not tested

Return, in this order: Critical, Major, Minor, Verification (what was and was not tested), Recommendation (commit, fix first, or split). Be specific: file, line and why.
