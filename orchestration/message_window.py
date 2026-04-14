"""Message history truncation using token-accurate counting.

Uses ``core.tokenizer.count_tokens`` which delegates to tiktoken when
available, falling back to len/4 otherwise.  The algorithm is unchanged:
keep the first message + most recent MIN_TAIL messages, then greedily
add middle messages (most recent first) until the soft token limit is hit.
"""

from core.schemas import Message
from core.tokenizer import count_tokens

# Limits expressed in **tokens** (not characters)
SOFT_LIMIT = 3_200    # ~12 800 chars at 4 chars/token
HARD_LIMIT = 5_000
MIN_TAIL   = 6


def _msg_tokens(m: Message) -> int:
    return count_tokens(m.content)


def truncate_history(messages: list[Message]) -> tuple[list[Message], bool]:
    if not messages:
        return messages, False

    total = sum(_msg_tokens(m) for m in messages)
    if total <= SOFT_LIMIT:
        return messages, False

    system = messages[0]
    rest   = messages[1:]
    tail   = rest[-MIN_TAIL:] if len(rest) >= MIN_TAIL else rest
    middle = rest[:-MIN_TAIL] if len(rest) > MIN_TAIL else []

    tail_tokens   = sum(_msg_tokens(m) for m in tail)
    budget        = SOFT_LIMIT - _msg_tokens(system) - tail_tokens
    kept_middle: list[Message] = []

    for msg in reversed(middle):
        cost = _msg_tokens(msg)
        if cost <= budget:
            kept_middle.insert(0, msg)
            budget -= cost

    result = [system] + kept_middle + tail
    total  = sum(_msg_tokens(m) for m in result)

    if total > HARD_LIMIT and len(result) > 2:
        overflow = total - HARD_LIMIT
        old      = result[1]
        # Rough trim: 4 chars ≈ 1 token
        trim_chars = overflow * 4 + 12
        result[1] = Message(role=old.role,
                            content="[truncated]\n" + old.content[trim_chars:])

    return result, True


def truncation_notice(dropped: int) -> Message:
    return Message(
        role="user",
        content=(
            f"[System note: {dropped} earlier messages were removed to fit "
            f"the context window. Continue from the most recent messages below. "
            f"Do not reference events you cannot see in the current context.]"
        ),
    )
