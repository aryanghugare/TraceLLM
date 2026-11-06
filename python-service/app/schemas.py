"""Pydantic models: request bodies and the inference-log payload that goes through the queue.

Python code uses snake_case; MongoDB documents and the JSON API use camelCase (to stay
compatible with the Node service and the React UI). `alias_generator=to_camel` bridges the
two: `ttfb_ms` is read from / written as `ttfbMs`.
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Provider = Literal["openai", "gemini", "anthropic"]
PROVIDERS: tuple[str, ...] = ("openai", "gemini", "anthropic")


class CamelModel(BaseModel):
    """Base model: camelCase on the wire, snake_case in Python, unknown fields rejected."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Latency(CamelModel):
    ttfb_ms: float | None = Field(default=None, ge=0)  # None if the call failed before any token
    total_ms: float = Field(ge=0)


class TokenUsage(CamelModel):
    prompt: int = Field(ge=0)
    completion: int = Field(ge=0)
    total: int = Field(ge=0)


class InferenceMetadata(CamelModel):
    provider: Provider
    model: str = Field(min_length=1)
    status: Literal["success", "error"]
    latency: Latency
    token_usage: TokenUsage | None = None  # providers do not always report usage (e.g. on errors)


class InferenceLog(CamelModel):
    """The job payload the gateway enqueues and the worker validates before writing to MongoDB."""

    session_id: str = Field(min_length=1)
    content: str
    metadata: InferenceMetadata

    def to_document(self, now: datetime | None = None) -> dict:
        """Shape it like the Node/Mongoose `Log` document so both services share one collection."""
        now = now or datetime.now(timezone.utc)
        return {
            "sessionId": self.session_id,
            "role": "assistant",
            "content": self.content,
            "metadata": self.metadata.model_dump(by_alias=True, exclude_none=True),
            "createdAt": now,
            "updatedAt": now,
        }


class ChatRequest(BaseModel):
    """Body of POST /api/chat. Loose on purpose: the route returns the same 400 messages as Node."""

    model_config = ConfigDict(extra="ignore")

    sessionId: str | None = None
    message: str | None = None
    title: str | None = None
    provider: str | None = None
    apiKey: str | None = None
    model: str | None = None
    temperature: float | None = None
    maxTokens: int | None = Field(default=None, gt=0)


class AgentRequest(BaseModel):
    """Body of POST /api/agent/ask."""

    question: str = Field(min_length=3, max_length=2000)
    provider: Literal["openai", "anthropic"] = "openai"
    apiKey: str | None = None
    model: str | None = None
    maxSteps: int | None = Field(default=None, ge=1, le=10)
