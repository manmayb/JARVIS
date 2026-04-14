import uuid
from fastapi import APIRouter
from core.schemas import ChatRequest, ChatResponse, TaskRequest
from orchestration.task_runner import run as run_task

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    task_req   = TaskRequest(user_input=req.message, session_id=session_id)
    result     = await run_task(task_req)
    return ChatResponse(
        response=result.final_answer,
        session_id=session_id,
        trace_id=result.trace_id,
        steps_taken=result.steps_taken,
        tools_used=list({e["tool"] for e in result.tool_calls_log if e.get("tool")}),
        status=result.status,
    )
