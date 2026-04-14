import aiosqlite
from core.config import settings
from core.observability import get_logger

log = get_logger(__name__)

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


async def init_db() -> None:
    global _db
    _db = await aiosqlite.connect(settings.db_path)
    _db.row_factory = aiosqlite.Row
    await _run_migrations(_db)
    log.info("db.initialized", path=settings.db_path)


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        log.info("db.closed")


async def _run_migrations(db: aiosqlite.Connection) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id    TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL DEFAULT 'default_user',
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
            message_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );

        CREATE TABLE IF NOT EXISTS task_log (
            task_id      TEXT PRIMARY KEY,
            session_id   TEXT NOT NULL,
            trace_id     TEXT NOT NULL,
            user_input   TEXT NOT NULL,
            final_answer TEXT,
            status       TEXT NOT NULL,
            steps_taken  INTEGER,
            tools_used   TEXT,
            duration_ms  INTEGER,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_task_log_session
            ON task_log(session_id);
        CREATE INDEX IF NOT EXISTS idx_task_log_trace
            ON task_log(trace_id);
    """)
    await db.commit()
