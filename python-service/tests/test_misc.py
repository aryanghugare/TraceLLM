import json

from app.agent.models import (
    AgentTurn,
    AnthropicAgentModel,
    OpenAIAgentModel,
    ToolCall,
    ToolResult,
    UserMessage,
    _parse_arguments,
)
from app.llm.providers import split_system
from app.redaction import redact_pii

TRANSCRIPT = [
    UserMessage("why slow?"),
    AgentTurn("Checking.", [ToolCall("t1", "get_latency_by_provider", {"hours": 6})]),
    [ToolResult("t1", "get_latency_by_provider", '{"providers": []}')],
]


def test_openai_transcript_format():
    msgs = OpenAIAgentModel._to_messages("SYS", TRANSCRIPT)
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1] == {"role": "user", "content": "why slow?"}
    call = msgs[2]["tool_calls"][0]
    assert call["id"] == "t1" and call["type"] == "function"
    assert json.loads(call["function"]["arguments"]) == {"hours": 6}
    assert msgs[3] == {"role": "tool", "tool_call_id": "t1", "content": '{"providers": []}'}


def test_anthropic_transcript_format():
    msgs = AnthropicAgentModel._to_messages(TRANSCRIPT)
    assert msgs[0] == {"role": "user", "content": "why slow?"}
    assert msgs[1]["content"] == [
        {"type": "text", "text": "Checking."},
        {"type": "tool_use", "id": "t1", "name": "get_latency_by_provider", "input": {"hours": 6}},
    ]
    assert msgs[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": '{"providers": []}', "is_error": False},
    ]}


def test_malformed_tool_arguments_are_flagged_not_crashed():
    assert _parse_arguments('{"hours": 3}') == {"hours": 3}
    assert _parse_arguments("{not json") == {"__invalid__": "{not json"}
    assert _parse_arguments(None) == {}


def test_split_system():
    system, rest = split_system([{"role": "system", "content": "a"}, {"role": "user", "content": "b"}])
    assert system == "a" and rest == [{"role": "user", "content": "b"}]
    assert split_system([{"role": "user", "content": "b"}])[0] is None


def test_redaction():
    out = redact_pii("mail a.b@x.io, call +1 415-555-0100, card 4111 1111 1111 1111")
    assert "a.b@x.io" not in out and "555-0100" not in out and "4111" not in out
    assert out.count("[REDACTED]") == 3
    assert redact_pii("") == ""


def test_health_ready_and_metrics(client, queue):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200

    client.post("/api/chat", json={"sessionId": "s1", "message": "hi"})
    text = client.get("/metrics").text
    assert 'tracellm_llm_requests_total{model="gpt-4o-mini",provider="openai",status="success"}' in text
    assert "tracellm_llm_ttfb_seconds_bucket" in text
    assert 'tracellm_http_requests_total{method="POST",route="/api/chat",status="200"}' in text

    queue.fail = True
    ready = client.get("/ready")
    assert ready.status_code == 503 and ready.json()["checks"]["redis"].startswith("error")
