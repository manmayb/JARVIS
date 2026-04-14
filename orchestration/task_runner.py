"""Task runner — entry point with global timeout, session persistence,
episodic memory storage, and optional task planning.
"""

import asyncio, time
from core.schemas import TaskRequest, TaskResult, Message
from core.observability import get_logger
from core.config import settings
from models.session_store import (
    get_or_create_session,
    get_session_history,
    append_message,
    save_task_result,
)
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
        log_tail = request._tool_calls_log
        last     = log_tail[-1] if log_tail else {}
        log.error("task.global_timeout",
                  trace_id=request.trace_id,
                  elapsed_seconds=elapsed,
                  last_step=request._steps_completed,
                  last_tool=last.get("tool"),
                  last_thought_snippet=request._last_thought[:200])
        return TaskResult(
            task_id=request.task_id,
            final_answer=(
                "This task took too long to complete. I returned the best result "
                "based on partial progress. Try narrowing the request or splitting "
                "it into smaller steps."
            ),
            status="timeout",
            steps_taken=request._steps_completed,
            tool_calls_log=log_tail,
            trace_id=request.trace_id,
        )
    except asyncio.CancelledError:
        log.warning("task.cancelled", trace_id=request.trace_id)
        raise


async def _run_inner(request: TaskRequest, start: float) -> TaskResult:
    # Ensure session exists in DB, then load its history
    await get_or_create_session(request.session_id, request.user_id)
    persisted = await get_session_history(request.session_id, limit=50)

    # Current user message
    user_msg = Message(role="user", content=request.user_input)

    # Working history = what was persisted + the new message
    message_history = persisted + [user_msg]

    # Persist the incoming user message immediately
    await append_message(request.session_id, user_msg)

    # ── Phase 3: Task Planner ──
    if settings.enable_planner:
        from orchestration.planner import generate_plan, execute_plan, needs_planning
        if needs_planning(request.user_input):
            log.info("task.planning", trace_id=request.trace_id)
            plan = await generate_plan(request.user_input, trace_id=request.trace_id)
            if not plan.is_simple and plan.subtasks:
                result_obj = await execute_plan(
                    plan, request, message_history, start)
                # Persist and store episode
                await _finalize(request, result_obj, start, message_history)
                return result_obj

    # ── Standard ReAct loop ──
    result = await run_loop(request, message_history, start)

    task_result = TaskResult(
        task_id=request.task_id,
        final_answer=result.answer,
        status=result.exit_reason,
        steps_taken=result.steps,
        tool_calls_log=result.tool_calls_log,
        trace_id=request.trace_id,
    )

    await _finalize(request, task_result, start, message_history)
    return task_result


async def _finalize(request: TaskRequest, result: TaskResult,
                    start: float, message_history: list[Message]) -> None:
    """Persist assistant response, save task result, and store episode."""

    # Persist the agent's final answer as an assistant message
    assistant_msg = Message(role="assistant", content=result.final_answer)
    await append_message(request.session_id, assistant_msg)

    # Save task result to log
    duration_ms = int((time.monotonic() - start) * 1000)
    tools_used  = list({e["tool"] for e in result.tool_calls_log
                        if e.get("tool")})
    await save_task_result(
        task_id=request.task_id,
        session_id=request.session_id,
        trace_id=request.trace_id,
        user_input=request.user_input,
        final_answer=result.final_answer,
        status=result.status,
        steps_taken=result.steps_taken,
        tools_used=tools_used,
        duration_ms=duration_ms,
    )

    # Phase 1: Store episodic memory
    if settings.enable_episodic_memory:
        try:
            from models.embeddings import store_episode
            summary = f"Q: {request.user_input[:200]} → A: {result.final_answer[:300]}"
            await store_episode(request.session_id, request.task_id, summary)
        except Exception as exc:
            log.warning("episodic.store_failed", error=str(exc),
                        trace_id=request.trace_id)
