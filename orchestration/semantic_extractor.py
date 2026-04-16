import asyncio
import json
from core.logging import get_logger
from core.config import settings
from core.schemas import Message
from models.user_facts import set_fact
from orchestration.llm_router import call as llm_call
from core.llm_parser import _extract

log = get_logger(__name__)

EXTRACTION_PROMPT = """You are a memory extraction background process.
Analyze the recent conversation and extract any NEW persistent facts about the user.
Examples of facts: User prefers Python, User uses macOS, User has a dog named Rex.
Output MUST be a valid JSON array of objects with "key" and "value".
Example:
[
  {"key": "preferred_language", "value": "Python"},
  {"key": "os", "value": "macOS"}
]
If there are no new persistent facts to extract, return an empty array [].
Do NOT wrap the output in markdown fences, just return raw JSON array.
"""


async def extract_facts(user_message: str, assistant_reply: str, trace_id: str) -> list[dict]:
    """Extract candidate facts from a single user/assistant exchange."""
    messages_payload = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_reply},
    ]
    resp = await llm_call(
        messages=messages_payload,
        system=EXTRACTION_PROMPT,
        task_type="analysis",
        trace_id=trace_id,
    )

    raw_json = _extract(resp.content)
    facts = json.loads(raw_json)
    if not isinstance(facts, list):
        return []
    return [fact for fact in facts if isinstance(fact, dict) and "key" in fact and "value" in fact]


async def save_facts(user_id: str, facts: list[dict]) -> int:
    """Persist extracted facts and return the number saved."""
    saved = 0
    for fact in facts:
        await set_fact(user_id, fact["key"], str(fact["value"]), source="auto_extraction")
        saved += 1
    return saved

async def extract_and_store_facts(user_id: str, message_history: list[Message], trace_id: str) -> None:
    if not settings.enable_semantic_memory:
        return

    # Look at the last up to 4 messages to catch context + new facts
    recent = message_history[-4:]
    messages_payload = [{"role": m.role, "content": m.content} for m in recent if m.role in ("user", "assistant")]
    
    # If there are no user messages, skip
    if not any(m["role"] == "user" for m in messages_payload):
        return

    try:
        assistant_reply = next((m["content"] for m in reversed(messages_payload) if m["role"] == "assistant"), "")
        user_msg = next((m["content"] for m in reversed(messages_payload) if m["role"] == "user"), "")
        facts = await extract_facts(user_msg, assistant_reply, trace_id)
        await save_facts(user_id, facts)
    except Exception as exc:
        log.warning("semantic_extraction.error", error=str(exc), trace_id=trace_id)

def schedule_fact_extraction(user_id: str, message_history: list[Message], trace_id: str) -> None:
    """Fire and forget wrapper to avoid blocking the main task runner."""
    asyncio.create_task(extract_and_store_facts(user_id, message_history, trace_id))
