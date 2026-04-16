from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Optional, Any
import time

from core.logging import get_logger

log = get_logger(__name__)

@dataclass
class AgentContext:
    session_id: str
    user_id: str
    memory_snapshot: dict[str, Any]
    parent_trace_id: str

@dataclass
class AgentResult:
    output: str
    tool_calls_made: int
    tokens_used: int
    sub_agent_name: str
    success: bool
    tool_calls: list[dict[str, Any]]
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable dictionary representation."""
        return asdict(self)

class BaseAgent(ABC):
    """Abstract base class for all specialist agents in the JARVIS V4 ecosystem."""

    def __init__(self, name: str, description: str, tools: list[str]):
        self.name = name
        self.description = description
        self.tools = tools

    @abstractmethod
    async def run(self, task: str, context: AgentContext) -> AgentResult:
        """Execute the assigned task using the agent's specialist logic and tools."""
        pass

    async def on_tool_call(self, tool_name: str, parameters: dict) -> bool:
        """
        Optional hook called before every tool execution.
        Return True to allow, False to cancel.
        """
        return True

    async def _run_task(self, task: str, context: AgentContext) -> AgentResult:
        """Helper to run the core ReAct loop with this agent's scoped tools."""
        from core.schemas import TaskRequest
        from orchestration.react_loop import run as run_loop
        
        start_time = time.monotonic()
        req = TaskRequest(
            user_input=task,
            session_id=context.session_id,
            user_id=context.user_id,
            trace_id=context.parent_trace_id,
            allowed_tools=self.tools
        )
        
        try:
            # We start with empty history for sub-agent tasks 
            loop_result = await run_loop(
                req, 
                message_history=[], 
                start_time=time.monotonic(),
                pre_execute_hook=self.on_tool_call
            )
            
            result = AgentResult(
                output=loop_result.answer,
                tool_calls_made=len(loop_result.tool_calls_log),
                tokens_used=0, # Token extraction would be added in next stage
                sub_agent_name=self.name,
                success=loop_result.exit_reason == "completed",
                tool_calls=loop_result.tool_calls_log,
                error=None if loop_result.exit_reason == "completed" else loop_result.exit_reason
            )
            self._log_execution(task, start_time, result)
            return result
        except Exception as e:
            result = AgentResult(
                output="",
                tool_calls_made=0,
                tokens_used=0,
                sub_agent_name=self.name,
                success=False,
                tool_calls=[],
                error=str(e)
            )
            self._log_execution(task, start_time, result)
            return result

    def _log_execution(self, task: str, start_time: float, result: AgentResult):
        """Standardized logging for agent entry/exit."""
        duration_ms = int((time.monotonic() - start_time) * 1000)
        log.info(
            "agent.execution.complete",
            agent=self.name,
            task=task[:80],
            duration_ms=duration_ms,
            success=result.success,
            tool_calls=result.tool_calls_made
        )
