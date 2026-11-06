"""Provider adapters for the agent loop.

The runner keeps one provider-neutral transcript (user text, assistant turns with tool calls,
tool results). Each adapter converts that transcript to its SDK's native format on every step
and converts the reply back into an `AgentTurn`. Adding a provider = writing one adapter.
"""

import json
from dataclasses import dataclass, field
from typing import Protocol

from app.llm.providers import Usage


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class AgentTurn:
    """One assistant reply: optional text plus zero or more tool calls."""

    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class UserMessage:
    text: str


TranscriptItem = UserMessage | AgentTurn | list[ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema


class AgentModel(Protocol):
    provider: str
    model: str

    async def next_turn(self, system: str, transcript: list[TranscriptItem], tools: list[ToolSpec]) -> AgentTurn: ...


def _parse_arguments(raw: str | None) -> dict:
    """LLMs occasionally emit malformed JSON; surface that to the tool layer as an argument error."""
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {"__invalid__": raw}
    except json.JSONDecodeError:
        return {"__invalid__": raw}


class OpenAIAgentModel:
    provider = "openai"

    def __init__(self, api_key: str, model: str):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self.model = model

    @staticmethod
    def _to_messages(system: str, transcript: list[TranscriptItem]) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": system}]
        for item in transcript:
            if isinstance(item, UserMessage):
                messages.append({"role": "user", "content": item.text})
            elif isinstance(item, AgentTurn):
                msg: dict = {"role": "assistant", "content": item.text}
                if item.tool_calls:
                    msg["tool_calls"] = [
                        {"id": c.id, "type": "function",
                         "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                        for c in item.tool_calls
                    ]
                messages.append(msg)
            else:
                messages.extend({"role": "tool", "tool_call_id": r.call_id, "content": r.content} for r in item)
        return messages

    async def next_turn(self, system, transcript, tools) -> AgentTurn:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=self._to_messages(system, transcript),
            tools=[{"type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                   for t in tools],
        )
        msg = response.choices[0].message
        calls = [ToolCall(c.id, c.function.name, _parse_arguments(c.function.arguments))
                 for c in (msg.tool_calls or [])]
        usage = Usage(response.usage.prompt_tokens, response.usage.completion_tokens) if response.usage else None
        return AgentTurn(text=msg.content, tool_calls=calls, usage=usage)


class AnthropicAgentModel:
    provider = "anthropic"

    def __init__(self, api_key: str, model: str):
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self.model = model

    @staticmethod
    def _to_messages(transcript: list[TranscriptItem]) -> list[dict]:
        messages: list[dict] = []
        for item in transcript:
            if isinstance(item, UserMessage):
                messages.append({"role": "user", "content": item.text})
            elif isinstance(item, AgentTurn):
                blocks: list[dict] = [{"type": "text", "text": item.text}] if item.text else []
                blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                           for c in item.tool_calls]
                messages.append({"role": "assistant", "content": blocks})
            else:  # all tool results of one turn go back in a single user message
                messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
                    for r in item
                ]})
        return messages

    async def next_turn(self, system, transcript, tools) -> AgentTurn:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=self._to_messages(transcript),
            tools=[{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools],
        )
        text = "".join(b.text for b in response.content if b.type == "text") or None
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"]
        usage = Usage(response.usage.input_tokens, response.usage.output_tokens)
        return AgentTurn(text=text, tool_calls=calls, usage=usage)


def default_agent_model_factory(provider: str, api_key: str, model: str) -> AgentModel:
    if provider == "openai":
        return OpenAIAgentModel(api_key, model)
    if provider == "anthropic":
        return AnthropicAgentModel(api_key, model)
    raise ValueError(f"Agent does not support provider: {provider}")
