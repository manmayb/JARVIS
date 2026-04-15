import pytest
import uuid
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from core.schemas import ThinkOutput, TaskResult
from api.app import app

client = TestClient(app)

def test_chat_flow_success():
    # Setup mock for the react loop to simulate a successful run
    mock_result = TaskResult(
        task_id="task_123",
        status="completed",
        final_answer="The answer is 42.",
        trace_id="trace_123",
        steps_taken=1,
        tool_calls_log=[]
    )
    
    with patch("api.routes.chat.run_task", new_callable=AsyncMock) as mock_run_task:
        mock_run_task.return_value = mock_result
        
        response = client.post("/chat", json={"message": "What is the answer to life?"})
        
        assert response.status_code == 200
        data = response.json()
        assert data["response"] == "The answer is 42."
        assert data["status"] == "completed"
        # Route now generates a fresh trace ID at request entry.
        uuid.UUID(data["trace_id"])
        mock_run_task.assert_called_once()

def test_chat_flow_error_fallback():
    # Setup mock to simulate a failure inside the task runner
    mock_result = TaskResult(
        task_id="task_124",
        status="error",
        final_answer="I encountered an internal error.",
        trace_id="trace_124",
        steps_taken=3,
        tool_calls_log=[{"tool": "database_search", "result": "error"}]
    )
    
    with patch("api.routes.chat.run_task", new_callable=AsyncMock) as mock_run_task:
        mock_run_task.return_value = mock_result
        
        response = client.post("/chat", json={"message": "Trigger error please"})
        
        assert response.status_code == 200
        data = response.json()
        assert data["response"] == "I encountered an internal error."
        assert data["status"] == "error"
        assert "database_search" in data["tools_used"]
        mock_run_task.assert_called_once()
