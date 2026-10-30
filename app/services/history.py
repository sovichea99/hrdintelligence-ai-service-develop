"""Turn stored chat history into the message list sent to the model. Pure functions, no I/O.

Why this exists:
- Some chat templates (Gemma among them) reject two messages in a row from the same role. After an
  interrupted answer the history has a user message with no reply, so consecutive same-role
  messages are merged.
- The model has a fixed context window. Old messages are dropped (oldest first) to stay inside a
  character budget. The newest user message is always kept.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryMessage:
    role: str  # "user" | "assistant"
    content: str


def sender_to_role(sender: str) -> str | None:
    """Map the database `sender` value to a chat role. Unknown senders are skipped."""
    return {"user": "user", "ai": "assistant"}.get(sender)


def _merge_consecutive(turns: list[tuple[str, str]]) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    for role, content in turns:
        if merged and merged[-1][0] == role:
            merged[-1] = (role, f"{merged[-1][1]}\n\n{content}")
        else:
            merged.append((role, content))
    return merged


def _drop_leading_assistant(turns: list[tuple[str, str]]) -> list[tuple[str, str]]:
    while turns and turns[0][0] == "assistant":
        turns = turns[1:]
    return turns


def build_model_messages(
    system_prompt: str,
    history: Sequence[HistoryMessage],
    new_message: str,
    max_chars: int,
) -> list[dict[str, str]]:
    """System prompt + (trimmed) history + the new user message.

    `max_chars` limits the conversation part only (not the system prompt).
    """
    turns = [(m.role, m.content.strip()) for m in history if m.content and m.content.strip()]
    turns.append(("user", new_message.strip()))

    turns = _drop_leading_assistant(_merge_consecutive(turns))
    # The last turn is always the user's, so at least one turn always survives.
    while len(turns) > 1 and sum(len(content) for _, content in turns) > max_chars:
        turns = _drop_leading_assistant(turns[1:])

    return [{"role": "system", "content": system_prompt}] + [
        {"role": role, "content": content} for role, content in turns
    ]
