import asyncio, time, json
from core.schemas import TaskRequest, Message
from core.config import settings
from core.llm_parser import parse_think_output
from core.observability import get_logger
from orchestration.llm_router import call as llm_call
from orchestration.context_assembler import build as assemble_context
from orchestration.loop_guard import LoopGuard, Step, hash_params
from tools.executor import execute as tool_execute
from tools.schemas import ToolCallRequest
from pydantic import BaseModel
from typing import Optional

log = get_logger(__name__)

MAX_OBSERVATION_CHARS = 2000

class LoopResult(BaseModel):
    answer: str
    exit_reason: str
    steps: int
    tool_calls_log: list[dict] = []

async def run(request: TaskRequest,
              message_history: list[Message],
              start_time: float) -> LoopResult:

    guard      = LoopGuard(max_steps=settings.max_steps)
    step_count = 0
    trace_id   = request.trace_id

    while True:
        system, messages = assemble_context(request, message_history)
        llm_resp = await llm_call(messages, system, trace_id=trace_id)
        thought  = parse_think_output(llm_resp.content, trace_id)
        request._last_thought = thought.thought

        message_history.append(Message(role="assistant", content=llm_resp.content))

        if thought.action_type == "final_answer":
            log.info("loop.final_answer", steps=step_count, trace_id=trace_id)
            return LoopResult(answer=thought.final_answer or "Done.",
                              exit_reason="completed", steps=step_count,
                              tool_calls_log=request._tool_calls_log)

        violation = guard.check(step_count)
        if violation:
            log.warning("loop.guard_violation", code=violation.code,
                        message=violation.message, trace_id=trace_id)
            return LoopResult(answer=_partial_answer(message_history),
                              exit_reason=violation.code, steps=step_count,
                              tool_calls_log=request._tool_calls_log)

        step_count += 1
        request._steps_completed = step_count

        elapsed          = time.monotonic() - start_time
        budget_exhausted = elapsed > (settings.global_timeout_seconds
                                      * settings.retry_budget_threshold)
        in_retry         = bool(request._tool_calls_log and
                                not request._tool_calls_log[-1]["success"])
        effective_retries = (0 if (budget_exhausted and not in_retry)
                             else settings.max_retries_per_tool)

        call_req = ToolCallRequest(
            tool_name=thought.tool_name,
            parameters=thought.tool_parameters or {},
            session_id=request.session_id,
            user_id=request.user_id,
            step_number=step_count,
            trace_id=trace_id,
        )

        log.info("loop.tool_call", tool=thought.tool_name,
                 step=step_count, trace_id=trace_id)
        result = await tool_execute(call_req, max_retries=effective_retries)

        request._tool_calls_log.append({
            "step":       step_count,
            "tool":       call_req.tool_name,
            "success":    result.success,
            "latency_ms": result.latency_ms,
            "error_code": result.error.code if not result.success else None,
        })

        if result.success:
            observation = json.dumps(result.output)
        else:
            observation = (f"Tool '{call_req.tool_name}' failed: {result.error.message}. "
                           + ("Try a different approach." if not result.error.retryable
                              else "Retries exhausted."))

        if len(observation) > MAX_OBSERVATION_CHARS:
            observation = observation[:MAX_OBSERVATION_CHARS] + "... [truncated]"

        message_history.append(Message(
            role="user",
            content=f"<observation>{observation}</observation>"
        ))

        guard.record(Step(
            tool_name=call_req.tool_name,
            params_hash=hash_params(call_req.parameters),
            tool_success=result.success,
            observation_length=len(observation),
        ))

def _partial_answer(history: list[Message]) -> str:
    for msg in reversed(history):
        if msg.role == "assistant" and msg.content:
            return f"Task stopped early. Last reasoning: {msg.content[:300]}"
    return "Task stopped early — no partial result available."
