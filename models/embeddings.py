"""Episodic memory — lightweight vector similarity search over past tasks.

Uses TF-IDF-style hashing for embeddings (zero external dependencies).
Vectors are stored in SQLite as JSON arrays. On retrieval, cosine similarity
is computed in-process with the standard library only (no numpy required).

Upgrading to a real embedding model (e.g. sentence-transformers) later only
requires swapping out ``_embed()``.
"""

from __future__ import annotations

import hashlib, json, math, re
from collections import Counter
from models.database import get_db
from core.observability import get_logger

log = get_logger(__name__)

# ------------------------------------------------------------------
# Embedding via feature-hashing (fast, zero-dependency, good-enough)
# ------------------------------------------------------------------

_DIM = 128  # embedding dimensionality (small — stored in SQLite JSON)


def _tokenize(text: str) -> list[str]:
    """Lowercase split + bigram generation."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    bigrams = [f"{words[i]}_{words[i+1]}" for i in range(len(words) - 1)]
    return words + bigrams


def _embed(text: str) -> list[float]:
    """Return a unit-length feature-hash vector of *text*."""
    vec = [0.0] * _DIM
    for token in _tokenize(text):
        idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % _DIM
        sign = 1 if int(hashlib.sha1(token.encode()).hexdigest(), 16) % 2 == 0 else -1
        vec[idx] += sign
    # L2 normalise
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ------------------------------------------------------------------
# Database helpers
# ------------------------------------------------------------------

_MIGRATION = """
CREATE TABLE IF NOT EXISTS episodic_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    task_id     TEXT NOT NULL UNIQUE,
    summary     TEXT NOT NULL,
    embedding   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_episodic_session ON episodic_memory(session_id);
"""


async def init_episodic_table() -> None:
    db = await get_db()
    await db.executescript(_MIGRATION)
    await db.commit()
    log.info("episodic.table_ready")


async def store_episode(session_id: str, task_id: str, summary: str) -> None:
    """Embed and persist a completed-task summary."""
    vec = _embed(summary)
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO episodic_memory "
        "(session_id, task_id, summary, embedding) VALUES (?, ?, ?, ?)",
        (session_id, task_id, summary, json.dumps(vec)),
    )
    await db.commit()
    log.info("episodic.stored", task_id=task_id)


async def recall(query: str, top_k: int = 3,
                 min_score: float = 0.15) -> list[dict]:
    """Return the *top_k* most relevant past episodes for *query*."""
    qvec = _embed(query)
    db = await get_db()
    async with db.execute(
        "SELECT task_id, session_id, summary, embedding FROM episodic_memory"
    ) as cursor:
        rows = await cursor.fetchall()

    scored: list[tuple[float, dict]] = []
    for row in rows:
        stored_vec = json.loads(row["embedding"])
        score = _cosine(qvec, stored_vec)
        if score >= min_score:
            scored.append((score, {
                "task_id": row["task_id"],
                "session_id": row["session_id"],
                "summary": row["summary"],
                "relevance": round(score, 4),
            }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]
