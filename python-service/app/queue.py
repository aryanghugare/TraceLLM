"""Job queue used to move log writes off the request path.

The API only *enqueues* a payload (fast, one Redis call). The arq worker (app/worker.py)
consumes it, validates it and writes it to MongoDB, with retries and a dead-letter list.
"""

from typing import Protocol

from arq.connections import ArqRedis, RedisSettings, create_pool

INGEST_JOB = "ingest_log"


class JobQueue(Protocol):
    async def enqueue_log(self, payload: dict) -> None: ...
    async def ping(self) -> None: ...


class ArqQueue:
    def __init__(self, pool: ArqRedis, queue_name: str):
        self._pool = pool
        self._queue_name = queue_name

    @classmethod
    async def connect(cls, redis_url: str, queue_name: str) -> "ArqQueue":
        pool = await create_pool(RedisSettings.from_dsn(redis_url), default_queue_name=queue_name)
        return cls(pool, queue_name)

    async def enqueue_log(self, payload: dict) -> None:
        await self._pool.enqueue_job(INGEST_JOB, payload, _queue_name=self._queue_name)

    async def ping(self) -> None:
        await self._pool.ping()

    async def close(self) -> None:
        await self._pool.aclose()
