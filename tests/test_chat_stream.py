import json
import time
import uuid

import httpx

from tests.conftest import GAP_SECONDS, WORDS, free_port, read_messages, read_sessions
from tests.helpers import ISSUER, OTHER_PRIVATE_KEY, make_token

VALID = {"message": "Hello"}
KHMER = "សួស្តី តើអ្នកសុខសប្បាយទេ?"


def url_of(app) -> str:
    return f"{app.url}/api/v1/chat/stream"


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def post(app, user, body=None, **kwargs):
    # `is None`, not `or`: an empty dict {} is a real (invalid) body the tests want to send.
    payload = VALID if body is None else body
    return httpx.post(url_of(app), json=payload, headers=user.headers, timeout=15, **kwargs)


def last_llm_request(fake_vllm) -> dict:
    return fake_vllm.app.state.last_body


# --------------------------------------------------------------------------- basics


def test_health(make_app_server):
    app = make_app_server()
    assert httpx.get(f"{app.url}/health").json() == {"status": "ok"}


def test_chat_returns_503_when_not_configured(make_app_server, users):
    app = make_app_server(configured=False)
    assert httpx.get(f"{app.url}/health").status_code == 200  # still starts
    assert post(app, users.alice).status_code == 503  # and never skips authentication


# --------------------------------------------------------------------------- authentication


def test_missing_token_is_401(make_app_server):
    app = make_app_server()
    r = httpx.post(url_of(app), json=VALID, timeout=10)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_bad_tokens_are_401(make_app_server, users):
    app = make_app_server()
    sub = users.alice.keycloak_id
    bad = {
        "wrong key": make_token(sub, key=OTHER_PRIVATE_KEY),
        "expired": make_token(sub, expires_in=-3600),
        "wrong issuer": make_token(sub, issuer="https://evil.test/realms/hrd"),
        "garbage": "not-a-jwt",
    }
    for name, token in bad.items():
        r = httpx.post(
            url_of(app), json=VALID, headers={"Authorization": f"Bearer {token}"}, timeout=10
        )
        assert r.status_code == 401, name


