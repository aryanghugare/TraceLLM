"""The LLM gateway: streams a completion from any provider and traces it.

For every call it measures time-to-first-token and total time, collects token usage,
records Prometheus metrics, redacts PII from the output and enqueues an `InferenceLog`
for the background worker. Tracing never blocks or breaks the user's stream: if the
queue is down, the failure is counted and logged, and the response still completes.
"""

import logging
import time
from collections.abc import AsyncIterator

import anyio

from app import metrics
from app.llm.providers import Message, ProviderFactory, TextDelta, Usage
from app.queue import JobQueue
from app.redaction import redact_pii
from app.schemas import InferenceLog, InferenceMetadata, Latency, TokenUsage

log = logging.getLogger(__name__)


class LLMGateway:
    def __init__(self, queue: JobQueue, provider_factory: ProviderFactory):
        self._queue = queue
        self._provider_factory = provider_factory

    async def stream_chat(
        self,
        *,
        provider: str,
        api_key: str,
        model: str,
        messages: list[Message],
        session_id: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        client = self._provider_factory(provider, api_key)
        started = time.perf_counter()
        ttfb: float | None = None
        usage: Usage | None = None
        status = "success"
        chunks: list[str] = []

        try:
            async for event in client.stream(messages, model, temperature, max_tokens):
                if isinstance(event, TextDelta):
                    if ttfb is None:
                        ttfb = time.perf_counter() - started
                    chunks.append(event.text)
                    yield event.text
                elif isinstance(event, Usage):
                    usage = event
        except BaseException:
            # BaseException also covers cancellation (client disconnected mid-stream).
            status = "error"
            raise
        finally:
            # Shielded: if the request was cancelled, still get the trace into the queue.
            with anyio.CancelScope(shield=True):
                await self.trace(
                    provider=provider,
                    model=model,
                    session_id=session_id,
                    status=status,
                    content="".join(chunks),
                    total_s=time.perf_counter() - started,
                    ttfb_s=ttfb,
                    usage=usage,
                )

    async def trace(
        self,
        *,
        provider: str,
        model: str,
        session_id: str,
        status: str,
        content: str,
        total_s: float,
        ttfb_s: float | None,
        usage: Usage | None,
    ) -> None:
        """Record metrics and enqueue a log for one LLM call. Also used by the agent."""
        self._record_metrics(provider, model, status, ttfb_s, total_s, usage)
        entry = InferenceLog(
            session_id=session_id,
            content=redact_pii(content),
            metadata=InferenceMetadata(
                provider=provider,
                model=model,
                status=status,
                latency=Latency(
                    ttfb_ms=None if ttfb_s is None else round(ttfb_s * 1000, 2),
                    total_ms=round(total_s * 1000, 2),
                ),
                token_usage=(
                    TokenUsage(prompt=usage.prompt, completion=usage.completion, total=usage.total)
                    if usage
                    else None
                ),
            ),
        )
        await self._enqueue(entry)

    async def _enqueue(self, entry: InferenceLog) -> None:
        try:
            await self._queue.enqueue_log(entry.model_dump(by_alias=True, exclude_none=True, mode="json"))
        except Exception:
            metrics.QUEUE_ENQUEUE_FAILURES.inc()
            log.exception("Failed to enqueue inference log for session %s", entry.session_id)

    @staticmethod
    def _record_metrics(provider, model, status, ttfb, total, usage) -> None:
        metrics.LLM_REQUESTS.labels(provider, model, status).inc()
        metrics.LLM_DURATION.labels(provider, model).observe(total)
        if ttfb is not None:
            metrics.LLM_TTFB.labels(provider, model).observe(ttfb)
        if usage:
            metrics.LLM_TOKENS.labels(provider, model, "prompt").inc(usage.prompt)
            metrics.LLM_TOKENS.labels(provider, model, "completion").inc(usage.completion)
