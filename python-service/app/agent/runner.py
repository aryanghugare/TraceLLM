"""The agent loop: ask the model, run the tools it requests, feed results back, repeat.

Guardrails:
  - a hard step limit (no infinite loops, bounded cost)
  - tool arguments are validated; bad calls return an error the model can recover from
  - tools are read-only
  - every model call is traced into TraceLLM itself (session id `agent:<run id>`)
"""

import time
import uuid
from dataclasses import dataclass, field

from app import metrics
from app.agent.models import AgentModel, AgentTurn, ToolResult, ToolSpec, TranscriptItem, UserMessage
from app.agent.tools import TOOLS, execute_tool
from app.llm.gateway import LLMGateway
from app.store import Store

SYSTEM_PROMPT = """You are the observability assistant for TraceLLM, a service that traces LLM calls.
Answer the user's question about latency, token usage and errors using ONLY data from your tools.
Call as many tools as you need, then give a short answer that quotes the actual numbers
(with units: ms, tokens). If the data is empty or does not answer the question, say so plainly.
Never invent numbers."""

TOOL_SPECS = [ToolSpec(t.name, t.description, t.json_schema) for t in TOOLS.values()]


@dataclass
class AgentResult:
    run_id: str
    answer: str
    stopped_reason: str  # "answered" | "max_steps"
    steps: list[dict] = field(default_factory=list)


async def run_agent(
    question: str, model: AgentModel, store: Store, gateway: LLMGateway, max_steps: int
) -> AgentResult:
    run_id = uuid.uuid4().hex[:12]
    transcript: list[TranscriptItem] = [UserMessage(question)]
    steps: list[dict] = []

    for _ in range(max_steps):
        turn = await _traced_turn(model, transcript, gateway, run_id)
        transcript.append(turn)

        if not turn.tool_calls:
            metrics.AGENT_RUNS.labels("answered").inc()
            return AgentResult(run_id, turn.text or "", "answered", steps)

        results: list[ToolResult] = []
        for call in turn.tool_calls:
            outcome = await execute_tool(call.name, call.arguments, store)
            results.append(ToolResult(call.id, call.name, outcome.content, outcome.is_error))
            steps.append({"tool": call.name, "arguments": call.arguments,
                          "isError": outcome.is_error, "result": outcome.content})
        transcript.append(results)

    metrics.AGENT_RUNS.labels("max_steps").inc()
    return AgentResult(
        run_id,
        f"Stopped after {max_steps} steps without a final answer. Try a narrower question.",
        "max_steps",
        steps,
    )


async def _traced_turn(model: AgentModel, transcript, gateway: LLMGateway, run_id: str) -> AgentTurn:
    started = time.perf_counter()
    try:
        turn = await model.next_turn(SYSTEM_PROMPT, transcript, TOOL_SPECS)
    except Exception:
        await gateway.trace(provider=model.provider, model=model.model, session_id=f"agent:{run_id}",
                            status="error", content="", total_s=time.perf_counter() - started,
                            ttfb_s=None, usage=None)
        metrics.AGENT_RUNS.labels("llm_error").inc()
        raise
    summary = turn.text or "tool calls: " + ", ".join(c.name for c in turn.tool_calls)
    await gateway.trace(provider=model.provider, model=model.model, session_id=f"agent:{run_id}",
                        status="success", content=summary, total_s=time.perf_counter() - started,
                        ttfb_s=None, usage=turn.usage)
    return turn
