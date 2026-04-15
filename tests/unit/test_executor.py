import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from tools.schemas import ToolCallRequest, ToolCallResult, ToolError, ToolSpec
from tools.executor import execute, _rate_limit_store, _rate_limit_lock
from tools.sandbox import PermissionResult

@pytest.fixture(autouse=True)
def clear_rate_limits():
    _rate_limit_store.clear()
    yield
    _rate_limit_store.clear()

def generate_request(tool_name="dummy", params=None):
    return ToolCallRequest(
        tool_name=tool_name,
        parameters=params or {},
        user_id="user123",
        trace_id="trace123",
        session_id="session123",
        step_number=1
    )

def make_spec(**kwargs):
    base = {
        "name": "dummy",
        "description": "desc",
        "parameters": {},
        "permission_tier": "base",
        "task_types": ["search"]
    }
    base.update(kwargs)
    return ToolSpec(**base)

@pytest.mark.asyncio
async def test_execute_unknown_tool():
    with patch("tools.executor.get_tool", side_effect=Exception("ToolNotFoundError")) as m:
        # Actually it uses a specific ToolNotFoundError, we'll patch it to raise any exception 
        # or we can mock get_tool to raise core.errors.ToolNotFoundError
        # Let's import it directly
        from core.errors import ToolNotFoundError
        m.side_effect = ToolNotFoundError()
        
        req = generate_request()
        res = await execute(req)
        assert not res.success
        assert res.error.code == "VALIDATION_ERROR"
        assert res.error.retryable is False

@pytest.mark.asyncio
async def test_execute_permission_denied():
    req = generate_request()
    
    spec = make_spec(rate_limit_per_minute=10)
    def mock_get_tool(name): return (spec, AsyncMock())
    
    with patch("tools.executor.get_tool", side_effect=mock_get_tool):
        with patch("tools.executor.check_permission", return_value=PermissionResult(allowed=False, reason="Denied")):
            res = await execute(req)
            assert not res.success
            assert res.error.code == "PERMISSION_DENIED"
            assert "Denied" in res.error.message

@pytest.mark.asyncio
async def test_execute_rate_limited():
    req = generate_request()
    spec = make_spec(rate_limit_per_minute=1) # Limit 1 per min
    def mock_get_tool(name): return (spec, AsyncMock(return_value={"status": "ok"}))
    
    with patch("tools.executor.get_tool", side_effect=mock_get_tool):
        with patch("tools.executor.check_permission", return_value=PermissionResult(allowed=True)):
            # First call succeeds
            res1 = await execute(req)
            assert res1.success is True
            # Second call hits limit
            res2 = await execute(req)
            assert not res2.success
            assert res2.error.code == "RATE_LIMITED"

@pytest.mark.asyncio
async def test_execute_success():
    req = generate_request()
    spec = make_spec(rate_limit_per_minute=10)
    
    async def mock_tool_fn():
        return {"result": "Task Complete"}
        
    def mock_get_tool(name): return (spec, mock_tool_fn)
    
    with patch("tools.executor.get_tool", side_effect=mock_get_tool):
        with patch("tools.executor.check_permission", return_value=PermissionResult(allowed=True)):
            res = await execute(req)
            assert res.success is True
            assert res.output == {"result": "Task Complete"}
            assert res.tool_name == "dummy"

@pytest.mark.asyncio
async def test_execute_timeout_with_retries():
    req = generate_request()
    spec = make_spec(rate_limit_per_minute=10, timeout_seconds=1)
    
    async def mock_tool_fn():
        await asyncio.sleep(1.5) # Will trigger timeout
        return {"result": "Should not reach"}
        
    def mock_get_tool(name): return (spec, mock_tool_fn)

    
    with patch("tools.executor.get_tool", side_effect=mock_get_tool):
        with patch("tools.executor.check_permission", return_value=PermissionResult(allowed=True)):
            with patch("tools.executor.RETRY_DELAYS", [0.01]): # Fast retries for testing
                res = await execute(req, max_retries=1)
                assert not res.success
                assert res.error.code == "TIMEOUT"
                assert res.error.retryable is True

@pytest.mark.asyncio
async def test_execute_exception_with_retries():
    req = generate_request()
    spec = make_spec(rate_limit_per_minute=10)
    
    async def mock_tool_fn():
        raise ValueError("API Error")
        
    def mock_get_tool(name): return (spec, mock_tool_fn)
    
    with patch("tools.executor.get_tool", side_effect=mock_get_tool):
        with patch("tools.executor.check_permission", return_value=PermissionResult(allowed=True)):
            with patch("tools.executor.RETRY_DELAYS", [0.01]):
                res = await execute(req, max_retries=1)
                assert not res.success
                assert res.error.code == "EXTERNAL_API_ERROR"
                assert "API Error" in res.error.message