def test_token_with_non_uuid_subject_is_401(make_app_server):
    app = make_app_server()
    token = make_token("not-a-uuid")
    r = httpx.post(url_of(app), json=VALID, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 401


def test_inactive_or_unknown_account_is_403(make_app_server, users):
    app = make_app_server()
    assert post(app, users.carol).status_code == 403  # inactive
    stranger = {"Authorization": f"Bearer {make_token(uuid.uuid4())}"}
    r = httpx.post(url_of(app), json=VALID, headers=stranger, timeout=10)
    assert r.status_code == 403  # valid token, not in the users table


def test_role_comes_from_the_roles_table(make_app_server, users, db_url):
    """Both ERD roles may chat. An active account with no role, or with a role this service does
    not know, is refused with the same 403 as an inactive account (nothing is revealed)."""
    app = make_app_server()
    assert post(app, users.alice).status_code == 200  # admin
    assert post(app, users.bob).status_code == 200  # instructor
    for refused in (users.dave, users.erin):  # no role; role "student"
        r = post(app, refused)
        assert r.status_code == 403
        assert r.json()["detail"] == "This account may not use the AI service"
    assert {s.user_id for s in read_sessions(db_url)} == {users.alice.user_id, users.bob.user_id}


def test_validation_rejects_bad_requests(make_app_server, users):
    app = make_app_server()
    for body in ({}, {"message": ""}, {"message": "   "}, {"message": "hi", "session_id": "nope"}):
        assert post(app, users.alice, body).status_code == 422, body
    assert read_sessions(app.app.state.settings.database_url.get_secret_value()) == []


# --------------------------------------------------------------------------- streaming


def test_streams_tokens_incrementally(make_app_server, users):
    """Tokens must arrive spread out over time, not all at once at the end."""
    app = make_app_server()
    post(app, users.alice)  # warm-up: absorbs one-time connection/client setup cost

    arrivals: list[float] = []
    texts: list[str] = []
    start = time.monotonic()
    with httpx.stream("POST", url_of(app), json=VALID, headers=users.alice.headers, timeout=15) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: ") and "text" in line:
                arrivals.append(time.monotonic() - start)
                texts.append(json.loads(line[6:])["text"])

    print("arrival times:", [round(a, 2) for a in arrivals])
    assert texts == WORDS
    total_fake_time = GAP_SECONDS * (len(WORDS) - 1)
    assert arrivals[0] < arrivals[-1] - total_fake_time * 0.7, "first token waited for the whole reply"
    gaps = [b - a for a, b in zip(arrivals, arrivals[1:])]
    assert all(g > GAP_SECONDS * 0.5 for g in gaps), f"tokens bunched together: gaps={gaps}"


def test_event_sequence_and_history_is_saved(make_app_server, users, db_url):
    app = make_app_server()
    r = post(app, users.alice)
    assert r.status_code == 200

    events = parse_sse(r.text)
    assert [e for e, _ in events] == ["session"] + ["token"] * len(WORDS) + ["done"]
    session_id = events[0][1]["session_id"]
    answer = "".join(d["text"] for e, d in events if e == "token")
    assert answer == "".join(WORDS)

    sessions = read_sessions(db_url)
    assert len(sessions) == 1
    s = sessions[0]
    assert str(s.session_id) == session_id
    assert s.user_id == users.alice.user_id
    assert s.chat_type == "general"
    assert s.folder_id is None
    assert s.title == "Hello"

    messages = read_messages(db_url)
    assert [(m.sender, m.content) for m in messages] == [("user", "Hello"), ("ai", answer)]
    assert all(m.session_id == s.session_id and m.message_type == "text" for m in messages)


def test_continuing_a_session_sends_the_history_to_the_model(make_app_server, users, db_url, fake_vllm):
    app = make_app_server()
    first = parse_sse(post(app, users.alice, {"message": "first question"}).text)
    session_id = first[0][1]["session_id"]
    first_answer = "".join(d["text"] for e, d in first if e == "token")

    r = post(app, users.alice, {"message": "second question", "session_id": session_id})
    assert r.status_code == 200
    assert parse_sse(r.text)[0][1]["session_id"] == session_id  # same session, not a new one

    sent = last_llm_request(fake_vllm)["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert [m["content"] for m in sent[1:]] == ["first question", first_answer, "second question"]

    assert len(read_sessions(db_url)) == 1
    assert [m.sender for m in read_messages(db_url)] == ["user", "ai", "user", "ai"]


def test_khmer_is_stored_and_forwarded_intact(make_app_server, users, db_url, fake_vllm):
    app = make_app_server()
    assert post(app, users.alice, {"message": KHMER}).status_code == 200
    assert last_llm_request(fake_vllm)["messages"][-1]["content"] == KHMER
    assert read_messages(db_url)[0].content == KHMER


# --------------------------------------------------------------------------- sessions and ownership


def test_unknown_session_is_404(make_app_server, users, db_url):
    app = make_app_server()
    r = post(app, users.alice, {"message": "hi", "session_id": str(uuid.uuid4())})
    assert r.status_code == 404
    assert read_sessions(db_url) == []


def test_someone_elses_session_is_404_and_untouched(make_app_server, users, db_url):
    app = make_app_server()
    events = parse_sse(post(app, users.alice, {"message": "alice private question"}).text)
    session_id = events[0][1]["session_id"]
    before = len(read_messages(db_url))

    r = post(app, users.bob, {"message": "let me in", "session_id": session_id})
    assert r.status_code == 404  # same answer as "does not exist": no hint it exists
    assert "alice" not in r.text
    assert len(read_messages(db_url)) == before


# --------------------------------------------------------------------------- failures


def test_session_limit_refuses_new_chat_with_409_but_not_continuing(
    make_app_server, users, db_url, fake_vllm
):
    """At the per-user limit a new chat gets 409 before the model is called and nothing is saved;
    continuing an existing session still works, and the limit is per user."""
    app = make_app_server(max_sessions=2)
    first = parse_sse(post(app, users.alice, {"message": "one"}).text)[0][1]["session_id"]
    assert post(app, users.alice, {"message": "two"}).status_code == 200
    fake_vllm.app.state.last_body = None

    r = post(app, users.alice, {"message": "three"})
    assert r.status_code == 409
    assert r.json()["detail"] == "Your session has reached the limit"
    assert last_llm_request(fake_vllm) is None  # refused before the model was called
    assert len(read_sessions(db_url)) == 2
    assert len(read_messages(db_url)) == 4  # two questions, two answers, nothing from "three"

    r = post(app, users.alice, {"message": "follow-up", "session_id": first})
    assert r.status_code == 200
    assert post(app, users.bob, {"message": "bob is unaffected"}).status_code == 200


def test_llm_unreachable_is_503_and_nothing_is_saved(make_app_server, users, db_url):
    app = make_app_server(base_url=f"http://127.0.0.1:{free_port()}/v1")
    r = post(app, users.alice)
    assert r.status_code == 503
    assert "127.0.0.1" not in r.text  # no internal details leaked
    assert read_sessions(db_url) == [] and read_messages(db_url) == []


def test_llm_error_is_502_and_nothing_is_saved(make_app_server, users, db_url):
    app = make_app_server(model="fail")
    r = post(app, users.alice)
    assert r.status_code == 502
    assert "boom" not in r.text
    assert read_sessions(db_url) == [] and read_messages(db_url) == []


def test_empty_answer_is_502_and_nothing_is_saved(make_app_server, users, db_url):
    app = make_app_server(model="empty")
    assert post(app, users.alice).status_code == 502
    assert read_sessions(db_url) == [] and read_messages(db_url) == []


def test_midstream_failure_sends_error_and_saves_no_partial_answer(make_app_server, users, db_url):
    app = make_app_server(model="die-midstream")
    r = post(app, users.alice)
    assert r.status_code == 200  # streaming had already started

    events = parse_sse(r.text)
    assert events[0][0] == "session"
    assert [d["text"] for e, d in events if e == "token"] == WORDS[:2]
    assert events[-1][0] == "error"
    assert "done" not in [e for e, _ in events]  # a cut-off answer is never reported as done

    messages = read_messages(db_url)
    assert [m.sender for m in messages] == ["user"]  # the question is kept, the partial answer is not


def test_client_disconnect_stops_the_model(make_app_server, users, fake_vllm):
    """Closing the connection mid-answer must close our request to the model too."""
    fake_vllm.app.state.cancelled = False
    app = make_app_server()
    with httpx.stream("POST", url_of(app), json=VALID, headers=users.alice.headers, timeout=15) as r:
        for line in r.iter_lines():
            if line.startswith("data: ") and "text" in line:
                break  # got one token, now walk away (leaving the block closes the connection)

    deadline = time.time() + 5
    while time.time() < deadline and not fake_vllm.app.state.cancelled:
        time.sleep(0.1)
    assert fake_vllm.app.state.cancelled, "the model kept generating after the client left"