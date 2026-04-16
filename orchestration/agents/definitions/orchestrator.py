import asyncio, json, time
from typing import Any
from orchestration.agents.base import BaseAgent, AgentContext, AgentResult
from orchestration.agents.registry import registry
from orchestration.llm_router import call as llm_call
from core.logging import get_logger

log = get_logger(__name__)

ROUTING_PROMPT = """
You are the JARVIS orchestrator. Given the user message and available agents,
produce a JSON array describing which agents to invoke and with what task.
Only invoke agents that are necessary. If a single agent suffices, return one item.

Available agents: {agent_list}
User message: {user_message}
Session context: {context_summary}

Respond ONLY with a valid JSON array. No markdown. No explanation.
Example: [{"agent": "researcher", "task": "find recent news about X"}]
"""

SYNTHESIS_PROMPT = """
You are the JARVIS synthesis engine. Your goal is to combine the results from several
specialist agents into a single, cohesive, and helpful response for the user.

User original request: {user_message}
Agent outputs:
{agent_outputs}

Instructions:
- Be concise but thorough.
- Directly answer the user's question using the provided agent data.
- Attributes information to the relevant specialist where it adds clarity.
- If an agent failed, acknowledge it gracefully.
"""

class OrchestratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="orchestrator",
            description="Routes tasks to specialist agents and assembles replies",
            tools=[] # No direct tools
        )

    async def run(self, task: str, context: AgentContext) -> AgentResult:
        start_time = time.monotonic()
        
        # 1. Routing phase with 5s timeout fallback
        try:
            plan = await asyncio.wait_for(self._create_plan(task, context), timeout=5.0)
        except (asyncio.TimeoutError, Exception) as e:
            log.warning("orchestrator.plan_failed", error=str(e))
            plan = [{"agent": "researcher", "task": task}]

        plan = plan[:4] # Truncate to first 4 agents
        
        # 2. Execution phase (Sequential to support data flow)
        agent_results = []
        accumulated_context = context.memory_snapshot.copy()
        
        for step in plan:
            agent_name = step.get("agent")
            sub_task = step.get("task")
            agent = registry.get(agent_name)
            
            if not agent:
                log.warning("orchestrator.agent_not_found", name=agent_name)
                continue
                
            # Run agent and update context
            res = await agent.run(sub_task, context)
            agent_results.append(res)
            accumulated_context[f"last_result_{agent_name}"] = res.output
            
        # 3. Synthesis phase
        final_response = await self._synthesize(task, agent_results)
        
        # Construct summary result
        total_tools = sum(r.tool_calls_made for r in agent_results)
        success = any(r.success for r in agent_results)
        
        res = AgentResult(
            output=final_response,
            tool_calls_made=total_tools,
            tokens_used=0,
            sub_agent_name="orchestrator",
            success=success,
            tool_calls=[c for r in agent_results for c in r.tool_calls],
            error=None
        )
        
        # Store plan in dict for Pydantic serialization later
        res_dict = res.to_dict()
        res_dict["agent_plan"] = [{"agent": p["agent"], "task": p["task"], "success": agent_results[i].success if i < len(agent_results) else False} for i, p in enumerate(plan)]
        
        self._log_execution(task, start_time, res)
        return res

    async def _create_plan(self, task: str, context: AgentContext) -> list[dict]:
        agent_list = json.dumps(registry.list_agents(), indent=2)
        prompt = ROUTING_PROMPT.format(
            agent_list=agent_list,
            user_message=task,
            context_summary=str(context.memory_snapshot.get("recent_history", ""))
        )
        
        resp = await llm_call(prompt, model_preference="fast")
        try:
            # Simple cleanup for potential JSON formatting issues
            clean_json = resp.content.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json.split("```json")[1].split("```")[0].strip()
            return json.loads(clean_json)
        except:
            return [{"agent": "researcher", "task": task}]

    async def _synthesize(self, task: str, results: list[AgentResult]) -> str:
        agent_outputs = "\n".join([f"Agent {r.sub_agent_name}: {r.output}" for r in results])
        prompt = SYNTHESIS_PROMPT.format(user_message=task, agent_outputs=agent_outputs)
        resp = await llm_call(prompt, model_preference="strong")
        return resp.content
