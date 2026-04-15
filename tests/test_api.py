import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import app
from core.errors import AgentError


@pytest.mark.asyncio
async def test_chat_session_echo_and_trace_id_generation():
    mock_result = SimpleNamespace(
        final_answer="ok",
        status="completed",
        steps_taken=1,
        tool_calls_log=[{"tool": "calculator"}],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("api.routes.chat.run_task", new=AsyncMock(return_value=mock_result)):
            session_id = str(uuid.uuid4())
            response = await client.post("/chat", json={"message": "hello", "session_id": session_id})

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert body["response"] == "ok"
    assert body["tool_calls_made"] == 1
    uuid.UUID(body["trace_id"])


@pytest.mark.asyncio
async def test_chat_error_shape_value_error():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("api.routes.chat.run_task", new=AsyncMock(side_effect=ValueError("bad input"))):
            response = await client.post("/chat", json={"message": "hello"})

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALUE_ERROR"
    assert body["error"] == "bad input"
    assert "trace_id" in body


@pytest.mark.asyncio
async def test_chat_error_shape_agent_error():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("api.routes.chat.run_task", new=AsyncMock(side_effect=AgentError("agent failed"))):
            response = await client.post("/chat", json={"message": "hello"})

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "AGENT_ERROR"
    assert body["error"] == "agent failed"


@pytest.mark.asyncio
async def test_tools_and_stats_endpoints():
    fake_tool = SimpleNamespace(model_dump=lambda: {"name": "calculator", "description": "math"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("api.routes.tools.list_tools", return_value=[fake_tool]):
            tools_resp = await client.get("/tools")
        stats_resp = await client.get("/api/stats")

    assert tools_resp.status_code == 200
    tools = tools_resp.json()
    assert isinstance(tools, list)
    assert tools[0]["name"] == "calculator"

    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert "agent" in stats
    assert "facts_extracted_total" in stats["agent"]
    assert "tokenizer_calibration" in stats["agent"]
