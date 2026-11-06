"""Background ingestion worker (arq). Run with:  arq app.worker.WorkerSettings

For each queued inference log:
  1. validate it with Pydantic. Invalid payloads can never succeed, so they go straight
     to the dead-letter list instead of being retried.
  2. write it to MongoDB. Transient failures (DB down, timeout) are retried with backoff;
     after the last try the payload is dead-lettered, so nothing is silently lost.
Dead-lettered payloads sit in a Redis list (`DEAD_LETTER_KEY`) for inspection or replay.
"""

import json
import logging
from datetime import datetime, timezone

from arq import Retry, func
from arq.connections import RedisSettings
from prometheus_client import start_http_server
from pydantic import ValidationError

from app import metrics
from app.config import get_settings
from app.queue import INGEST_JOB
from app.schemas import InferenceLog
from app.store import MongoStore

log = logging.getLogger(__name__)


def backoff_seconds(job_try: int) -> int:
    """1s, 2s, 4s, ... capped at 30s."""
    return min(2 ** (job_try - 1), 30)


async def dead_letter(ctx: dict, payload: dict, reason: str, details=None) -> None:
    record = {
        "payload": payload,
        "reason": reason,
        "details": details,
        "attempts": ctx.get("job_try", 1),
        "failedAt": datetime.now(timezone.utc).isoformat(),
    }
    await ctx["redis"].lpush(ctx["settings"].dead_letter_key, json.dumps(record, default=str))
    metrics.WORKER_JOBS.labels("dead_lettered").inc()
    log.warning("Dead-lettered inference log: %s", reason)


async def ingest_log(ctx: dict, payload: dict) -> str:
    try:
        entry = InferenceLog.model_validate(payload)
    except ValidationError as exc:
        await dead_letter(ctx, payload, "invalid_payload", exc.errors(include_url=False))
        return "dead_lettered"

    try:
        await ctx["store"].insert_log(entry.to_document())
    except Exception as exc:
        job_try = ctx.get("job_try", 1)
        if job_try >= ctx["settings"].ingestion_max_tries:
            await dead_letter(ctx, payload, "write_failed", str(exc))
            return "dead_lettered"
        metrics.WORKER_JOBS.labels("retried").inc()
        raise Retry(defer=backoff_seconds(job_try)) from exc

    metrics.WORKER_JOBS.labels("stored").inc()
    return "stored"


async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    ctx["store"] = MongoStore(settings.mongodb_uri)
    await ctx["store"].ensure_indexes()
    start_http_server(settings.worker_metrics_port)  # Prometheus scrapes the worker here
    log.info("Ingestion worker started; metrics on :%s", settings.worker_metrics_port)


async def shutdown(ctx: dict) -> None:
    await ctx["store"].close()


_settings = get_settings()


class WorkerSettings:
    functions = [func(ingest_log, name=INGEST_JOB, max_tries=_settings.ingestion_max_tries)]
    queue_name = _settings.queue_name
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    max_jobs = _settings.ingestion_worker_concurrency
    on_startup = startup
    on_shutdown = shutdown
