"""PreToolUse hook for Bash commands.

Claude Code sends the pending tool call as JSON on stdin. Exiting with code 2 blocks the
command and shows stderr to Claude; any other exit code lets it run.
Uses only the standard library.
"""

import json
import re
import sys

BLOCKED = [
    (r"\brm\s+-\w*[rR]\w*\s+(/|~|\$HOME|\*)(\s|$)", "recursive delete of root, home or everything"),
    (r"(?=.*Remove-Item)(?=.*-Recurse)(?=.*(^|\s)[A-Za-z]:\\?(\s|$))", "recursive delete of a whole drive"),
    (r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f(\s|$))", "force push"),
    (r"\bgit\s+clean\s+-\w*f", "git clean -f (deletes untracked files)"),
    (r"\bDROP\s+(DATABASE|TABLE|SCHEMA)\b", "dropping database objects"),
    (r"\bTRUNCATE\s+TABLE\b", "truncating a table"),
    # The backend team owns the shared hrd_db schema. This service only maps existing tables.
    (r"\b(CREATE|ALTER)\s+(TABLE|EXTENSION)\b", "creating or altering tables/extensions (the backend team owns the schema)"),
    (r"\balembic\b|\bcreate_all\s*\(", "schema migration or create_all (the backend team owns the schema)"),
    # main and develop are changed only through pull requests. Branch names such as
    # feature/develop-notes or docs/main-page are allowed.
    (r"\bgit\s+push\b[^\n;&|]*(?<![\w/.-])(main|develop)(?![\w/.-])", "pushing to main or develop (use a feature branch and a pull request)"),
    # Scratch files must never be committed (see CLAUDE.md, Git workflow).
    (r"\bgit\s+add\b[^\n;&|]*(body\.json|diag_llm\.py|stream_\w+\.py)", "staging a scratch file"),
    # The real LLM API key lives in .env. Reading, copying or staging it is blocked;
    # .env.example is fine.
    (r"\.env\b(?!\.example)", "touching .env (holds the real API key); use .env.example for names and placeholders"),
]


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0  # never break the session because of a malformed hook payload

    command = (data.get("tool_input") or {}).get("command", "")
    for pattern, reason in BLOCKED:
        if re.search(pattern, command, flags=re.IGNORECASE):
            print(f"Blocked by project hook: {reason}. Ask the user to run this themselves if it is really needed.", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
