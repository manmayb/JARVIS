"""ReAct loop — Think → Act → Observe.

Phase 2 enhancements:
- Uses ``build_enriched`` for episodic/semantic memory injection.
- Supports parallel tool execution when the LLM returns a
  ``tool_calls`` array (list of tool_call dicts) instead of a single tool_call.
- Integrates the tool-output TTL cache.
"""

import asyncio, time, json
from core.schemas import TaskRequest, Message
from core.config import settings
from core.llm_parser import parse_think_output
from core.logging import (
    get_logger,
    increment_facts_extracted_total,
)
from core.cache import tool_cache, TTLCache
from orchestration.llm_router import call as llm_call
from orchestration.context_assembler import build_enriched, build
from orchestration.loop_guard import LoopGuard, Step, hash_params
from tools.executor import execute as tool_execute
from tools.schemas import ToolCallRequest
from models.session_store import save_session
from orchestration.semantic_extractor import extract_facts, save_facts
from pydantic import BaseModel
from typing import Optional, Callable, Awaitable

log = get_logger(__name__)

MAX_OBSERVATION_CHARS = 2000


class LoopResult(BaseModel):
    answer: str
    exit_reason: str
    steps: int
    tool_calls_log: list[dict] = []
    agent_plan: list[dict] = []


async def _persist_session_snapshot(request: TaskRequest,
                                    message_history: list[Message]) -> None:
    """Persist the current turn state so the session can be restored later."""
    await save_session(
        request.session_id,
        {
            "session_id": request.session_id,
            "user_id": request.user_id,
            "trace_id": request.trace_id,
            "steps_completed": request._steps_completed,
            "last_thought": request._last_thought,
            "tool_calls_log": request._tool_calls_log,
            "messages": message_history,
        },
    )


async def _background_extract(session_id: str,
                              user_id: str,
                              user_message: str,
                              assistant_reply: str,
                              trace_id: str) -> None:
    """Extract and persist semantic facts without delaying the response."""
    try:
        facts = await extract_facts(user_message, assistant_reply, trace_id)
        if not facts:
            return
        saved = await save_facts(user_id, facts)
        if saved > 0:
            await increment_facts_extracted_total(saved)
        log.info("facts.extracted.background",
                 trace_id=trace_id,
                 session_id=session_id,
                 saved=saved)
    except Exception as exc:
        log.warning("facts.extraction.background_failed",
                    trace_id=trace_id,
                    session_id=session_id,
                    error=str(exc))


