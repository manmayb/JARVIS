from core.schemas import Message

SOFT_LIMIT = 12_000
HARD_LIMIT = 20_000
MIN_TAIL   = 6

def truncate_history(messages: list[Message]) -> tuple[list[Message], bool]:
    if not messages:
        return messages, False
    total = sum(len(m.content) for m in messages)
    if total <= SOFT_LIMIT:
        return messages, False
    system = messages[0]
    rest   = messages[1:]
    tail   = rest[-MIN_TAIL:] if len(rest) >= MIN_TAIL else rest
    middle = rest[:-MIN_TAIL] if len(rest) > MIN_TAIL else []
    tail_chars  = sum(len(m.content) for m in tail)
    budget      = SOFT_LIMIT - len(system.content) - tail_chars
    kept_middle = []
    for msg in reversed(middle):
        if len(msg.content) <= budget:
            kept_middle.insert(0, msg)
            budget -= len(msg.content)
    result = [system] + kept_middle + tail
    total  = sum(len(m.content) for m in result)
    if total > HARD_LIMIT and len(result) > 2:
        overflow  = total - HARD_LIMIT
        old       = result[1]
        result[1] = Message(role=old.role,
                            content="[truncated]\n" + old.content[overflow + 12:])
    return result, True

def truncation_notice(dropped: int) -> Message:
    return Message(
        role="user",
        content=(
            f"[System note: {dropped} earlier messages were removed to fit "
            f"the context window. Continue from the most recent messages below. "
            f"Do not reference events you cannot see in the current context.]"
        )
    )
