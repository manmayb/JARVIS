import asyncio, time
from core.schemas import TaskRequest, TaskResult, Message
from core.observability import get_logger
from core.config import settings
from orchestration.react_loop import run as run_loop

log = get_logger(__name__)

async def run(request: TaskRequest) -> TaskResult:
    start = time.monotonic()
    try:
        return await asyncio.wait_for(
            _run_inner(request, start),
            timeout=settings.global_timeout_seconds,
        )
    except asyncio.TimeoutError:
        elapsed  = round(time.monotonic() - start, 2)
        log_tail = getattr(request, "_tool_calls_log", [])
        last     = log_tail[-1] if log_tail else {}
        log.error("task.global_timeout",
                  trace_id=request.trace_id,
                  elapsed_seconds=elapsed,
                  last_step=getattr(request, "_steps_completed", 0),
                  last_tool=last.get("tool"),
                  last_thought_snippet=getattr(request, "_last_thought", "")[:200])
        return TaskResult(
            task_id=request.task_id,
            final_answer=(
                "This task took too long to complete. I returned the best result "
                "based on partial progress. Try narrowing the request or splitting "
                "it into smaller steps."
            ),
            status="timeout",
            steps_taken=getattr(request, "_steps_completed", 0),
            tool_calls_log=log_tail,
            trace_id=request.trace_id,
        )
    except asyncio.CancelledError:
        log.warning("task.cancelled", trace_id=request.trace_id)
        raise

async def _run_inner(request: TaskRequest, start: float) -> TaskResult:
    request._steps_completed = 0
    request._tool_calls_log  = []
    request._last_thought    = ""

    message_history = [Message(role="user", content=request.user_input)]
    result = await run_loop(request, message_history, start)

    return TaskResult(
        task_id=request.task_id,
        final_answer=result.answer,
        status=result.exit_reason,
        steps_taken=result.steps,
        tool_calls_log=result.tool_calls_log,
        trace_id=request.trace_id,
    )
