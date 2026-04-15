import pytest
from orchestration.loop_guard import LoopGuard, Step, hash_params

def test_hash_params():
    params1 = {"b": 2, "a": 1}
    params2 = {"a": 1, "b": 2}
    # Should sort keys and produce identical hashes
    assert hash_params(params1) == hash_params(params2)
    assert len(hash_params(params1)) == 8

def test_max_steps():
    guard = LoopGuard(max_steps=3)
    # Check at step 3 (which is index 3 if we start from 0)
    violation = guard.check(3)
    assert violation is not None
    assert violation.code == "max_steps_exceeded"

def test_no_progress():
    guard = LoopGuard(max_no_progress=2)
    guard.record(Step("tool1", "hash", False, 0))
    guard.record(Step("tool2", "hash", False, 0))
    violation = guard.check(1)
    assert violation is not None
    assert violation.code == "no_progress"

def test_progress_resets_counter():
    guard = LoopGuard(max_no_progress=2)
    guard.record(Step("tool1", "hash", False, 0))
    # successful progress
    guard.record(Step("tool2", "hash", True, 10))
    violation = guard.check(1)
    assert violation is None

def test_same_tool_streak():
    guard = LoopGuard(max_same_tool_streak=3)
    guard.record(Step("tool1", "hash1", True, 10))
    guard.record(Step("tool1", "hash2", True, 10))
    guard.record(Step("tool1", "hash3", True, 10))
    violation = guard.check(1)
    assert violation is not None
    assert violation.code == "same_tool_streak"

def test_identical_calls():
    guard = LoopGuard(max_identical_calls=2)
    guard.record(Step("tool1", "hash_same", True, 10))
    guard.record(Step("tool1", "hash_same", True, 10))
    violation = guard.check(1)
    assert violation is not None
    assert violation.code == "identical_calls"
