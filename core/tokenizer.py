"""Token counting utilities.

Uses tiktoken when available for accurate counts, otherwise falls back
to a character-based approximation (len / 4).
"""

from __future__ import annotations

from functools import lru_cache
from core.observability import get_logger

log = get_logger(__name__)

_FALLBACK_CHARS_PER_TOKEN = 4

try:
    import tiktoken                        # type: ignore[import-untyped]
    _HAS_TIKTOKEN = True
except ImportError:
    _HAS_TIKTOKEN = False
    log.warning("tokenizer.fallback",
                reason="tiktoken not installed — using character approximation")


@lru_cache(maxsize=1)
def _get_encoder():
    """Return the cl100k_base encoder used by Claude-family models."""
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Return the number of tokens in *text*."""
    if _HAS_TIKTOKEN:
        return len(_get_encoder().encode(text))
    return max(1, len(text) // _FALLBACK_CHARS_PER_TOKEN)


def count_messages_tokens(messages: list[dict]) -> int:
    """Count tokens across a list of ``{"role": ..., "content": ...}`` dicts."""
    total = 0
    for m in messages:
        # ~4 tokens overhead per message for role + separators
        total += 4 + count_tokens(m.get("content", ""))
    return total
