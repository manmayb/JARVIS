import uuid
from fastapi import APIRouter, Request, Query
from core.schemas import ChatRequest, ChatResponse, TaskRequest
from orchestration.task_runner import run as run_task
from models.session_store import get_session_history, get_session_tasks

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    trace_id = getattr(request.state, "trace_id", None) or f"tr_{uuid.uuid4().hex[:12]}"
    task_req   = TaskRequest(user_input=req.message, session_id=session_id, trace_id=trace_id)
    result     = await run_task(task_req)
    return ChatResponse(
        response=result.final_answer,
        session_id=session_id,
        trace_id=result.trace_id,
        steps_taken=result.steps_taken,
        tools_used=list({e["tool"] for e in result.tool_calls_log if e.get("tool")}),
        status=result.status,
    )


@router.get("/chat/{session_id}/history")
async def get_history(session_id: str, limit: int = Query(50, ge=1, le=500)):
    """Retrieve message history for a session."""
    messages = await get_session_history(session_id, limit=limit)
    return {
        "session_id": session_id,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
            }
            for m in messages
        ],
        "count": len(messages),
    }


@router.get("/chat/{session_id}/tasks")
async def get_tasks(session_id: str, limit: int = Query(20, ge=1, le=100)):
    """Retrieve task execution history for a session."""
    tasks = await get_session_tasks(session_id, limit=limit)
    return {
        "session_id": session_id,
        "tasks": tasks,
        "count": len(tasks),
    }
