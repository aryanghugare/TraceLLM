import json
from datetime import datetime, timezone

from app.agent.models import AgentTurn, ToolCall, ToolResult
from app.llm.providers import Usage
from tests.conftest import ScriptedAgentModel


def seed_error(db):
    db["logs"].sync.insert_one({
        "sessionId": "s9", "role": "assistant", "content": "partial answer",
        "createdAt": datetime.now(timezone.utc),
        "metadata": {"provider": "openai", "model": "gpt-4o-mini", "status": "error",
                     "latency": {"totalMs": 4200.0}},
    })


def test_agent_calls_tools_then_answers_from_their_data(client, db, queue, agent_box):
    seed_error(db)
    model = ScriptedAgentModel([
        AgentTurn(None, [ToolCall("c1", "get_error_counts_by_model", {}),
                         ToolCall("c2", "get_recent_errors", {"limit": 3})], Usage(50, 10)),
        AgentTurn("gpt-4o-mini had 1 error; the last one took 4200 ms.", [], Usage(80, 15)),
    ])
    agent_box["model"] = model

    res = client.post("/api/agent/ask", json={"question": "Which model is failing?"})

    assert res.status_code == 200
    body = res.json()
    assert body["stoppedReason"] == "answered"
    assert body["answer"].startswith("gpt-4o-mini had 1 error")
    assert [s["tool"] for s in body["steps"]] == ["get_error_counts_by_model", "get_recent_errors"]
    errors = json.loads(body["steps"][0]["result"])["models"]
    assert errors == [{"model": "gpt-4o-mini", "success": 0, "error": 1}]

    # the second model call saw both tool results
    tool_results = model.seen_transcripts[1][-1]
    assert [r.call_id for r in tool_results] == ["c1", "c2"]
    assert all(isinstance(r, ToolResult) for r in tool_results)

    # the agent's own LLM calls were traced into TraceLLM
    agent_traces = [j for j in queue.jobs if j["sessionId"].startswith("agent:")]
    assert len(agent_traces) == 2
    assert agent_traces[1]["metadata"]["tokenUsage"] == {"prompt": 80, "completion": 15, "total": 95}


def test_bad_tool_arguments_go_back_to_the_model_instead_of_crashing(client, agent_box):
    agent_box["model"] = ScriptedAgentModel([
        AgentTurn(None, [ToolCall("c1", "get_latency_by_provider", {"hours": 9999})]),
        AgentTurn(None, [ToolCall("c2", "drop_database", {})]),
        AgentTurn("Sorry, I could not get that data.", []),
    ])

    body = client.post("/api/agent/ask", json={"question": "latency last year?"}).json()

    assert [s["isError"] for s in body["steps"]] == [True, True]
    assert "Invalid arguments" in body["steps"][0]["result"]
    assert "Unknown tool" in body["steps"][1]["result"]
    assert body["stoppedReason"] == "answered"


def test_agent_stops_at_the_step_limit(client, agent_box):
    loop = [AgentTurn(None, [ToolCall(f"c{i}", "get_error_counts_by_model", {})]) for i in range(10)]
    agent_box["model"] = ScriptedAgentModel(loop)

    body = client.post("/api/agent/ask", json={"question": "keep going", "maxSteps": 2}).json()

    assert body["stoppedReason"] == "max_steps"
    assert len(body["steps"]) == 2


def test_agent_llm_failure_returns_502_and_is_traced(client, agent_box, queue):
    agent_box["model"] = ScriptedAgentModel([])  # raises on first call
    res = client.post("/api/agent/ask", json={"question": "anything?"})
    assert res.status_code == 502
    assert queue.jobs[-1]["metadata"]["status"] == "error"


def test_tool_schemas_are_json_schema_objects():
    from app.agent.runner import TOOL_SPECS

    assert {t.name for t in TOOL_SPECS} == {
        "get_latency_by_provider", "get_token_throughput", "get_error_counts_by_model", "get_recent_errors"
    }
    for spec in TOOL_SPECS:
        assert spec.parameters["type"] == "object"
