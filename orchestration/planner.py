"""Task planner — decomposes complex goals into a directed acyclic graph (DAG)
of sub-tasks that are each executed via the standard ReAct loop.

The planner itself is an LLM call that produces a JSON plan.  Simple
queries (< 30 words, no "and"/"then" chaining) skip planning entirely
and go straight to the ReAct loop.
"""

from __future__ import annotations

import json, uuid
from typing import Optional
from pydantic import BaseModel, Field
from core.schemas import TaskRequest, TaskResult, Message
from core.observability import get_logger
from core.config import settings

log = get_logger(__name__)


# ── Schema ──────────────────────────────────────────────────────────

class SubTask(BaseModel):
    id: str = Field(default_factory=lambda: f"sub_{uuid.uuid4().hex[:6]}")
    description: str
    depends_on: list[str] = []
    status: str = "pending"    # pending | running | completed | failed
    result: Optional[str] = None


class Plan(BaseModel):
    goal: str
    subtasks: list[SubTask] = []
    is_simple: bool = False   # True → skip decomposition, run directly


# ── Heuristic: should we even plan? ─────────────────────────────────

_COMPLEX_MARKERS = {"and then", "first ", "after that", "finally ",
                    "step 1", "multi-step", "followed by"}


def needs_planning(text: str) -> bool:
    """Return True if *text* looks complex enough to benefit from planning."""
    words = text.split()
    if len(words) < 15:
        return False
    lower = text.lower()
    return any(m in lower for m in _COMPLEX_MARKERS)


# ── Plan generation via LLM ─────────────────────────────────────────

_PLAN_SYSTEM = """You are a task planner. Given a complex user goal, break it
into a minimal list of independent sub-tasks.

Respond with ONLY valid JSON:
{
  "subtasks": [
    {"description": "...", "depends_on": []},
    {"description": "...", "depends_on": ["sub_0"]}
  ]
}

Rules:
- Each sub-task must be self-contained enough for an AI agent to complete alone.
- Use depends_on to express ordering (reference earlier subtask ids: sub_0, sub_1, …).
- Keep the list as short as possible. Most goals need 2-4 steps.
- Never include meta-instructions about yourself.
"""


async def generate_plan(goal: str, trace_id: str = "") -> Plan:
    """Use the LLM to decompose *goal* into a Plan."""
    if not needs_planning(goal):
        return Plan(goal=goal, is_simple=True)

    from orchestration.llm_router import call as llm_call

    messages = [{"role": "user", "content": goal}]
    resp = await llm_call(messages, _PLAN_SYSTEM,
                          task_type="analysis", trace_id=trace_id)

    try:
        data = json.loads(resp.content)
        subtasks = []
        for i, st in enumerate(data.get("subtasks", [])):
            subtasks.append(SubTask(
                id=f"sub_{i}",
                description=st["description"],
                depends_on=st.get("depends_on", []),
            ))
        plan = Plan(goal=goal, subtasks=subtasks)
        log.info("planner.generated", steps=len(subtasks), trace_id=trace_id)
        return plan
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log.warning("planner.parse_failed", error=str(exc), trace_id=trace_id)
        return Plan(goal=goal, is_simple=True)


# ── Plan executor ────────────────────────────────────────────────────

async def execute_plan(plan: Plan, request: TaskRequest,
                       message_history: list[Message],
                       start_time: float) -> TaskResult:
    """Execute all subtasks in dependency order, collecting results."""
    from orchestration.react_loop import run as run_loop

    results_map: dict[str, str] = {}
    combined_tool_log: list[dict] = []
    total_steps = 0

    # Topological execution: process subtasks in order, respecting deps
    remaining = list(plan.subtasks)
    while remaining:
        # Find subtasks whose dependencies are all completed
        ready = [st for st in remaining
                 if all(d in results_map for d in st.depends_on)]

        if not ready:
            log.error("planner.deadlock", remaining=[s.id for s in remaining],
                      trace_id=request.trace_id)
            break

        for subtask in ready:
            subtask.status = "running"
            # Build context: inject prior subtask results
            context_parts = [f"Goal: {plan.goal}"]
            for dep_id in subtask.depends_on:
                context_parts.append(
                    f"[Result of step {dep_id}]: {results_map[dep_id][:500]}")
            context_parts.append(f"Current step: {subtask.description}")
            enriched_input = "\n".join(context_parts)

            sub_request = TaskRequest(
                user_input=enriched_input,
                session_id=request.session_id,
                user_id=request.user_id,
                trace_id=request.trace_id,
            )
            sub_history = message_history + [
                Message(role="user", content=enriched_input)
            ]

            result = await run_loop(sub_request, sub_history, start_time)
            subtask.result = result.answer
            subtask.status = "completed"
            results_map[subtask.id] = result.answer
            combined_tool_log.extend(result.tool_calls_log)
            total_steps += result.steps
            log.info("planner.subtask_done", subtask_id=subtask.id,
                     steps=result.steps, trace_id=request.trace_id)

        remaining = [s for s in remaining if s.status != "completed"]

    # Synthesise final answer from all subtask results
    final_parts = [f"**{st.description}**: {st.result}"
                   for st in plan.subtasks if st.result]
    final_answer = "\n\n".join(final_parts) if final_parts else "Plan execution failed."

    return TaskResult(
        task_id=request.task_id,
        final_answer=final_answer,
        status="completed",
        steps_taken=total_steps,
        tool_calls_log=combined_tool_log,
        trace_id=request.trace_id,
    )
