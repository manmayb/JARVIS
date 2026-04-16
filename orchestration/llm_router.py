"""LLM routing and caching layer.

Routes between Gemini Flash (fast/cheap) and Gemini Pro (strong) based on 
prompt token count and task type. Integrates the TTL cache from ``core.cache``
so that identical prompts within the cache window skip the API call entirely.
"""

import time
from functools import lru_cache
from google import genai
from google.genai import types

from core.config import settings
from core.errors import AgentError, ConfigurationError
from core.logging import get_logger
from core import tokenizer
from core.cache import llm_cache, TTLCache
from pydantic import BaseModel

log = get_logger(__name__)


class LLMResponse(BaseModel):
    content: str
    model_used: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    from_cache: bool = False


# Gemini 2.0 release family constants
FAST_MODEL   = "gemini-2.0-flash"
STRONG_MODEL = "gemini-2.0-pro-exp-02-05"


def _is_placeholder_api_key(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"", "your_key_here", "replace_me", "changeme"}


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key, http_options={'api_version': 'v1alpha'})


def _select_model(prompt_tokens: int, task_type: str) -> str:
    # Gemini Flash is extremely capable for its size; we reserve Pro for 
    # intensive analysis or very long context.
    if prompt_tokens > 15000 or task_type in ("research", "coding", "analysis"):
        return STRONG_MODEL
    return FAST_MODEL


def _transform_messages(messages: list[dict]) -> list[types.Content]:
    """Translate OpenAI/Anthropic message format to Google Gemini Content format."""
    gemini_messages = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        content = m.get("content", "")
        gemini_messages.append(
            types.Content(
                role=role,
                parts=[types.Part(text=content)]
            )
        )
    return gemini_messages


async def call(messages: list[dict], system: str,
               task_type: str = "general",
               trace_id: str = "") -> LLMResponse:
    if _is_placeholder_api_key(settings.gemini_api_key):
        raise ConfigurationError(
            "GEMINI_API_KEY is missing or still set to a placeholder value in .env"
        )

    # ── Token-accurate counting (Estimated) ──
    estimated_input = tokenizer.estimate(messages)
    model = _select_model(estimated_input, task_type)
    
    # ── Cache lookup ──
    cache_key = TTLCache._make_key(model, system, messages)
    cached = await llm_cache.get(cache_key)
    if cached is not None:
        log.info("llm.cache_hit", model=model, trace_id=trace_id)
        return LLMResponse(**cached, from_cache=True)

    start = time.monotonic()
    log.info("llm.call_start", model=model, trace_id=trace_id,
              prompt_tokens=estimated_input)

    try:
        # Transform messages to Gemini format
        contents = _transform_messages(messages)
        
        # Call Google Gemini API
        client = _get_client()
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=2048,
                temperature=0.4,
            )
        )
    except Exception as exc:
        log.error("llm.api_error", error=str(exc), trace_id=trace_id)
        raise AgentError(f"Gemini API error: {exc}") from exc

    latency = int((time.monotonic() - start) * 1000)
    
    # Extract text content (Gemini returns a GenerateContentResponse)
    content = ""
    if response.candidates and response.candidates[0].content.parts:
        content = response.candidates[0].content.parts[0].text or ""

    usage = response.usage_metadata
    tokens_in = usage.prompt_token_count or 0
    tokens_out = usage.candidates_token_count or 0

    log.info("llm.call_done", model=model, latency_ms=latency,
             tokens_in=tokens_in, tokens_out=tokens_out,
             trace_id=trace_id)

    result = LLMResponse(content=content, model_used=model,
                         tokens_in=tokens_in, tokens_out=tokens_out,
                         latency_ms=latency)

    # Online token calibration (actual API usage vs local estimate)
    await tokenizer.record_actual(estimated_input, tokens_in)

    # ── Cache store (only cache successful responses) ──
    await llm_cache.set(cache_key, {
        "content": result.content,
        "model_used": result.model_used,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "latency_ms": result.latency_ms,
    }, ttl=settings.llm_cache_ttl)

    return result
