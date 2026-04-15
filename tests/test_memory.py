import pytest

from core.config import settings
from core.schemas import Message
from models import session_store
from models.database import close_db, init_db
from models.embeddings import recall, store_episode
from models.user_facts import delete_fact, get_fact, set_fact


@pytest.mark.asyncio
async def test_user_facts_sqlite_memory_db():
    original_db_path = settings.db_path
    settings.db_path = ":memory:"
    try:
        await init_db()

        await set_fact("u1", "preferred_language", "Python")
        value = await get_fact("u1", "preferred_language")
        assert value == "Python"

        deleted = await delete_fact("u1", "preferred_language")
        assert deleted is True
        assert await get_fact("u1", "preferred_language") is None
    finally:
        await close_db()
        settings.db_path = original_db_path


@pytest.mark.asyncio
async def test_session_store_save_and_load_serialization():
    original_db_path = settings.db_path
    settings.db_path = ":memory:"
    try:
        await init_db()

        payload = {
            "session_id": "sess-1",
            "messages": [
                Message(role="user", content="hello"),
                Message(role="assistant", content="hi"),
            ],
            "tool_calls_log": [{"tool": "calculator", "success": True}],
        }

        await session_store.save_session("sess-1", payload)
        loaded = await session_store.load_session("sess-1")

        assert loaded is not None
        assert loaded["session_id"] == "sess-1"
        assert loaded["messages"][0].role == "user"
        assert loaded["messages"][1].content == "hi"
        assert loaded["tool_calls_log"][0]["tool"] == "calculator"
    finally:
        await close_db()
        settings.db_path = original_db_path


@pytest.mark.asyncio
async def test_embeddings_semantic_ranking_in_memory():
    original_db_path = settings.db_path
    settings.db_path = ":memory:"
    try:
        await init_db()

        await store_episode("sess-a", "task-1", "User likes Python and FastAPI.")
        await store_episode("sess-a", "task-2", "User asked about gardening and plants.")

        results = await recall("python api project", top_k=2, min_score=0.0)

        assert len(results) >= 1
        assert results[0]["task_id"] in {"task-1", "task-2"}
        assert "summary" in results[0]
        assert "relevance" in results[0]
    finally:
        await close_db()
        settings.db_path = original_db_path
