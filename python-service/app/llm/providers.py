"""Streaming adapters for each LLM provider, behind one interface.

Every provider exposes `stream(...)`, an async generator yielding:
  - `TextDelta`: a chunk of generated text
  - `Usage`:     token counts, usually at the end of the stream
The gateway (gateway.py) measures latency and logging around this, so each adapter only
has to translate its SDK's event format.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol

Message = dict[str, str]  # {"role": "user" | "assistant" | "system", "content": "..."}


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Usage:
    prompt: int
    completion: int

    @property
    def total(self) -> int:
        return self.prompt + self.completion


StreamEvent = TextDelta | Usage


class ChatProvider(Protocol):
    def stream(
        self,
        messages: list[Message],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
    ) -> AsyncIterator[StreamEvent]: ...


def split_system(messages: list[Message]) -> tuple[str | None, list[Message]]:
    """Anthropic and Gemini take the system prompt separately from the conversation."""
    system = [m["content"] for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]
    return ("\n".join(system) or None), rest


class OpenAIProvider:
    def __init__(self, api_key: str):
        from openai import AsyncOpenAI  # imported lazily so unused SDKs cost nothing at startup

        self._client = AsyncOpenAI(api_key=api_key)

    async def stream(self, messages, model, temperature, max_tokens) -> AsyncIterator[StreamEvent]:
        kwargs: dict = {"stream_options": {"include_usage": True}}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_completion_tokens"] = max_tokens
        stream = await self._client.chat.completions.create(
            model=model, messages=messages, stream=True, **kwargs
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield TextDelta(chunk.choices[0].delta.content)
            if chunk.usage:  # sent in the final chunk because of include_usage
                yield Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)


class AnthropicProvider:
    def __init__(self, api_key: str):
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)

    async def stream(self, messages, model, temperature, max_tokens) -> AsyncIterator[StreamEvent]:
        # Note: the current Anthropic SDK no longer accepts `temperature`, so it is ignored here.
        system, conversation = split_system(messages)
        kwargs: dict = {"system": system} if system else {}
        stream = await self._client.messages.create(
            model=model, messages=conversation, max_tokens=max_tokens or 1024, stream=True, **kwargs
        )
        prompt_tokens = 0
        async for event in stream:
            if event.type == "message_start":
                prompt_tokens = event.message.usage.input_tokens  # input count arrives first
            elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                yield TextDelta(event.delta.text)
            elif event.type == "message_delta" and event.usage:
                yield Usage(prompt_tokens, event.usage.output_tokens)  # output count arrives last


class GeminiProvider:
    def __init__(self, api_key: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)

    async def stream(self, messages, model, temperature, max_tokens) -> AsyncIterator[StreamEvent]:
        from google.genai import types

        system, conversation = split_system(messages)
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part(text=m["content"])],
            )
            for m in conversation
        ]
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=temperature, max_output_tokens=max_tokens
        )
        usage = None
        async for chunk in await self._client.aio.models.generate_content_stream(
            model=model, contents=contents, config=config
        ):
            if chunk.text:
                yield TextDelta(chunk.text)
            if chunk.usage_metadata:
                usage = chunk.usage_metadata  # cumulative; keep the latest
        if usage:
            yield Usage(usage.prompt_token_count or 0, usage.candidates_token_count or 0)


ProviderFactory = Callable[[str, str], ChatProvider]


def default_provider_factory(provider: str, api_key: str) -> ChatProvider:
    match provider:
        case "openai":
            return OpenAIProvider(api_key)
        case "anthropic":
            return AnthropicProvider(api_key)
        case "gemini":
            return GeminiProvider(api_key)
        case _:
            raise ValueError(f"Unsupported provider: {provider}")
