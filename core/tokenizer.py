"""Token counting utilities.

Gemini does not expose a public tokenizer library. This module uses a
two-level strategy:

1. **Primary** — `google.generativeai.count_tokens()` is the ground-truth source
   but requires an API call, so it is only used for calibration, not in the
   critical path of every request.

2. **Fast path** — A character-ratio approximation calibrated specifically
   to Gemini's SentencePiece tokenizer.  Empirically, Gemini 1.5/2.x
   tokenizes English prose at roughly 3.7 characters per token (vs. ~4.0 for
   GPT-4).  Tool schemas (JSON) compress more aggressively: ~2.8 chars/token.
   We use 3.7 as the conservative default so we *undercount* tokens, keeping
   us safely inside the window.

Note: tiktoken's `cl100k_base` (GPT-4 / Claude) was previously used here but
it measures *different* vocabulary units from Gemini's SentencePiece model and
was removed to avoid misleading truncation decisions.
"""

from __future__ import annotations
import asyncio
from core.observability import get_logger

log = get_logger(__name__)

# Calibrated for Gemini 1.5 / 2.x (SentencePiece, English text)
# Set conservatively so we never accidentally exceed the context window.
_GEMINI_CHARS_PER_TOKEN: float = 3.7
# Per-message overhead (role string + structural tokens Gemini adds)
_MSG_OVERHEAD_TOKENS: int = 5

# Online calibration state (EMA)
correction_factor: float = 1.0
_calibration_updates: int = 0
_last_estimated_input: int = 0
_last_actual_input: int = 0
_calibration_lock = asyncio.Lock()


def count_tokens(text: str) -> int:
    """Return an estimated token count for *text* using the Gemini calibration.

    This is a fast, synchronous approximation.  For absolute precision,
    use the Gemini API's ``count_tokens`` method offline/asynchronously.
    """
    if not text:
        return 0
    return max(1, round((len(text) / _GEMINI_CHARS_PER_TOKEN) * correction_factor))


def count_messages_tokens(messages: list[dict]) -> int:
    """Estimate total tokens across a list of ``{"role": ..., "content": ...}`` dicts."""
    total = 0
    for m in messages:
        total += _MSG_OVERHEAD_TOKENS + count_tokens(m.get("content", ""))
    return total


def estimate(messages: list[dict]) -> int:
    """Alias for the calibrated input token estimate."""
    return count_messages_tokens(messages)


async def record_actual(estimated_input: int, actual_input: int) -> None:
    """Update calibration factor using EMA on actual model usage.

    Update rule: ``new = 0.9 * old + 0.1 * (actual / estimated)`` and clamp to
    ``[0.5, 2.0]``.
    """
    global correction_factor
    global _calibration_updates
    global _last_estimated_input
    global _last_actual_input

    if estimated_input <= 0 or actual_input <= 0:
        return

    ratio = actual_input / estimated_input
    async with _calibration_lock:
        updated = 0.9 * correction_factor + 0.1 * ratio
        correction_factor = max(0.5, min(2.0, updated))
        _calibration_updates += 1
        _last_estimated_input = estimated_input
        _last_actual_input = actual_input


def get_calibration_stats() -> dict:
    return {
        "correction_factor": round(correction_factor, 6),
        "updates": _calibration_updates,
        "last_estimated_input": _last_estimated_input,
        "last_actual_input": _last_actual_input,
    }


def tokens_remaining(messages: list[dict], context_limit: int = 1_000_000) -> int:
    """Return how many tokens are still available in the context window.

    Gemini 2.5 Pro has a 1M token context window by default.
    """
    used = count_messages_tokens(messages)
    return max(0, context_limit - used)
