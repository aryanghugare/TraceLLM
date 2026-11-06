"""Test fixtures: in-memory MongoDB and queue, plus scripted LLMs, so the suite needs no
running services and no API keys. The real MongoStore, gateway, routes, worker and agent
code all run unchanged on top of these fakes."""

from collections.abc import AsyncIterator

import mongomock
import pytest
from fastapi.testclient import TestClient

from app.agent.models import AgentTurn
from app.config import get_settings
from app.llm.providers import TextDelta, Usage
from app.main import create_app
from app.store import MongoStore


# ---------- in-memory MongoDB with the async pymongo API surface MongoStore uses ----------

class _Cursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def sort(self, *args, **kwargs):
        self._cursor = self._cursor.sort(*args, **kwargs)
        return self

    def limit(self, n):
        self._cursor = self._cursor.limit(n)
        return self

    async def to_list(self, length=None):
        return list(self._cursor)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=None):
        return self._rows


class AsyncCollection:
    def __init__(self, collection):
        self._c = collection
        self.fail_next_inserts = 0  # simulate a flaky database

    def find(self, *args, **kwargs):
        return _Cursor(self._c.find(*args, **kwargs))

    async def find_one(self, *args, **kwargs):
        return self._c.find_one(*args, **kwargs)

    async def insert_one(self, doc):
        if self.fail_next_inserts:
            self.fail_next_inserts -= 1
            raise ConnectionError("simulated MongoDB outage")
        return self._c.insert_one(dict(doc))

    async def update_one(self, *args, **kwargs):
        return self._c.update_one(*args, **kwargs)

    async def create_index(self, *args, **kwargs):
        return self._c.create_index(*args, **kwargs)

    async def aggregate(self, pipeline):
        return _Rows(list(self._c.aggregate(pipeline)))

    # direct access for assertions / seeding
    @property
    def sync(self):
        return self._c


class AsyncDatabase:
    def __init__(self):
        self._db = mongomock.MongoClient(tz_aware=True).db
        self._collections: dict[str, AsyncCollection] = {}

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = AsyncCollection(self._db[name])
        return self._collections[name]

    async def command(self, name):
        return {"ok": 1}


class FakeQueue:
    def __init__(self):
        self.jobs: list[dict] = []
        self.fail = False

    async def enqueue_log(self, payload: dict) -> None:
        if self.fail:
            raise ConnectionError("simulated Redis outage")
        self.jobs.append(payload)

    async def ping(self) -> None:
        if self.fail:
            raise ConnectionError("simulated Redis outage")


# ---------- scripted LLMs ----------

class ScriptedProvider:
    """Streams fixed chunks, optionally raising after them (to test error handling)."""

    def __init__(self, chunks=("Hello", " world"), usage=Usage(11, 2), error: Exception | None = None):
        self.chunks, self.usage, self.error = chunks, usage, error
        self.calls: list[dict] = []

    async def stream(self, messages, model, temperature, max_tokens) -> AsyncIterator:
        self.calls.append({"messages": messages, "model": model,
                           "temperature": temperature, "max_tokens": max_tokens})
        for chunk in self.chunks:
            yield TextDelta(chunk)
        if self.error:
            raise self.error
        if self.usage:
            yield self.usage


class ScriptedAgentModel:
    """Returns pre-scripted turns in order and records what it was shown."""

    def __init__(self, turns: list[AgentTurn], provider="openai", model="test-model"):
        self.turns, self.provider, self.model = list(turns), provider, model
        self.seen_transcripts: list[list] = []

    async def next_turn(self, system, transcript, tools):
        self.seen_transcripts.append(list(transcript))
        if not self.turns:
            raise RuntimeError("script exhausted")
        return self.turns.pop(0)


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db():
    return AsyncDatabase()


@pytest.fixture
def store(db):
    return MongoStore(database=db)


@pytest.fixture
def queue():
    return FakeQueue()


@pytest.fixture
def provider():
    return ScriptedProvider()


@pytest.fixture
def agent_box():
    """Holds the scripted agent model a test wants the app to use."""
    return {"model": None}


@pytest.fixture
def client(store, queue, provider, agent_box):
    app = create_app(
        store=store,
        queue=queue,
        provider_factory=lambda name, key: provider,
        agent_model_factory=lambda name, key, model: agent_box["model"],
    )
    with TestClient(app) as c:  # `with` runs the startup/shutdown lifespan
        yield c
