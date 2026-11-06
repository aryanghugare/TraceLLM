"""Tools the agent can call. Each tool = a name, a description the LLM reads, a Pydantic
model for its arguments (which doubles as the JSON Schema sent to the LLM), and a handler.

All tools are read-only queries over the trace data; the agent cannot modify anything.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from app import analytics, metrics
from app.store import Store


class LatencyArgs(BaseModel):
    hours: int = Field(24, ge=1, le=168, description="Look-back window in hours (1-168).")


class ThroughputArgs(BaseModel):
    days: int = Field(7, ge=1, le=30, description="Look-back window in days (1-30).")


class NoArgs(BaseModel):
    pass


class RecentErrorsArgs(BaseModel):
    limit: int = Field(5, ge=1, le=20, description="How many recent failed calls to return (1-20).")


async def _latency(store: Store, args: LatencyArgs):
    return {"hours": args.hours, "providers": await analytics.latency_by_provider(store, args.hours)}


async def _throughput(store: Store, args: ThroughputArgs):
    series = await analytics.token_throughput(store, args.days)
    peak = max(series, key=lambda r: r["totalTokens"], default=None)
    return {
        "days": args.days,
        "totalTokens": sum(r["totalTokens"] for r in series),
        "peakHour": peak,
        "hourly": series[-48:],  # keep the tool result small enough for the model's context
    }


async def _errors(store: Store, args: NoArgs):
    return {"models": await analytics.errors_by_model(store)}


async def _recent_errors(store: Store, args: RecentErrorsArgs):
    return {"errors": await analytics.recent_errors(store, args.limit)}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Store, BaseModel], Awaitable[dict]]

    @property
    def json_schema(self) -> dict:
        return self.args_model.model_json_schema()


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("get_latency_by_provider",
             "Average time-to-first-token and total latency (ms) per LLM provider over a recent window.",
             LatencyArgs, _latency),
        Tool("get_token_throughput",
             "Token usage over a recent window: total, the peak hour, and hourly totals (UTC).",
             ThroughputArgs, _throughput),
        Tool("get_error_counts_by_model",
             "Success and error call counts for each model, all time.",
             NoArgs, _errors),
        Tool("get_recent_errors",
             "The most recent failed LLM calls with provider, model, latency and an output preview.",
             RecentErrorsArgs, _recent_errors),
    ]
}


@dataclass
class ToolOutcome:
    content: str  # JSON string handed back to the model
    is_error: bool


async def execute_tool(name: str, arguments: dict, store: Store) -> ToolOutcome:
    """Validate the model's arguments and run the tool. Errors go back to the model as text,
    so it can correct itself instead of the whole run failing."""
    tool = TOOLS.get(name)
    if tool is None:
        metrics.AGENT_TOOL_CALLS.labels("unknown", "error").inc()
        return ToolOutcome(json.dumps({"error": f"Unknown tool '{name}'. Available: {sorted(TOOLS)}"}), True)
    try:
        args = tool.args_model.model_validate(arguments)
    except ValidationError as exc:
        metrics.AGENT_TOOL_CALLS.labels(name, "invalid_args").inc()
        return ToolOutcome(json.dumps({"error": "Invalid arguments", "details": exc.errors(include_url=False)}), True)
    try:
        result = await tool.handler(store, args)
    except Exception as exc:
        metrics.AGENT_TOOL_CALLS.labels(name, "error").inc()
        return ToolOutcome(json.dumps({"error": f"Tool failed: {exc}"}), True)
    metrics.AGENT_TOOL_CALLS.labels(name, "ok").inc()
    return ToolOutcome(json.dumps(result, default=str), False)
