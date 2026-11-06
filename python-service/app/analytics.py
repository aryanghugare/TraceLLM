"""MongoDB aggregation queries over the inference logs.

Shared by the dashboard endpoint (GET /api/analytics) and by the agent's tools, so the
numbers the agent reasons about are exactly the numbers the dashboard shows.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from app.store import Store, serialize


def _since(**delta) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**delta)


async def latency_by_provider(store: Store, hours: int = 24) -> list[dict]:
    """Average time-to-first-token and total latency per provider over the last `hours`."""
    return await store.aggregate_logs([
        {"$match": {
            "role": "assistant",
            "createdAt": {"$gte": _since(hours=hours)},
            "metadata.provider": {"$exists": True},
            "metadata.latency.ttfbMs": {"$type": "number"},
            "metadata.latency.totalMs": {"$type": "number"},
        }},
        {"$group": {
            "_id": "$metadata.provider",
            "avgTtfbMs": {"$avg": "$metadata.latency.ttfbMs"},
            "avgTotalMs": {"$avg": "$metadata.latency.totalMs"},
            "count": {"$sum": 1},
        }},
        {"$project": {"_id": 0, "provider": "$_id", "avgTtfbMs": 1, "avgTotalMs": 1, "count": 1}},
        {"$sort": {"provider": 1}},
    ])


async def token_throughput(store: Store, days: int = 7) -> list[dict]:
    """Total tokens per hour (UTC buckets) over the last `days`."""
    return await store.aggregate_logs([
        {"$match": {
            "role": "assistant",
            "createdAt": {"$gte": _since(days=days)},
            "metadata.tokenUsage.total": {"$type": "number"},
        }},
        {"$group": {
            # Dates are stored in UTC, so no timezone conversion is needed for UTC buckets.
            "_id": {"$dateToString": {"format": "%Y-%m-%dT%H:00:00.000Z", "date": "$createdAt"}},
            "totalTokens": {"$sum": "$metadata.tokenUsage.total"},
        }},
        {"$project": {"_id": 0, "hour": "$_id", "totalTokens": 1}},
        {"$sort": {"hour": 1}},
    ])


async def errors_by_model(store: Store) -> list[dict]:
    """Success and error counts per model (all time)."""
    return await store.aggregate_logs([
        {"$match": {
            "role": "assistant",
            "metadata.model": {"$exists": True},
            "metadata.status": {"$in": ["success", "error"]},
        }},
        {"$group": {
            "_id": "$metadata.model",
            "success": {"$sum": {"$cond": [{"$eq": ["$metadata.status", "success"]}, 1, 0]}},
            "error": {"$sum": {"$cond": [{"$eq": ["$metadata.status", "error"]}, 1, 0]}},
        }},
        {"$project": {"_id": 0, "model": "$_id", "success": 1, "error": 1}},
        {"$sort": {"model": 1}},
    ])


async def recent_errors(store: Store, limit: int = 5) -> list[dict]:
    """The most recent failed calls, with a short preview of any partial output."""
    docs = await store.find_logs(
        {"role": "assistant", "metadata.status": "error"}, sort=[("createdAt", -1)], limit=limit
    )
    return [
        {
            "sessionId": d.get("sessionId"),
            "provider": d.get("metadata", {}).get("provider"),
            "model": d.get("metadata", {}).get("model"),
            "latency": d.get("metadata", {}).get("latency"),
            "createdAt": serialize({"t": d.get("createdAt")})["t"],
            "contentPreview": (d.get("content") or "")[:120],
        }
        for d in docs
    ]


async def dashboard(store: Store) -> dict:
    """The full payload for GET /api/analytics (same shape as the Node API)."""
    latency, throughput, errors = await asyncio.gather(
        latency_by_provider(store, 24), token_throughput(store, 7), errors_by_model(store)
    )
    return {
        "latency": {"rangeHours": 24, "series": latency},
        "throughput": {"rangeDays": 7, "series": throughput},
        "errors": {"series": errors},
    }
