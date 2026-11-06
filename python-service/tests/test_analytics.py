from datetime import datetime, timedelta, timezone


def seed(db, *, provider, model, status, ttfb, total, tokens, age=timedelta(minutes=5)):
    db["logs"].sync.insert_one({
        "sessionId": "s1",
        "role": "assistant",
        "content": "x",
        "createdAt": datetime.now(timezone.utc) - age,
        "metadata": {
            "provider": provider, "model": model, "status": status,
            "latency": {"ttfbMs": ttfb, "totalMs": total},
            **({"tokenUsage": {"prompt": tokens, "completion": 0, "total": tokens}} if tokens else {}),
        },
    })


def test_analytics_payload_matches_node_shape_and_numbers(client, db):
    seed(db, provider="openai", model="gpt-4o-mini", status="success", ttfb=100, total=1000, tokens=50)
    seed(db, provider="openai", model="gpt-4o-mini", status="error", ttfb=300, total=3000, tokens=None)
    seed(db, provider="anthropic", model="claude", status="success", ttfb=200, total=800, tokens=20)
    seed(db, provider="openai", model="gpt-4o-mini", status="success", ttfb=9999, total=9999, tokens=5,
         age=timedelta(days=2))  # outside the 24h latency window, inside the 7d token window
    db["logs"].sync.insert_one({"sessionId": "s1", "role": "user", "content": "q",
                                "createdAt": datetime.now(timezone.utc)})  # ignored: not assistant

    data = client.get("/api/analytics").json()

    assert data["latency"]["rangeHours"] == 24
    assert data["latency"]["series"] == [
        {"provider": "anthropic", "avgTtfbMs": 200.0, "avgTotalMs": 800.0, "count": 1},
        {"provider": "openai", "avgTtfbMs": 200.0, "avgTotalMs": 2000.0, "count": 2},
    ]
    assert data["throughput"]["rangeDays"] == 7
    assert sum(p["totalTokens"] for p in data["throughput"]["series"]) == 75
    assert all(p["hour"].endswith(":00:00.000Z") for p in data["throughput"]["series"])
    assert data["errors"]["series"] == [
        {"model": "claude", "success": 1, "error": 0},
        {"model": "gpt-4o-mini", "success": 2, "error": 1},
    ]
