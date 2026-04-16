from uuid import uuid4
from fastapi import APIRouter, Query, Request
from core.schemas import ChatRequest, ChatResponse, TaskRequest, APIResponse
from orchestration.task_runner import run as run_task
from models.session_store import get_session_history, get_session_tasks
from core.logging import get_logger

router = APIRouter()
log = get_logger(__name__)

@router.post("/chat", response_model=APIResponse[ChatResponse])
async def chat(req: ChatRequest, request: Request):
    trace_id = str(uuid4())
    session_id = req.session_id or str(uuid4())
    user_id = req.user_id or "default_user"

    log.info("chat.request.start", trace_id=trace_id, session_id=session_id)

    task_req = TaskRequest(
        user_input=req.message,
        session_id=session_id,
        user_id=user_id,
        trace_id=trace_id,
    )
    result = await run_task(task_req)
    
    response_data = ChatResponse(
        response=result.final_answer,
        session_id=session_id,
        trace_id=trace_id,
        steps_taken=result.steps_taken,
        tools_used=list({e["tool"] for e in result.tool_calls_log if e.get("tool")}),
        tool_calls_made=len(result.tool_calls_log),
        agent_plan=result.agent_plan,
        status=result.status,
    )
    
    log.info("chat.request.complete", trace_id=trace_id, session_id=session_id,
             status=result.status, tool_calls_made=response_data.tool_calls_made)
    
    return APIResponse(success=True, data=response_data, message="Neural thread processed")

@router.get("/chat/{session_id}/history", response_model=APIResponse)
async def get_history(session_id: str, limit: int = Query(50, ge=1, le=500)):
    """Retrieve message history for a session."""
    messages = await get_session_history(session_id, limit=limit)
    data = {
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
    return APIResponse(success=True, data=data)

@router.get("/chat/{session_id}/tasks", response_model=APIResponse)
async def get_tasks(session_id: str, limit: int = Query(20, ge=1, le=100)):
    """Retrieve task execution history for a session."""
    tasks = await get_session_tasks(session_id, limit=limit)
    data = {"session_id": session_id, "tasks": tasks, "count": len(tasks)}
    return APIResponse(success=True, data=data)