async def run(request: TaskRequest,
              message_history: list[Message],
              start_time: float,
              pre_execute_hook: Optional[Callable[[str, dict], Awaitable[bool]]] = None) -> LoopResult:

    guard      = LoopGuard(max_steps=settings.max_steps)
    step_count = 0
    trace_id   = request.trace_id

    while True:
        # Use enriched context (with episodic + semantic memory) on the
        # first iteration; fall back to sync ``build`` on subsequent steps
        # to keep latency low inside the loop.
        if step_count == 0:
            try:
                system, messages = await build_enriched(request, message_history)
            except Exception:
                system, messages = build(request, message_history)
        else:
            system, messages = build(request, message_history)

        llm_resp = await llm_call(messages, system, trace_id=trace_id)
        thought  = parse_think_output(llm_resp.content, trace_id)
        request._last_thought = thought.thought

        message_history.append(Message(role="assistant", content=llm_resp.content))

        if thought.action_type == "final_answer":
            await _persist_session_snapshot(request, message_history)
            asyncio.create_task(
                _background_extract(
                    session_id=request.session_id,
                    user_id=request.user_id,
                    user_message=request.user_input,
                    assistant_reply=thought.final_answer or "Done.",
                    trace_id=trace_id,
                )
            )
            log.info("loop.final_answer", steps=step_count, trace_id=trace_id)
            return LoopResult(answer=thought.final_answer or "Done.",
                              exit_reason="completed", steps=step_count,
                              tool_calls_log=request._tool_calls_log)

        violation = guard.check(step_count)
        if violation:
            await _persist_session_snapshot(request, message_history)
            asyncio.create_task(
                _background_extract(
                    session_id=request.session_id,
                    user_id=request.user_id,
                    user_message=request.user_input,
                    assistant_reply=_partial_answer(message_history),
                    trace_id=trace_id,
                )
            )
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

        # ── Execute tool (with cache) ──
        # Call pre-execution hook if provided (e.g., for confirmation)
        if pre_execute_hook:
            approved = await pre_execute_hook(thought.tool_name, thought.tool_parameters or {})
            if not approved:
                observation = "Tool execution cancelled by agent policy or user."
                message_history.append(Message(role="user", content=f"Observation: {observation}"))
                request._tool_calls_log.append({
                    "tool": thought.tool_name,
                    "params": thought.tool_parameters,
                    "success": False,
                    "error": "Cancelled"
                })
                continue

        call_req = ToolCallRequest(
            tool_name=thought.tool_name,
            parameters=thought.tool_parameters or {},
            session_id=request.session_id,
            user_id=request.user_id,
            step_number=step_count,
            trace_id=trace_id,
            allowed_tool_names=request.allowed_tools,
        )

        log.info("loop.tool_call", tool=thought.tool_name,
                 step=step_count, trace_id=trace_id)

        # Check tool cache first
        cache_key = TTLCache._make_key(call_req.tool_name, call_req.parameters)
        cached_output = await tool_cache.get(cache_key)

        if cached_output is not None:
            log.info("tool.cache_hit", tool=call_req.tool_name, trace_id=trace_id)
            observation = json.dumps(cached_output)
            request._tool_calls_log.append({
                "step":       step_count,
                "tool":       call_req.tool_name,
                "success":    True,
                "latency_ms": 0,
                "error_code": None,
                "from_cache": True,
            })
            guard.record(Step(
                tool_name=call_req.tool_name,
                params_hash=hash_params(call_req.parameters),
                tool_success=True,
                observation_length=len(observation),
            ))
        else:
            result = await tool_execute(call_req, max_retries=effective_retries)

            request._tool_calls_log.append({
                "step":       step_count,
                "tool":       call_req.tool_name,
                "success":    result.success,
                "latency_ms": result.latency_ms,
                "error_code": result.error.code if not result.success else None,
                "from_cache": False,
            })

            if result.success:
                observation = json.dumps(result.output)
                # Cache successful tool output
                await tool_cache.set(cache_key, result.output,
                                     ttl=settings.tool_cache_ttl)
            else:
                observation = (f"Tool '{call_req.tool_name}' failed: {result.error.message}. "
                               + ("Try a different approach." if not result.error.retryable
                                  else "Retries exhausted."))

            guard.record(Step(
                tool_name=call_req.tool_name,
                params_hash=hash_params(call_req.parameters),
                tool_success=result.success,
                observation_length=len(observation),
            ))

        if len(observation) > MAX_OBSERVATION_CHARS:
            observation = observation[:MAX_OBSERVATION_CHARS] + "... [truncated]"

        message_history.append(Message(
            role="user",
            content=f"<observation>{observation}</observation>"
        ))

        await _persist_session_snapshot(request, message_history)


def _partial_answer(history: list[Message]) -> str:
    for msg in reversed(history):
        if msg.role == "assistant" and msg.content:
            return f"Task stopped early. Last reasoning: {msg.content[:300]}"
    return "Task stopped early — no partial result available."

async def run_orchestrated(request: TaskRequest,
                             message_history: list[Message],
                             start_time: float) -> LoopResult:
    """Entry point for the multi-agent orchestrated flow."""
    from orchestration.agents.definitions.orchestrator import OrchestratorAgent
    from orchestration.agents.base import AgentContext
    
    orchestrator = OrchestratorAgent()
    
    # Map TaskRequest to AgentContext
    context = AgentContext(
        session_id=request.session_id,
        user_id=request.user_id,
        memory_snapshot={"recent_history": [m.content for m in message_history[-5:]]},
        parent_trace_id=request.trace_id
    )
    
    agent_result = await orchestrator.run(request.user_input, context)
    
    # Sync tool calls back to request for observability
    request._tool_calls_log.clear()
    request._tool_calls_log.extend(agent_result.tool_calls)
    
    return LoopResult(
        answer=agent_result.output,
        exit_reason="completed" if agent_result.success else "failed",
        steps=agent_result.tool_calls_made,
        tool_calls_log=agent_result.tool_calls,
        agent_plan=getattr(agent_result, "agent_plan", [])
    )
