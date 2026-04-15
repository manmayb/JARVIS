from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from core.errors import AgentError
from core.schemas import ChatRequest, ChatResponse, ErrorResponse, TaskRequest
from orchestration.task_runner import run as run_task
from models.session_store import get_session_history, get_session_tasks
from core.observability import get_logger

router = APIRouter()
log = get_logger(__name__)

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    trace_id = str(uuid4())
    session_id = req.session_id or str(uuid4())
    user_id = req.user_id or "default_user"

    log.info("chat.request.start", trace_id=trace_id, session_id=session_id)

    try:
        task_req = TaskRequest(
            user_input=req.message,
            session_id=session_id,
            user_id=user_id,
            trace_id=trace_id,
        )
        result = await run_task(task_req)
        response = ChatResponse(
            response=result.final_answer,
            session_id=session_id,
            trace_id=trace_id,
            steps_taken=result.steps_taken,
            tools_used=list({e["tool"] for e in result.tool_calls_log if e.get("tool")}),
            tool_calls_made=len(result.tool_calls_log),
            status=result.status,
        )
        log.info("chat.request.complete", trace_id=trace_id, session_id=session_id,
                 status=result.status, tool_calls_made=response.tool_calls_made)
        return response
    except AgentError as exc:
        log.error("chat.request.agent_error", trace_id=trace_id,
                  session_id=session_id, error=str(exc))
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=str(exc),
                error_code="AGENT_ERROR",
                trace_id=trace_id,
                session_id=session_id,
            ).model_dump(),
        )
    except ValueError as exc:
        log.error("chat.request.value_error", trace_id=trace_id,
                  session_id=session_id, error=str(exc))
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error=str(exc),
                error_code="VALUE_ERROR",
                trace_id=trace_id,
                session_id=session_id,
            ).model_dump(),
        )
    except Exception as exc:
        log.error("chat.request.unhandled_error", trace_id=trace_id,
                  session_id=session_id, error=str(exc))
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="An unexpected error occurred.",
                error_code="INTERNAL_ERROR",
                trace_id=trace_id,
                session_id=session_id,
            ).model_dump(),
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
