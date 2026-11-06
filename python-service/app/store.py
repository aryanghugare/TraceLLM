"""MongoDB access. Routes and the worker depend on the small `Store` interface, not on pymongo
directly, so tests can swap in an in-memory implementation.

Collections and field names match the Node/Mongoose models (`logs`, `sessions`, camelCase),
so the Node and Python services can read and write the same database.
"""

from datetime import datetime, timezone
from typing import Any, Protocol

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient


class Store(Protocol):
    async def ping(self) -> None: ...
    async def list_sessions(self) -> list[dict]: ...
    async def get_session(self, session_id: str) -> dict | None: ...
    async def upsert_session(self, session_id: str, title: str | None) -> None: ...
    async def session_messages(self, session_id: str) -> list[dict]: ...
    async def recent_messages(self, session_id: str, limit: int) -> list[dict]: ...
    async def insert_log(self, document: dict) -> None: ...
    async def aggregate_logs(self, pipeline: list[dict]) -> list[dict]: ...
    async def find_logs(self, query: dict, sort: list[tuple[str, int]], limit: int) -> list[dict]: ...


def serialize(doc: dict | None) -> dict | None:
    """Make a Mongo document JSON-safe: ObjectId -> str, datetime -> ISO-8601 (UTC)."""
    if doc is None:
        return None
    out: dict[str, Any] = {}
    for key, value in doc.items():
        if key == "_id":
            out[key] = str(value)
        elif isinstance(value, datetime):
            value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            out[key] = value.isoformat().replace("+00:00", "Z")
        elif isinstance(value, dict):
            out[key] = serialize(value)
        else:
            out[key] = value
    return out


class MongoStore:
    def __init__(self, uri: str | None = None, *, database=None):
        """Pass a URI in production. Tests pass `database=` (an in-memory stand-in)."""
        self._client: AsyncMongoClient | None = None
        if database is None:
            # One client per process; it keeps its own connection pool.
            self._client = AsyncMongoClient(uri, tz_aware=True)
            database = self._client.get_default_database(default="tracellm")
        self._db = database
        self._logs = database["logs"]
        self._sessions = database["sessions"]

    async def ensure_indexes(self) -> None:
        await self._sessions.create_index("sessionId", unique=True)
        await self._logs.create_index([("sessionId", ASCENDING), ("createdAt", ASCENDING)])
        # Serves the analytics pipelines, which all filter by role + time range.
        await self._logs.create_index([("role", ASCENDING), ("createdAt", DESCENDING)])

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    async def ping(self) -> None:
        await self._db.command("ping")

    async def list_sessions(self) -> list[dict]:
        return await self._sessions.find({}).sort("updatedAt", DESCENDING).to_list()

    async def get_session(self, session_id: str) -> dict | None:
        return await self._sessions.find_one({"sessionId": session_id})

    async def upsert_session(self, session_id: str, title: str | None) -> None:
        now = datetime.now(timezone.utc)
        update: dict[str, Any] = {
            "$setOnInsert": {"sessionId": session_id, "createdAt": now},
            "$set": {"updatedAt": now},
        }
        if title:
            update["$set"]["title"] = title
        else:
            update["$setOnInsert"]["title"] = ""
        await self._sessions.update_one({"sessionId": session_id}, update, upsert=True)

    async def session_messages(self, session_id: str) -> list[dict]:
        return await self._logs.find({"sessionId": session_id}).sort("createdAt", ASCENDING).to_list()

    async def recent_messages(self, session_id: str, limit: int) -> list[dict]:
        cursor = self._logs.find({"sessionId": session_id}).sort("createdAt", DESCENDING).limit(limit)
        return list(reversed(await cursor.to_list()))

    async def insert_log(self, document: dict) -> None:
        await self._logs.insert_one(document)

    async def aggregate_logs(self, pipeline: list[dict]) -> list[dict]:
        cursor = await self._logs.aggregate(pipeline)
        return await cursor.to_list()

    async def find_logs(self, query: dict, sort: list[tuple[str, int]], limit: int) -> list[dict]:
        return await self._logs.find(query).sort(sort).limit(limit).to_list()
