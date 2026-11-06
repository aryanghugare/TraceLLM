import json

from fastapi.testclient import TestClient

from app.llm.providers import Usage
from app.main import create_app
from tests.conftest import ScriptedProvider


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in filter(None, text.split("\n\n")):
        event, data = "message", None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        events.append((event, data))
    return events


def test_chat_streams_deltas_and_enqueues_a_trace(client, queue, db, provider):
    res = client.post("/api/chat", json={"sessionId": "s1", "message": "hi", "title": "First chat"})

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert parse_sse(res.text) == [
        ("message", {"delta": "Hello"}),
        ("message", {"delta": " world"}),
        ("message", {"done": True}),
    ]

    # user message stored synchronously; session created with title
    user_logs = list(db["logs"].sync.find({"role": "user"}))
    assert [log["content"] for log in user_logs] == ["hi"]
    assert db["sessions"].sync.find_one({"sessionId": "s1"})["title"] == "First chat"

    # assistant output goes through the queue, not straight to the DB
    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    assert job["sessionId"] == "s1" and job["content"] == "Hello world"
    meta = job["metadata"]
    assert meta["provider"] == "openai" and meta["model"] == "gpt-4o-mini" and meta["status"] == "success"
    assert meta["tokenUsage"] == {"prompt": 11, "completion": 2, "total": 13}
    assert meta["latency"]["totalMs"] >= 0 and meta["latency"]["ttfbMs"] >= 0


def test_chat_sends_recent_history_to_the_model(client, provider):
    client.post("/api/chat", json={"sessionId": "s1", "message": "first"})
    client.post("/api/chat", json={"sessionId": "s1", "message": "second"})

    second_call = provider.calls[1]["messages"]
    assert second_call == [{"role": "user", "content": "first"}, {"role": "user", "content": "second"}]


def test_chat_validation_errors_match_the_node_api(client):
    assert client.post("/api/chat", json={"message": "hi"}).json() == {"error": "sessionId and message are required"}
    assert client.post("/api/chat", json={"sessionId": "s1", "message": "   "}).status_code == 400

    res = client.post("/api/chat", json={"sessionId": "s1", "message": "hi", "provider": "gemini"})
    assert res.status_code == 400 and res.json()["error"] == "Missing API key for provider"

    res = client.post("/api/chat", json={"sessionId": "s1", "message": "hi", "provider": "mistral"})
    assert res.status_code == 400


def test_provider_failure_is_reported_in_stream_and_traced_as_error(store, queue):
    failing = ScriptedProvider(chunks=("partial",), usage=None, error=RuntimeError("rate limited"))
    with TestClient(create_app(store=store, queue=queue, provider_factory=lambda n, k: failing)) as c:
        res = c.post("/api/chat", json={"sessionId": "s1", "message": "hi"})

    events = parse_sse(res.text)
    assert events[0] == ("message", {"delta": "partial"})
    assert events[-1] == ("error", {"message": "rate limited"})
    assert queue.jobs[0]["metadata"]["status"] == "error"
    assert queue.jobs[0]["content"] == "partial"
    assert "tokenUsage" not in queue.jobs[0]["metadata"]


def test_stream_completes_even_if_the_queue_is_down(client, queue):
    queue.fail = True
    res = client.post("/api/chat", json={"sessionId": "s1", "message": "hi"})
    assert parse_sse(res.text)[-1] == ("message", {"done": True})
    assert "tracellm_queue_enqueue_failures_total" in client.get("/metrics").text


def test_pii_is_redacted_before_logging(store, queue):
    leaky = ScriptedProvider(chunks=("Mail me at jane@example.com",), usage=Usage(1, 1))
    with TestClient(create_app(store=store, queue=queue, provider_factory=lambda n, k: leaky)) as c:
        res = c.post("/api/chat", json={"sessionId": "s1", "message": "hi"})

    assert "jane@example.com" in res.text  # the user still sees the real answer
    assert queue.jobs[0]["content"] == "Mail me at [REDACTED]"  # the stored trace does not


def test_sessions_endpoints(client):
    client.post("/api/chat", json={"sessionId": "s1", "message": "hi", "title": "One"})
    client.post("/api/chat", json={"sessionId": "s2", "message": "yo"})

    sessions = client.get("/api/sessions").json()["sessions"]
    assert [s["sessionId"] for s in sessions] == ["s2", "s1"]  # most recently updated first
    assert isinstance(sessions[0]["_id"], str) and sessions[0]["createdAt"].endswith("Z")

    detail = client.get("/api/sessions/s1").json()
    assert detail["session"]["title"] == "One"
    assert [m["content"] for m in detail["messages"]] == ["hi"]

    assert client.get("/api/sessions/nope").json() == {"session": None, "messages": []}
