from orchestration.agents.base import BaseAgent, AgentContext, AgentResult

class ResearcherAgent(BaseAgent):
    """Specialist in finding information from the web, documents, and memory."""

    def __init__(self):
        super().__init__(
            name="researcher",
            description="Finds information from the web, documents, and memory",
            tools=["web_search", "scrape_url", "read_file"]
        )

    async def run(self, task: str, context: AgentContext) -> AgentResult:
        """Execute research task with long-term memory grounding."""
        # Inject long-term memory from ChromaDB
        recalled_memory = await self._recall_memory(task)
        enriched_task = task
        if recalled_memory:
            enriched_task = f"recalled memory:\n{recalled_memory}\n\nTask: {task}"
            
        return await self._run_task(enriched_task, context)

    async def _recall_memory(self, task: str) -> str:
        """Perform similarity search against stored facts."""
        try:
            from models.embeddings import recall
            episodes = await recall(task, top_k=3)
            if not episodes:
                return ""
            
            lines = [f"- {ep['summary']}" for ep in episodes]
            return "\n".join(lines)
        except Exception:
            # Silently fail memory enrichment if sub-system is unavailable
            return ""
