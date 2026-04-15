import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.schemas import TaskRequest
from orchestration.react_loop import run


@pytest.mark.asyncio
async def test_react_loop_two_iteration_tool_then_final():
    request = TaskRequest(
        user_input="Calculate 1+1",
        session_id="sess-test",
        user_id="user-test",
        trace_id="trace-test",
    )

    llm_responses = [
        SimpleNamespace(content='{"action_type":"tool_call","tool_name":"calculator","tool_parameters":{"expression":"1+1"}}'),
        SimpleNamespace(content='{"action_type":"final_answer","final_answer":"2"}'),
    ]

    parsed_outputs = [
        SimpleNamespace(
            thought="Need calculator",
            action_type="tool_call",
            tool_name="calculator",
            tool_parameters={"expression": "1+1"},
            final_answer=None,
        ),
        SimpleNamespace(
            thought="Done",
            action_type="final_answer",
            tool_name=None,
            tool_parameters=None,
            final_answer="2",
        ),
    ]

    with patch("orchestration.react_loop.build_enriched", new=AsyncMock(return_value=("system", []))), \
         patch("orchestration.react_loop.build", return_value=("system", [])), \
         patch("orchestration.react_loop.llm_call", new=AsyncMock(side_effect=llm_responses)), \
         patch("orchestration.react_loop.parse_think_output", side_effect=parsed_outputs), \
         patch("orchestration.react_loop.tool_execute", new=AsyncMock(return_value=SimpleNamespace(success=True, output={"value": 2}, latency_ms=4, error=None))), \
         patch("orchestration.react_loop.tool_cache.get", new=AsyncMock(return_value=None)), \
         patch("orchestration.react_loop.tool_cache.set", new=AsyncMock()), \
         patch("orchestration.react_loop.save_session", new=AsyncMock()), \
         patch("orchestration.react_loop._background_extract", new=AsyncMock()):
        result = await run(request, message_history=[], start_time=0.0)

    assert result.exit_reason == "completed"
    assert result.answer == "2"
    assert result.steps == 1
    assert len(result.tool_calls_log) == 1
    assert result.tool_calls_log[0]["tool"] == "calculator"


@pytest.mark.asyncio
async def test_react_loop_guard_halts_when_limit_hit():
    request = TaskRequest(
        user_input="loop",
        session_id="sess-guard",
        user_id="user-guard",
        trace_id="trace-guard",
    )

    llm_response = SimpleNamespace(content='{"action_type":"tool_call","tool_name":"calculator","tool_parameters":{}}')
    parsed_tool_call = SimpleNamespace(
        thought="Need tool",
        action_type="tool_call",
        tool_name="calculator",
        tool_parameters={},
        final_answer=None,
    )

    with patch("orchestration.react_loop.build_enriched", new=AsyncMock(return_value=("system", []))), \
         patch("orchestration.react_loop.build", return_value=("system", [])), \
         patch("orchestration.react_loop.llm_call", new=AsyncMock(return_value=llm_response)), \
         patch("orchestration.react_loop.parse_think_output", return_value=parsed_tool_call), \
            patch("orchestration.react_loop.save_session", new=AsyncMock()), \
            patch("orchestration.react_loop._background_extract", new=AsyncMock()), \
         patch("orchestration.react_loop.settings.max_steps", 0):
        result = await run(request, message_history=[], start_time=0.0)

    assert result.exit_reason == "max_steps_exceeded"
    assert result.steps == 0
