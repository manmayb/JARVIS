import json
from datetime import datetime
from models.database import get_db
from core.schemas import Message
from core.observability import get_logger

log = get_logger(__name__)

# Hard cap on messages stored per session.
# Oldest messages are pruned automatically when exceeded.
MAX_MESSAGES_PER_SESSION = 100


async def get_or_create_session(session_id: str,
                                 user_id: str = "default_user") -> dict:
    """Return existing session or create a new one."""
    db = await get_db()
    async with db.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if row:
        return dict(row)

    await db.execute(
        "INSERT INTO sessions (session_id, user_id) VALUES (?, ?)",
        (session_id, user_id),
    )
    await db.commit()
    log.info("session.created", session_id=session_id, user_id=user_id)
    return {"session_id": session_id, "user_id": user_id, "message_count": 0}


async def append_message(session_id: str, message: Message) -> None:
    """Persist one message and increment the session message count."""
    db = await get_db()
    await db.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, message.role, message.content,
         message.timestamp.isoformat()),
    )
    await db.execute(
        "UPDATE sessions SET updated_at = datetime('now'), "
        "message_count = message_count + 1 WHERE session_id = ?",
        (session_id,),
    )
    await db.commit()

    # Prune oldest messages if over cap
    await _prune_if_needed(session_id)


async def get_session_history(session_id: str,
                               limit: int = 50) -> list[Message]:
    """Retrieve message history for a session in chronological order."""
    db = await get_db()
    async with db.execute(
        """
        SELECT role, content, timestamp FROM messages
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (session_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()

    # Reverse to chronological order
    messages = [
        Message(role=row["role"], content=row["content"],
                timestamp=datetime.fromisoformat(row["timestamp"]))
        for row in reversed(rows)
    ]
    return messages


async def save_task_result(task_id: str, session_id: str, trace_id: str,
                            user_input: str, final_answer: str, status: str,
                            steps_taken: int | None, tools_used: list[str],
                            duration_ms: int) -> None:
    """Save a completed task to the log."""
    db = await get_db()
    await db.execute(
        """
        INSERT OR REPLACE INTO task_log
        (task_id, session_id, trace_id, user_input, final_answer,
         status, steps_taken, tools_used, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, session_id, trace_id, user_input, final_answer,
         status, steps_taken, json.dumps(tools_used), duration_ms),
    )
    await db.commit()


async def get_session_tasks(session_id: str, limit: int = 20) -> list[dict]:
    """Retrieve task history for a session."""
    db = await get_db()
    async with db.execute(
        """
        SELECT task_id, trace_id, user_input, final_answer, status,
               steps_taken, tools_used, created_at, duration_ms
        FROM task_log
        WHERE session_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (session_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()

    results = []
    for row in rows:
        r = dict(row)
        r["tools_used"] = json.loads(r["tools_used"] or "[]")
        results.append(r)
    return results


async def _prune_if_needed(session_id: str) -> None:
    """Remove oldest messages if session exceeds MAX_MESSAGES_PER_SESSION."""
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
        count = row["cnt"]

    if count > MAX_MESSAGES_PER_SESSION:
        excess = count - MAX_MESSAGES_PER_SESSION
        await db.execute(
            """
            DELETE FROM messages WHERE id IN (
                SELECT id FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                LIMIT ?
            )
            """,
            (session_id, excess),
        )
        await db.commit()
        log.info("session.pruned", session_id=session_id, removed=excess)
