import json
import uuid
from datetime import datetime
from typing import Optional, Any
from models.database import get_db

class Goal:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id")
        self.user_id = kwargs.get("user_id")
        self.description = kwargs.get("description")
        self.status = kwargs.get("status")
        self.created_at = kwargs.get("created_at")
        self.deadline = kwargs.get("deadline")
        self.last_checked = kwargs.get("last_checked")
        self.metadata = json.loads(kwargs.get("metadata", "{}"))

async def init_goals_table():
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS goals (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            description  TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'active',
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            deadline     TEXT,
            last_checked TEXT,
            metadata     TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_goals_user ON goals(user_id);
    """)
    await db.commit()

async def create_goal(user_id: str, description: str, deadline: Optional[datetime] = None, metadata: dict = None):
    db = await get_db()
    goal_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO goals (id, user_id, description, deadline, metadata) VALUES (?, ?, ?, ?, ?)",
        (goal_id, user_id, description, deadline.isoformat() if deadline else None, json.dumps(metadata or {}))
    )
    await db.commit()
    return goal_id

async def list_active_goals(user_id: str):
    db = await get_db()
    async with db.execute("SELECT * FROM goals WHERE user_id = ? AND status = 'active'", (user_id,)) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def mark_complete(goal_id: str):
    db = await get_db()
    await db.execute("UPDATE goals SET status = 'completed' WHERE id = ?", (goal_id,))
    await db.commit()

async def update_progress(goal_id: str, note: str):
    db = await get_db()
    # We store the note in metadata or a separate progress log if needed.
    # For now, just update last_checked and append to metadata.
    async with db.execute("SELECT metadata FROM goals WHERE id = ?", (goal_id,)) as cursor:
        row = await cursor.fetchone()
        if not row: return
        meta = json.loads(row[0])
        history = meta.get("progress_history", [])
        history.append({"ts": datetime.utcnow().isoformat(), "note": note})
        meta["progress_history"] = history
        
        await db.execute(
            "UPDATE goals SET metadata = ?, last_checked = datetime('now') WHERE id = ?",
            (json.dumps(meta), goal_id)
        )
        await db.commit()

async def get_overdue_goals():
    db = await get_db()
    now = datetime.utcnow().isoformat()
    async with db.execute(
        "SELECT * FROM goals WHERE status = 'active' AND deadline IS NOT NULL AND deadline < ?", 
        (now,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
