import json

import pytest
from arq import Retry

from app.config import get_settings
from app.worker import backoff_seconds, ingest_log

VALID = {
    "sessionId": "s1",
    "content": "Hello",
    "metadata": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "status": "success",
        "latency": {"ttfbMs": 120.5, "totalMs": 900.0},
        "tokenUsage": {"prompt": 10, "completion": 5, "total": 15},
    },
}


class FakeRedis:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)


@pytest.fixture
def ctx(store):
    return {"store": store, "redis": FakeRedis(), "settings": get_settings(), "job_try": 1}


def dead_letters(ctx):
    return [json.loads(x) for x in ctx["redis"].lists.get(ctx["settings"].dead_letter_key, [])]


async def test_valid_log_is_stored_in_node_compatible_shape(ctx, db):
    assert await ingest_log(ctx, VALID) == "stored"
    doc = db["logs"].sync.find_one({"sessionId": "s1"})
    assert doc["role"] == "assistant"
    assert doc["metadata"]["latency"] == {"ttfbMs": 120.5, "totalMs": 900.0}
    assert doc["metadata"]["tokenUsage"]["total"] == 15
    assert doc["createdAt"] is not None


async def test_invalid_payload_is_dead_lettered_without_retrying(ctx, db):
    bad = {**VALID, "metadata": {**VALID["metadata"], "provider": "mistral"}}
    assert await ingest_log(ctx, bad) == "dead_lettered"
    assert db["logs"].sync.count_documents({}) == 0
    [record] = dead_letters(ctx)
    assert record["reason"] == "invalid_payload" and record["payload"] == bad


async def test_unknown_fields_are_rejected(ctx):
    assert await ingest_log(ctx, {**VALID, "__attempts": 2}) == "dead_lettered"


async def test_transient_db_failure_is_retried_with_backoff(ctx, db):
    db["logs"].fail_next_inserts = 1
    with pytest.raises(Retry) as exc:
        await ingest_log(ctx, VALID)
    assert exc.value.defer_score == 1000  # 1s on the first try (arq stores ms)

    ctx["job_try"] = 2
    assert await ingest_log(ctx, VALID) == "stored"
    assert dead_letters(ctx) == []


async def test_final_failure_is_dead_lettered_not_lost(ctx, db):
    db["logs"].fail_next_inserts = 5
    ctx["job_try"] = ctx["settings"].ingestion_max_tries
    assert await ingest_log(ctx, VALID) == "dead_lettered"
    [record] = dead_letters(ctx)
    assert record["reason"] == "write_failed" and record["attempts"] == 3


def test_backoff_grows_and_is_capped():
    assert [backoff_seconds(n) for n in (1, 2, 3, 4)] == [1, 2, 4, 8]
    assert backoff_seconds(10) == 30
