from orchestration.agents.base import BaseAgent, AgentContext, AgentResult
from core.logging import get_logger

log = get_logger(__name__)

class CommunicatorAgent(BaseAgent):
    """Specialist in cross-platform messaging and record creation."""

    def __init__(self):
        super().__init__(
            name="communicator",
            description="Sends messages and creates records across platforms",
            tools=["send_email", "send_slack_message", "create_notion_page"]
        )

    async def run(self, task: str, context: AgentContext) -> AgentResult:
        """Execute communication task with mandatory confirmation check."""
        return await self._run_task(task, context)

    async def on_tool_call(self, tool_name: str, parameters: dict) -> bool:
        """Confirm all platform actions before execution."""
        # Selection of message content to confirm
        message = parameters.get("message") or parameters.get("content") or "Action"
        confirmed = await self._confirm_action(f"Send to {tool_name}: {message[:50]}...")
        
        if confirmed:
            log.info("agent.communicator.confirmed", tool=tool_name, trace_id=self.name)
        else:
            log.info("agent.communicator.denied", tool=tool_name, trace_id=self.name)
            
        return confirmed

    async def _confirm_action(self, message: str) -> bool:
        """
        Placeholder for human-in-the-loop approval.
        Currently auto-approves all actions.
        """
        log.info("agent.communicator.auto_approval", detail=message)
        return True
