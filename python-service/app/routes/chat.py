"""Chat and session endpoints. Same paths, payloads and SSE format as the Node API,
so the existing React UI works against this service unchanged."""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Settings, get_settings
from app.llm.gateway import LLMGateway
from app.schemas import PROVIDERS, ChatRequest
from app.store import Store, serialize

router = APIRouter()

HISTORY_LIMIT = 5  # previous messages sent back to the model as context


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_gateway(request: Request) -> LLMGateway:
    return request.app.state.gateway


def sse(data: dict, event: str | None = None) -> str:
    """Format one server-sent event."""
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {json.dumps(data)}\n\n"


@router.get("/api/sessions")
async def list_sessions(store: Store = Depends(get_store)):
    return {"sessions": [serialize(s) for s in await store.list_sessions()]}


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str, store: Store = Depends(get_store)):
    session = await store.get_session(session_id)
    messages = await store.session_messages(session_id)
    return {"session": serialize(session), "messages": [serialize(m) for m in messages]}


@router.post("/api/chat")
async def chat(
    body: ChatRequest,
    store: Store = Depends(get_store),
    gateway: LLMGateway = Depends(get_gateway),
    settings: Settings = Depends(get_settings),
):
    message = (body.message or "").strip()
    if not body.sessionId or not message:
        return JSONResponse({"error": "sessionId and message are required"}, status_code=400)

    provider = (body.provider or settings.llm_provider).lower()
    if provider not in PROVIDERS:
        return JSONResponse({"error": f"provider must be one of {', '.join(PROVIDERS)}"}, status_code=400)

    api_key = body.apiKey or settings.api_key_for(provider)
    if not api_key:
        return JSONResponse({"error": "Missing API key for provider", "provider": provider}, status_code=400)

    model = body.model or settings.default_model_for(provider)
    session_id = body.sessionId

    await store.upsert_session(session_id, (body.title or "").strip() or None)
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in await store.recent_messages(session_id, HISTORY_LIMIT)
    ]
    await store.insert_log(_user_log(session_id, message))

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk in gateway.stream_chat(
                provider=provider,
                api_key=api_key,
                model=model,
                messages=[*history, {"role": "user", "content": message}],
                session_id=session_id,
                temperature=body.temperature,
                max_tokens=body.maxTokens,
            ):
                yield sse({"delta": chunk})
            yield sse({"done": True})
        except Exception as exc:  # provider errors are reported in-stream, like the Node API
            yield sse({"message": str(exc)}, event="error")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _user_log(session_id: str, content: str) -> dict:
    now = datetime.now(timezone.utc)
    return {"sessionId": session_id, "role": "user", "content": content, "createdAt": now, "updatedAt": now}
