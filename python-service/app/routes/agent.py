from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.agent.runner import run_agent
from app.config import Settings, get_settings
from app.routes.chat import get_gateway, get_store
from app.schemas import AgentRequest

router = APIRouter()


@router.post("/api/agent/ask")
async def ask_agent(
    body: AgentRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    store=Depends(get_store),
    gateway=Depends(get_gateway),
):
    """Ask a question about the trace data; the agent decides which analytics tools to call."""
    api_key = body.apiKey or settings.api_key_for(body.provider)
    if not api_key:
        return JSONResponse({"error": "Missing API key for provider", "provider": body.provider}, status_code=400)

    model = request.app.state.agent_model_factory(
        body.provider, api_key, body.model or settings.default_model_for(body.provider)
    )
    try:
        result = await run_agent(body.question, model, store, gateway, body.maxSteps or settings.agent_max_steps)
    except Exception as exc:  # the upstream LLM failed; the run is already traced as an error
        return JSONResponse({"error": f"Agent LLM call failed: {exc}"}, status_code=502)

    return {
        "runId": result.run_id,
        "answer": result.answer,
        "stoppedReason": result.stopped_reason,
        "steps": result.steps,
    }
