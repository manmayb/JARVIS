from dataclasses import dataclass, field
from collections import Counter
from typing import Optional
import hashlib, json

@dataclass
class Step:
    tool_name: Optional[str]
    params_hash: str
    tool_success: bool
    observation_length: int

@dataclass
class LoopGuard:
    max_steps:            int = 12
    max_identical_calls:  int = 3
    max_no_progress:      int = 4
    max_same_tool_streak: int = 5

    _steps:             list = field(default_factory=list)
    _no_progress_count: int  = 0
    _last_tool:         Optional[str] = None
    _same_tool_streak:  int  = 0

    @dataclass
    class Violation:
        code:    str
        message: str

    def record(self, step: Step):
        self._steps.append(step)
        if step.tool_name and step.tool_name == self._last_tool:
            self._same_tool_streak += 1
        else:
            self._same_tool_streak = 1
        self._last_tool = step.tool_name
        if not step.tool_success or not step.observation_length:
            self._no_progress_count += 1
        else:
            self._no_progress_count = 0

    def check(self, current_step: int) -> Optional[Violation]:
        if current_step >= self.max_steps:
            return self.Violation("MAX_STEPS", f"Reached {self.max_steps} steps")
        if self._no_progress_count >= self.max_no_progress:
            return self.Violation("NO_PROGRESS",
                f"{self._no_progress_count} consecutive steps without progress")
        if self._same_tool_streak >= self.max_same_tool_streak:
            return self.Violation("SAME_TOOL_STREAK",
                f"'{self._last_tool}' called {self._same_tool_streak} times in a row")
        recent = self._steps[-self.max_identical_calls:]
        if len(recent) == self.max_identical_calls:
            sigs = [f"{s.tool_name}:{s.params_hash}" for s in recent]
            if Counter(sigs).most_common(1)[0][1] >= self.max_identical_calls:
                return self.Violation("IDENTICAL_CALLS",
                    f"Identical call repeated {self.max_identical_calls} times")
        return None

def hash_params(params: dict) -> str:
    return hashlib.md5(
        json.dumps(params, sort_keys=True).encode()
    ).hexdigest()[:8]
