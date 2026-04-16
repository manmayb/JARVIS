from orchestration.agents.base import BaseAgent, AgentContext, AgentResult
from core.state_backend import get_backend

class ExecutorAgent(BaseAgent):
    """Specialist in code execution and filesystem operations."""

    def __init__(self):
        super().__init__(
            name="executor",
            description="Runs code and operates on the filesystem",
            tools=["execute_python", "calculate", "read_file", "write_file", 
                   "list_directory", "delete_file"]
        )

    async def run(self, task: str, context: AgentContext) -> AgentResult:
        """Execute system tasks and log tool operations to shared state."""
        result = await self._run_task(task, context)
        
        # After loop completion, synchronize tool logs to session state
        if result.tool_calls:
            backend = await get_backend()
            log_key = f"exec_log:{context.session_id}"
            
            for call in result.tool_calls:
                summary = f"{call.get('tool')} -> {'SUCCESS' if call.get('success') else 'FAILED'}"
                await backend.append_to_list(log_key, summary)
                
        return result
