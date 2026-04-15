import pytest
from core.llm_parser import parse_think_output, _extract, _repair

def test_extract_pure_json():
    text = '{"action_type": "final_answer"}'
    assert _extract(text) == text

def test_extract_from_fences():
    text = '''Some text surrounding
```json
{"action_type": "final_answer"}
```
And more text.
'''
    assert _extract(text) == '{"action_type": "final_answer"}'

def test_extract_first_brace():
    text = 'Wait I know this! {"action_type": "tool_call"} this is the reason.'
    assert _extract(text) == '{"action_type": "tool_call"}'

def test_repair_commas_and_quotes():
    # It repairs single quotes on values and drops trailing commas before closing braces
    text = '{"action_type": \'final_answer\',}'
    repaired = _repair(text)
    assert '"action_type": "final_answer"' in repaired
    assert ",}" not in repaired
    
def test_parse_valid_tool_call():
    raw = '{"action_type": "tool_call", "tool_name": "calculator", "tool_parameters": {"eq": "1+1"}}'
    output = parse_think_output(raw, "test")
    assert output.action_type == "tool_call"
    assert output.tool_name == "calculator"
    assert output.tool_parameters == {"eq": "1+1"}

def test_parse_valid_final_answer():
    raw = '{"action_type": "final_answer", "final_answer": "It is exactly 2."}'
    output = parse_think_output(raw, "test")
    assert output.action_type == "final_answer"
    assert output.final_answer == "It is exactly 2."

def test_parse_tool_call_missing_name():
    raw = '{"action_type": "tool_call", "thought": "I want a tool"}'
    output = parse_think_output(raw, "test")
    # Should fallback to final_answer
    assert output.action_type == "final_answer"
    assert output.final_answer == "I want a tool"

def test_parse_malformed_json_fallback():
    raw = 'Just pure text, no JSON at all.'
    output = parse_think_output(raw, "test")
    assert output.action_type == "final_answer"
    assert "Raw: Just pure text" in output.final_answer
    assert "JSON parsing failed" in output.thought

def test_parse_repaired_json():
    # Has a trailing comma which invalidates standard json.loads but is repaired
    raw = '{"action_type": "final_answer", "final_answer": "success",}'
    output = parse_think_output(raw, "test")
    assert output.action_type == "final_answer"
    assert output.final_answer == "success"
