from app.services.history import HistoryMessage, build_model_messages, sender_to_role

SYSTEM = "system prompt"


def roles(messages):
    return [m["role"] for m in messages]


def test_sender_to_role():
    assert sender_to_role("user") == "user"
    assert sender_to_role("ai") == "assistant"
    assert sender_to_role("something-else") is None


def test_new_conversation_is_system_plus_user():
    msgs = build_model_messages(SYSTEM, [], "hello", 1000)
    assert msgs == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "hello"},
    ]


def test_history_keeps_order_and_alternation():
    history = [
        HistoryMessage("user", "q1"),
        HistoryMessage("assistant", "a1"),
        HistoryMessage("user", "q2"),
        HistoryMessage("assistant", "a2"),
    ]
    msgs = build_model_messages(SYSTEM, history, "q3", 1000)
    assert roles(msgs) == ["system", "user", "assistant", "user", "assistant", "user"]
    assert [m["content"] for m in msgs[1:]] == ["q1", "a1", "q2", "a2", "q3"]


def test_unanswered_user_message_is_merged_with_the_new_one():
    """An interrupted answer leaves a user message with no reply; two user turns in a row are
    rejected by some chat templates, so they are merged into one."""
    history = [
        HistoryMessage("user", "q1"),
        HistoryMessage("assistant", "a1"),
        HistoryMessage("user", "q2 (never answered)"),
    ]
    msgs = build_model_messages(SYSTEM, history, "q3", 1000)
    assert roles(msgs) == ["system", "user", "assistant", "user"]
    assert msgs[-1]["content"] == "q2 (never answered)\n\nq3"


def test_leading_assistant_message_is_dropped():
    history = [HistoryMessage("assistant", "orphan"), HistoryMessage("user", "q1")]
    msgs = build_model_messages(SYSTEM, history, "q2", 1000)
    assert roles(msgs)[1] == "user"
    assert "orphan" not in [m["content"] for m in msgs]


def test_blank_history_messages_are_ignored():
    history = [HistoryMessage("user", "   "), HistoryMessage("assistant", "")]
    msgs = build_model_messages(SYSTEM, history, "hello", 1000)
    assert [m["content"] for m in msgs[1:]] == ["hello"]


def test_trimming_drops_oldest_first_and_keeps_the_new_message():
    history = [
        HistoryMessage("user", "a" * 100),
        HistoryMessage("assistant", "b" * 100),
        HistoryMessage("user", "c" * 100),
        HistoryMessage("assistant", "d" * 100),
    ]
    msgs = build_model_messages(SYSTEM, history, "new question", 250)
    contents = [m["content"] for m in msgs[1:]]
    assert contents[-1] == "new question"
    assert "a" * 100 not in contents  # oldest gone
    assert "d" * 100 in contents  # newest history kept
    assert sum(len(c) for c in contents) <= 250
    assert msgs[1]["role"] == "user"  # still starts with a user turn


def test_trimming_never_starts_with_an_assistant_turn():
    history = [
        HistoryMessage("user", "x" * 100),
        HistoryMessage("assistant", "y" * 100),
        HistoryMessage("user", "z" * 100),
    ]
    # Budget forces the first user turn out; the assistant turn that follows must go too.
    msgs = build_model_messages(SYSTEM, history, "q", 210)
    assert msgs[1]["role"] == "user"


def test_message_longer_than_budget_is_still_sent():
    msgs = build_model_messages(SYSTEM, [HistoryMessage("user", "q"), HistoryMessage("assistant", "a")], "n" * 500, 100)
    assert msgs[-1]["content"] == "n" * 500
    assert len(msgs) == 2  # system + the new message only


def test_khmer_text_is_preserved():
    text = "សួស្តី តើអ្នកសុខសប្បាយទេ?"
    msgs = build_model_messages(SYSTEM, [HistoryMessage("user", text)], "ok", 1000)
    assert text in msgs[1]["content"]
