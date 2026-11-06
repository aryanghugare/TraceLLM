"""Prometheus metrics. The API exposes them at GET /metrics; the worker on its own port.

Naming follows Prometheus conventions: `_total` for counters, `_seconds` for durations.
Labels are kept low-cardinality (provider, model, route template), never session ids.
"""

from prometheus_client import Counter, Histogram

# HTTP layer
HTTP_REQUESTS = Counter(
    "tracellm_http_requests_total", "HTTP requests handled", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "tracellm_http_request_duration_seconds", "HTTP request duration", ["method", "route"]
)

# LLM calls
_LLM_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64)
LLM_REQUESTS = Counter(
    "tracellm_llm_requests_total", "LLM calls by outcome", ["provider", "model", "status"]
)
LLM_TTFB = Histogram(
    "tracellm_llm_ttfb_seconds", "Time to first token", ["provider", "model"], buckets=_LLM_BUCKETS
)
LLM_DURATION = Histogram(
    "tracellm_llm_duration_seconds", "End-to-end LLM call time", ["provider", "model"], buckets=_LLM_BUCKETS
)
LLM_TOKENS = Counter(
    "tracellm_llm_tokens_total", "Tokens used", ["provider", "model", "kind"]  # kind: prompt|completion
)

# Queue and worker
QUEUE_ENQUEUE_FAILURES = Counter(
    "tracellm_queue_enqueue_failures_total", "Inference logs that could not be enqueued"
)
WORKER_JOBS = Counter(
    "tracellm_worker_jobs_total", "Ingestion jobs by outcome", ["outcome"]  # stored|retried|dead_lettered
)

# Agent
AGENT_RUNS = Counter("tracellm_agent_runs_total", "Agent runs by outcome", ["outcome"])
AGENT_TOOL_CALLS = Counter(
    "tracellm_agent_tool_calls_total", "Agent tool calls", ["tool", "outcome"]
)
