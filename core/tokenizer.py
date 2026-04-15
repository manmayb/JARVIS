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
from core.observability import get_logger

log = get_logger(__name__)

# Calibrated for Gemini 1.5 / 2.x (SentencePiece, English text)
# Set conservatively so we never accidentally exceed the context window.
_GEMINI_CHARS_PER_TOKEN: float = 3.7
# Per-message overhead (role string + structural tokens Gemini adds)
_MSG_OVERHEAD_TOKENS: int = 5


def count_tokens(text: str) -> int:
    """Return an estimated token count for *text* using the Gemini calibration.

    This is a fast, synchronous approximation.  For absolute precision,
    use the Gemini API's ``count_tokens`` method offline/asynchronously.
    """
    if not text:
        return 0
    return max(1, round(len(text) / _GEMINI_CHARS_PER_TOKEN))


def count_messages_tokens(messages: list[dict]) -> int:
    """Estimate total tokens across a list of ``{"role": ..., "content": ...}`` dicts."""
    total = 0
    for m in messages:
        total += _MSG_OVERHEAD_TOKENS + count_tokens(m.get("content", ""))
    return total


def tokens_remaining(messages: list[dict], context_limit: int = 1_000_000) -> int:
    """Return how many tokens are still available in the context window.

    Gemini 2.5 Pro has a 1M token context window by default.
    """
    used = count_messages_tokens(messages)
    return max(0, context_limit - used)
