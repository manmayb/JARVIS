import re, json
from core.schemas import ThinkOutput
from core.logging import get_logger

log = get_logger(__name__)

_DEFAULTS = {
    "thought": "",
    "action_type": "final_answer",
    "tool_name": None,
    "tool_parameters": None,
    "final_answer": None,
}

def _extract(text: str) -> str:
    text = text.strip()
    if text.startswith("{"):
        return text
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return m.group(0)
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    return text

def _repair(text: str) -> str:
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = re.sub(r":\s*'([^']*)'", r': "\1"', text)
    return text

def parse_think_output(raw: str, trace_id: str) -> ThinkOutput:
    candidate = _extract(raw)
    for attempt, text in enumerate([candidate, _repair(candidate)]):
        try:
            data   = json.loads(text)
            merged = {**_DEFAULTS, **data}
            if merged["action_type"] not in ("tool_call", "final_answer"):
                raise ValueError(f"Bad action_type: {merged['action_type']}")
            if merged["action_type"] == "tool_call" and not merged.get("tool_name"):
                log.warning("parse.missing_tool_name",
                            trace_id=trace_id, snippet=raw[:200])
                merged["action_type"] = "final_answer"
                merged["final_answer"] = merged.get("thought") or "Could not determine action."
            return ThinkOutput(**merged)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            if attempt == 0:
                log.warning("parse.repair_triggered", trace_id=trace_id, error=str(e))
            else:
                log.error("parse.failed", trace_id=trace_id,
                          error=str(e), snippet=raw[:400])
    return ThinkOutput(
        thought="JSON parsing failed.",
        action_type="final_answer",
        tool_name=None,
        tool_parameters=None,
        final_answer=f"Formatting issue. Raw: {raw[:500]}",
    )
