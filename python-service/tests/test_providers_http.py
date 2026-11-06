"""Exercise the real OpenAI and Anthropic SDK adapters against faked HTTP responses, so the
stream parsing (text deltas, usage) is verified without network access or API keys."""

import json

import httpx

from app.llm.providers import AnthropicProvider, OpenAIProvider, TextDelta, Usage


def sse_body(events: list[tuple[str | None, dict | str]]) -> bytes:
    out = []
    for name, data in events:
        payload = data if isinstance(data, str) else json.dumps(data)
        out.append((f"event: {name}\n" if name else "") + f"data: {payload}\n\n")
    return "".join(out).encode()


def http_client(body: bytes, seen: list, lib=httpx):
    """`lib` is the HTTP package the SDK is built on (anthropic 2.x moved to httpx2)."""

    def handler(request):
        seen.append(json.loads(request.content))
        return lib.Response(200, content=body, headers={"content-type": "text/event-stream"})

    return lib.AsyncClient(transport=lib.MockTransport(handler))


async def collect(provider, **kwargs):
    return [e async for e in provider.stream(**kwargs)]


async def test_openai_stream_parsing():
    chunk = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m"}
    body = sse_body([
        (None, {**chunk, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hi"}}]}),
        (None, {**chunk, "choices": [{"index": 0, "delta": {"content": " there"}, "finish_reason": "stop"}]}),
        (None, {**chunk, "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}}),
        (None, "[DONE]"),
    ])
    seen: list = []
    provider = OpenAIProvider("k")
    provider._client = provider._client.with_options(http_client=http_client(body, seen))

    events = await collect(provider, messages=[{"role": "user", "content": "q"}], model="m",
                           temperature=0.2, max_tokens=50)

    assert events == [TextDelta("Hi"), TextDelta(" there"), Usage(7, 2)]
    assert seen[0]["stream"] is True and seen[0]["stream_options"] == {"include_usage": True}
    assert seen[0]["max_completion_tokens"] == 50 and seen[0]["temperature"] == 0.2


async def test_anthropic_stream_parsing():
    body = sse_body([
        ("message_start", {"type": "message_start", "message": {
            "id": "m1", "type": "message", "role": "assistant", "model": "c", "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": "Hello"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 4}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    seen: list = []
    provider = AnthropicProvider("k")
    try:
        import httpx2 as lib
    except ImportError:  # older anthropic SDKs use plain httpx
        lib = httpx
    provider._client = provider._client.with_options(http_client=http_client(body, seen, lib))

    events = await collect(provider, messages=[{"role": "system", "content": "be brief"},
                                               {"role": "user", "content": "q"}],
                           model="c", temperature=None, max_tokens=None)

    assert events == [TextDelta("Hello"), Usage(12, 4)]
    assert seen[0]["system"] == "be brief" and seen[0]["max_tokens"] == 1024
    assert seen[0]["messages"] == [{"role": "user", "content": "q"}]
