from fastapi import APIRouter, Depends

from app import analytics
from app.routes.chat import get_store
from app.store import Store

router = APIRouter()


@router.get("/api/analytics")
async def get_analytics(store: Store = Depends(get_store)):
    return await analytics.dashboard(store)
