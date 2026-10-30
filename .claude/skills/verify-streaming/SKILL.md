---
name: verify-streaming
description: Prove that chat tokens arrive incrementally (not buffered) for the fake test server and the real vLLM server. Use after changing the chat endpoint, LLM client or anything between the model and the client.
---

An HTTP 200 does not prove streaming. Measure when each token arrives. Target: $ARGUMENTS (default: both fake and real).

## 1. Fake server (automatic, no key needed)
Run `poetry run pytest tests/test_chat_stream.py::test_streams_tokens_incrementally -v -s`.
It prints `arrival times:` and fails unless tokens are spaced out. Expected: about 0.3 s between tokens.

## 2. Real server (needs the service running, `LLM_API_KEY` set in `.env`, and a Keycloak token; never read `.env`)
The endpoint requires `Authorization: Bearer <Keycloak JWT>` and a body of `{"message": "..."}` (see the chat contract in CLAUDE.md). Ask the user to:
1. start the service: `poetry run uvicorn app.main:app --port 8080`
2. put a valid access token for an active test user in an environment variable in their own shell (`$env:HRD_TEST_TOKEN="..."` in PowerShell). Never print, log, paste or commit the token, and never read `.env`.

Then run this script (create it as a scratch file such as `stream_check.py`, never commit it):

```python
import os
import time
import httpx

token = os.environ["HRD_TEST_TOKEN"]
prompt = "Write a detailed 400-word explanation of why monitoring student attendance matters in a training center."
body = {"message": prompt}
headers = {"Authorization": f"Bearer {token}"}
times = []
start = time.monotonic()
with httpx.stream("POST", "http://localhost:8080/api/v1/chat/stream", json=body, headers=headers, timeout=180) as r:
    print("status:", r.status_code)
    if r.status_code != 200:
        raise SystemExit("not streaming: fix the status first (401 token, 403 account, 404 session, 422 body, 502/503 model or config)")
    for line in r.iter_lines():
        if line.startswith("data: ") and "text" in line:
            times.append(time.monotonic() - start)
if not times:
    raise SystemExit("no token events received")
print("tokens:", len(times))
print(f"first token: {times[0]:.2f}s | last token: {times[-1]:.2f}s | spread: {times[-1]-times[0]:.2f}s")
for i in range(0, len(times), max(1, len(times) // 8)):
    print(f"  token #{i:4d} at {times[i]:6.2f}s")
```

## 3. Interpret
- Use a LONG reply. A short reply finishes in a fraction of a second and looks like a burst even when streaming works.
- Spread of several seconds with steadily growing timestamps: genuine streaming.
- Spread under about 0.3 s after a long wait: something is buffering. The endpoint test already proves our code passes tokens through, so suspect a proxy in front of the model server and report it to whoever hosts it.
- A constant delay before the first token (about 3.3 s was measured) is model server latency, not buffering.

Report the numbers you observed, not a verdict without them. Delete the scratch script afterwards and do not include the token in any output.
