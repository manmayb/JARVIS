from fastapi import APIRouter
from core.schemas import APIResponse
from models.session_store import get_all_sessions
from core.logging import get_observability_metrics

router = APIRouter(prefix="/api")

@router.get("/sessions", response_model=APIResponse)
async def list_sessions():
    """Retrieve all tracked neural sessions."""
    sessions = await get_all_sessions()
    return APIResponse(success=True, data={"sessions": sessions})

@router.get("/memory/episodes", response_model=APIResponse)
async def get_episodes():
    """Retrieve recent episodic memory summaries."""
    from models.embeddings import get_recent_episodes
    episodes = await get_recent_episodes()
    return APIResponse(success=True, data={"episodes": episodes})

@router.get("/memory/facts/{user_id}", response_model=APIResponse)
async def get_facts(user_id: str):
    """Retrieve semantic facts for a specific user identity."""
    from models.embeddings import get_user_facts
    facts = await get_user_facts(user_id)
    return APIResponse(success=True, data={"facts": facts})
