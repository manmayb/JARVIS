import asyncio, time
from typing import Optional
from core.schemas import TaskRequest, TaskResult, Message
from core.logging import get_logger
from core.config import settings
from core.exceptions import JARVISException, OrchestrationError, ProviderError
from core.error_codes import AppErrorCode
from models.session_store import (
    get_or_create_session,
    get_session_history,
    append_message,
    save_task_result,
)
from orchestration.react_loop import run as run_loop, run_orchestrated
from orchestration.semantic_extractor import schedule_fact_extraction

log = get_logger(__name__)

async def run(request: TaskRequest) -> TaskResult:
    """Service entry point for executing a user task with orchestration."""
    start = time.monotonic()
    try:
        return await asyncio.wait_for(
            _run_inner(request, start),
            timeout=settings.global_timeout_seconds,
        )
    except asyncio.TimeoutError:
        elapsed = round(time.monotonic() - start, 2)
        log.error("task.global_timeout", trace_id=request.trace_id, elapsed_seconds=elapsed)
        raise OrchestrationError(
            f"Operation timed out after {settings.global_timeout_seconds}s",
            error_code=AppErrorCode.TOOL_TIMEOUT
        )
    except JARVISException:
        raise
    except Exception as exc:
        log.error("task.unhandled_service_error", 
                  trace_id=request.trace_id, 
                  error=str(exc), 
                  exc_info=True)
        raise JARVISException(
            "An internal orchestration error occurred", 
            error_code=AppErrorCode.INTERNAL_ERROR
        )

async def _run_inner(request: TaskRequest, start: float) -> TaskResult:
    # Ensure session exists in DB
    await get_or_create_session(request.session_id, request.user_id)
    persisted = await get_session_history(request.session_id, limit=50)

    user_msg = Message(role="user", content=request.user_input)
    message_history = persisted + [user_msg]
    await append_message(request.session_id, user_msg)

    # ── Phase 3: Task Planner ──
    if settings.enable_planner:
        from orchestration.planner import generate_plan, execute_plan, needs_planning
        if needs_planning(request.user_input):
            try:
                plan = await generate_plan(request.user_input, trace_id=request.trace_id)
                if not plan.is_simple and plan.subtasks:
                    result_obj = await execute_plan(plan, request, message_history, start)
                    await _finalize(request, result_obj, start, message_history)
                    return result_obj
            except Exception as e:
                log.warning("task.planning_failed_falling_back", error=str(e))

    # ── Multi-Agent Orchestration ──
    try:
        result = await run_orchestrated(request, message_history, start)
    except Exception as exc:
        log.error("task.orchestration_failed", 
                  trace_id=request.trace_id, 
                  session_id=request.session_id,
                  error=str(exc))
        raise OrchestrationError(f"Agent orchestration failed: {str(exc)}")

    task_result = TaskResult(
        task_id=request.task_id,
        final_answer=result.answer,
        status=result.exit_reason,
        steps_taken=result.steps,
        tool_calls_log=result.tool_calls_log,
        agent_plan=result.agent_plan,
        trace_id=request.trace_id,
    )

    await _finalize(request, task_result, start, message_history)
    log.info("task.complete", 
             trace_id=request.trace_id, 
             session_id=request.session_id, 
             status=task_result.status)
    return task_result

async def _finalize(request: TaskRequest, result: TaskResult,
                    start: float, message_history: list[Message]) -> None:
    # Persist and extract
    assistant_msg = Message(role="assistant", content=result.final_answer)
    await append_message(request.session_id, assistant_msg)

    duration_ms = int((time.monotonic() - start) * 1000)
    tools_used  = list({e["tool"] for e in result.tool_calls_log if e.get("tool")})
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

    if settings.enable_episodic_memory:
        try:
            from models.embeddings import store_episode
            summary = f"Q: {request.user_input[:200]} → A: {result.final_answer[:300]}"
            await store_episode(request.session_id, request.task_id, summary)
        except Exception as exc:
            log.warning("episodic.store_failed", error=str(exc))

    if settings.enable_semantic_memory:
        schedule_fact_extraction(request.user_id, message_history, request.trace_id)
