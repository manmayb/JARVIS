"""LLM routing and caching layer.

Routes between Haiku (fast/cheap) and Sonnet (strong) based on prompt
token count and task type.  Integrates the TTL cache from ``core.cache``
so that identical prompts within the cache window skip the API call entirely.
"""

import anthropic, time
from functools import lru_cache
from core.config import settings
from core.errors import AgentError, ConfigurationError
from core.observability import get_logger
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


FAST_MODEL   = "claude-haiku-4-5-20251001"
STRONG_MODEL = "claude-sonnet-4-6"


def _is_placeholder_api_key(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"", "your_key_here", "replace_me", "changeme"}


@lru_cache(maxsize=1)
def _get_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def _select_model(prompt_tokens: int, task_type: str) -> str:
    if prompt_tokens > 2000 or task_type in ("research", "coding", "analysis"):
        return STRONG_MODEL
    return FAST_MODEL


async def call(messages: list[dict], system: str,
               task_type: str = "general",
               trace_id: str = "") -> LLMResponse:
    if _is_placeholder_api_key(settings.anthropic_api_key):
        raise ConfigurationError(
            "ANTHROPIC_API_KEY is missing or still set to a placeholder value in .env"
        )

    # ── Token-accurate counting ──
    estimated_input = tokenizer.estimate(messages)
    prompt_tokens = estimated_input
    model         = _select_model(prompt_tokens, task_type)
    
    # ── Cache lookup ──
    cache_key = TTLCache._make_key(model, system, messages)
    cached = await llm_cache.get(cache_key)
    if cached is not None:
        log.info("llm.cache_hit", model=model, trace_id=trace_id)
        return LLMResponse(**cached, from_cache=True)

    start = time.monotonic()
    log.info("llm.call_start", model=model, trace_id=trace_id,
             prompt_tokens=prompt_tokens)

    try:
        response = await _get_client().messages.create(
            model=model, max_tokens=1024,
            system=system, messages=messages,
        )
    except anthropic.AuthenticationError as exc:
        log.error("llm.auth_error", error=str(exc), trace_id=trace_id)
        raise ConfigurationError(
            "ANTHROPIC_API_KEY was rejected by Anthropic. Check the value in .env"
        ) from exc
    except anthropic.BadRequestError as exc:
        message = str(exc)
        log.error("llm.bad_request", error=message, trace_id=trace_id)
        if "credit balance is too low" in message.lower():
            raise ConfigurationError(
                "Anthropic account has insufficient credits. Add credits in billing and retry."
            ) from exc
        raise AgentError(f"Anthropic request rejected: {message}") from exc
    except anthropic.APIError as exc:
        log.error("llm.api_error", error=str(exc), trace_id=trace_id)
        raise AgentError(f"Anthropic API error: {exc}") from exc

    latency = int((time.monotonic() - start) * 1000)
    content = "".join(b.text for b in response.content if hasattr(b, "text"))

    log.info("llm.call_done", model=model, latency_ms=latency,
             tokens_in=response.usage.input_tokens,
             tokens_out=response.usage.output_tokens,
             trace_id=trace_id)

    result = LLMResponse(content=content, model_used=model,
                         tokens_in=response.usage.input_tokens,
                         tokens_out=response.usage.output_tokens,
                         latency_ms=latency)

    # Online token calibration (actual API usage vs local estimate)
    await tokenizer.record_actual(estimated_input, response.usage.input_tokens)

    # ── Cache store (only cache successful responses) ──
    await llm_cache.set(cache_key, {
        "content": result.content,
        "model_used": result.model_used,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "latency_ms": result.latency_ms,
    }, ttl=settings.llm_cache_ttl)

    return result
