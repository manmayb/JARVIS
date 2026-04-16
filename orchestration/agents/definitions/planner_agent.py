from orchestration.agents.base import BaseAgent, AgentContext, AgentResult
from core.logging import get_logger

log = get_logger(__name__)

class PlannerAgent(BaseAgent):
    """Specialist in time management, calendar events, and persistent goals."""

    def __init__(self):
        super().__init__(
            name="planner",
            description="Manages time, calendar events, and persistent goals",
            tools=["create_event", "list_events"]
        )

    async def run(self, task: str, context: AgentContext) -> AgentResult:
        """Execute planning task and update persistent goals."""
        result = await self._run_task(task, context)
        
        if result.success:
            await self._update_goal_progress(task)
            
        return result

    async def _update_goal_progress(self, task: str):
        """
        Cross-reference the completed task with the GoalStore.
        Note: GoalStore implementation follows in P4-4.
        """
        try:
            # Placeholder for actual GoalStore integration
            log.info("agent.planner.goal_check", topic=task[:50])
            # from models.goal_store import update_progress
            # await update_progress(topic=task)
        except Exception as e:
            log.warning("agent.planner.goal_update_failed", error=str(e))
