import json
from core.schemas import Message, TaskRequest
from tools.registry import list_tools
from orchestration.message_window import truncate_history, truncation_notice
from core.observability import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT = """You are Jarvis, a capable AI agent with access to tools.

You MUST respond with valid JSON — no other text outside the JSON object.
Schema:
{
  "thought": "<your reasoning>",
  "action_type": "tool_call" | "final_answer",
  "tool_name": "<tool name>" | null,
  "tool_parameters": {...} | null,
  "final_answer": "<answer>" | null
}

Rules:
- Think step by step before acting.
- Use tools when you need current information or to perform an action.
- When you have enough information, set action_type to final_answer.
- final_answer must be a complete, helpful response to the user.
- Never set both tool_name and final_answer in the same response.
"""

def build(request: TaskRequest,
          message_history: list[Message]) -> tuple[str, list[dict]]:
    tools     = list_tools()
    tool_desc = _format_tools(tools)
    system    = SYSTEM_PROMPT + f"\n## Available tools\n{tool_desc}"

    trimmed, was_truncated = truncate_history(message_history)
    if was_truncated:
        dropped = len(message_history) - len(trimmed)
        trimmed.insert(1, truncation_notice(dropped))
        log.info("context.truncated", dropped=dropped, trace_id=request.trace_id)

    messages = [{"role": m.role, "content": m.content}
                for m in trimmed if m.role in ("user", "assistant")]
    return system, messages

def _format_tools(tools) -> str:
    lines = []
    for t in tools:
        params = json.dumps(t.parameters.get("properties", {}), indent=2)
        lines.append(f"- **{t.name}** ({t.permission_tier}): {t.description}\n"
                     f"  Parameters: {params}")
    return "\n\n".join(lines)
