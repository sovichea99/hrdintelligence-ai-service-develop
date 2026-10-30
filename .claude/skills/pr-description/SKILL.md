---
name: pr-description
description: Write a pull request title and description for the current branch targeting develop, with honest Verified and Not yet verified sections.
---

## Branch changes

!`git branch --show-current`

!`git log develop..HEAD --oneline`

!`git diff develop...HEAD --stat`

Write a PR for the branch above, targeting `develop`. Extra context from the user: $ARGUMENTS

If the current branch is `main` or `develop`, stop and tell the user to create a feature branch first (`feature/wbs-7-x-short-name`, branched from `develop`). Pull requests go into `develop`; never suggest pushing directly to `main` or `develop`.

Title: `feat(scope): short summary (WBS 7.x)` (use fix, docs, test or chore when more accurate; leave out the WBS suffix for changes that belong to no WBS task, such as docs or tooling).

Description sections:
- **What**: bullet points of behavior added or changed
- **Verified**: only things actually run, with the real numbers (tests passed, timings, status codes)
- **Not yet verified**: anything untested, such as the real LLM server, auth, or client disconnects
- **Limitations**: known gaps and risks
- **Integration impact**: whether the chat contract (request body, SSE events, status codes) changed, which database tables or columns are newly read or written (the schema is owned by the backend team), any new environment variable names, and any reference docs (`docs/*.md`) or `CLAUDE.md` sections edited or found in conflict
- **How to run**: the exact commands (`poetry install`, `poetry run pytest -v`, and any `.env` variable names that changed; never values)

Do not claim a task is complete without evidence. Never include secrets or internal URLs. If scratch files (`body.json`, `diag_llm.py`, `stream_*.py`) or `.env` appear in the diff stat, warn the user.
