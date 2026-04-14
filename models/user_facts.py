"""Semantic memory — persistent key-value fact store per user.

Stores user preferences and facts extracted during conversations
(e.g. "preferred_language" → "Python", "os" → "macOS").
"""

from __future__ import annotations

import json
from models.database import get_db
from core.observability import get_logger

log = get_logger(__name__)

_MIGRATION = """
CREATE TABLE IF NOT EXISTS user_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source     TEXT NOT NULL DEFAULT 'inferred',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, key)
);
CREATE INDEX IF NOT EXISTS idx_user_facts_user ON user_facts(user_id);
"""


async def init_facts_table() -> None:
    db = await get_db()
    await db.executescript(_MIGRATION)
    await db.commit()
    log.info("user_facts.table_ready")


async def set_fact(user_id: str, key: str, value: str,
                   confidence: float = 1.0, source: str = "inferred") -> None:
    """Upsert a user fact."""
    db = await get_db()
    await db.execute(
        """
        INSERT INTO user_facts (user_id, key, value, confidence, source, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(user_id, key) DO UPDATE SET
            value      = excluded.value,
            confidence = excluded.confidence,
            source     = excluded.source,
            updated_at = datetime('now')
        """,
        (user_id, key, value, confidence, source),
    )
    await db.commit()
    log.info("user_facts.set", user_id=user_id, key=key)


async def get_fact(user_id: str, key: str) -> str | None:
    """Return a single fact value or None."""
    db = await get_db()
    async with db.execute(
        "SELECT value FROM user_facts WHERE user_id = ? AND key = ?",
        (user_id, key),
    ) as cur:
        row = await cur.fetchone()
    return row["value"] if row else None


async def get_all_facts(user_id: str) -> list[dict]:
    """Return all facts for a user."""
    db = await get_db()
    async with db.execute(
        "SELECT key, value, confidence, source, updated_at "
        "FROM user_facts WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_fact(user_id: str, key: str) -> bool:
    """Delete a fact. Returns True if a row was deleted."""
    db = await get_db()
    cur = await db.execute(
        "DELETE FROM user_facts WHERE user_id = ? AND key = ?",
        (user_id, key),
    )
    await db.commit()
    return cur.rowcount > 0
