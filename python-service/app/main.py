"""FastAPI application. Run with:  uvicorn app.main:app --port 8000

`create_app()` accepts optional dependencies so tests can inject in-memory fakes;
in production they are created from settings during startup (the lifespan handler).
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import metrics
from app.agent.models import default_agent_model_factory
from app.config import get_settings
from app.llm.gateway import LLMGateway
from app.llm.providers import default_provider_factory
from app.queue import ArqQueue
from app.routes import agent, analytics, chat
from app.store import MongoStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(*, store=None, queue=None, provider_factory=None, agent_model_factory=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = get_settings()
        owned = []  # resources we opened here and must close on shutdown

        app.state.store = store
        if app.state.store is None:
            app.state.store = MongoStore(settings.mongodb_uri)
            await app.state.store.ensure_indexes()
            owned.append(app.state.store)

        app.state.queue = queue
        if app.state.queue is None:
            app.state.queue = await ArqQueue.connect(settings.redis_url, settings.queue_name)
            owned.append(app.state.queue)

        app.state.gateway = LLMGateway(app.state.queue, provider_factory or default_provider_factory)
        app.state.agent_model_factory = agent_model_factory or default_agent_model_factory
        yield
        for resource in owned:
            await resource.close()

    app = FastAPI(title="TraceLLM API (Python)", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        # Use the route template (/api/sessions/{session_id}), not the raw path, to keep
        # label cardinality bounded. For SSE responses this measures time to first byte.
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        metrics.HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        metrics.HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - started)
        return response

    app.include_router(chat.router)
    app.include_router(analytics.router)
    app.include_router(agent.router)

    @app.get("/health")
    async def health():
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request):
        """Readiness: MongoDB and Redis are reachable. Kubernetes stops routing traffic if not."""
        checks = {}
        for name, dep in (("mongodb", request.app.state.store), ("redis", request.app.state.queue)):
            try:
                await dep.ping()
                checks[name] = "ok"
            except Exception as exc:
                checks[name] = f"error: {exc}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)

    @app.get("/metrics")
    async def prometheus_metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
