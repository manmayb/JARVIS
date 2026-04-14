import os

files = {}

# ── .env ──────────────────────────────────────────────────────────────────────
files[".env"] = '''\
ANTHROPIC_API_KEY=your_key_here
APP_ENV=development
LOG_LEVEL=INFO
'''

# ── core/config.py ────────────────────────────────────────────────────────────
files["core/__init__.py"] = ""
files["core/config.py"] = '''\
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    anthropic_api_key: str
    app_env: str = "development"
    log_level: str = "INFO"

    tool_timeout_seconds: int = 10
    max_retries_per_tool: int = 2
    max_steps: int = 12
    global_timeout_seconds: int = 200
    retry_budget_threshold: float = 0.80

    class Config:
        env_file = ".env"

settings = Settings()
'''

# ── core/schemas.py ───────────────────────────────────────────────────────────
files["core/schemas.py"] = '''\
from pydantic import BaseModel, Field
from typing import Any, Optional
from datetime import datetime
import uuid

class Message(BaseModel):
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class TaskRequest(BaseModel):
    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    user_input: str
    session_id: str
    user_id: str = "default_user"
    trace_id: str = Field(default_factory=lambda: f"tr_{uuid.uuid4().hex[:12]}")

    _steps_completed: int = 0
    _tool_calls_log: list = []
    _last_thought: str = ""

class TaskResult(BaseModel):
    task_id: str
    final_answer: str
    status: str
    steps_taken: Optional[int] = None
    tool_calls_log: list[dict] = []
    trace_id: str = ""

class ThinkOutput(BaseModel):
    thought: str
    action_type: str
    tool_name: Optional[str]
    tool_parameters: Optional[dict]
    final_answer: Optional[str]

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str
    trace_id: str
    steps_taken: Optional[int]
    tools_used: list[str]
    status: str
'''

# ── core/observability.py ─────────────────────────────────────────────────────
files["core/observability.py"] = '''\
import json, sys
from datetime import datetime, timezone

class StructuredLogger:
    def __init__(self, name: str):
        self._name = name

    def _emit(self, level: str, event: str, **kwargs):
        record = {
            "ts":    datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event,
            "name":  self._name,
            **kwargs,
        }
        print(json.dumps(record), file=sys.stdout, flush=True)

    def info   (self, event: str, **kw): self._emit("INFO",    event, **kw)
    def warning(self, event: str, **kw): self._emit("WARNING", event, **kw)
    def error  (self, event: str, **kw): self._emit("ERROR",   event, **kw)
    def debug  (self, event: str, **kw): self._emit("DEBUG",   event, **kw)

def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)
'''

# ── core/errors.py ────────────────────────────────────────────────────────────
files["core/errors.py"] = '''\
class AgentError(Exception): pass
class ToolNotFoundError(AgentError): pass
class PermissionDeniedError(AgentError): pass
class ParseError(AgentError): pass
class ContextWindowError(AgentError): pass
'''

# ── core/llm_parser.py ────────────────────────────────────────────────────────
files["core/llm_parser.py"] = '''\
import re, json
from core.schemas import ThinkOutput
from core.observability import get_logger

log = get_logger(__name__)

_DEFAULTS = {
    "thought": "",
    "action_type": "final_answer",
    "tool_name": None,
    "tool_parameters": None,
    "final_answer": None,
}

def _extract(text: str) -> str:
    text = text.strip()
    if text.startswith("{"):
        return text
    m = re.search(r"\\{.*\\}", text, re.DOTALL)
    if m:
        return m.group(0)
    fence = re.search(r"```(?:json)?\\s*(\\{.*?\\})\\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    return text

def _repair(text: str) -> str:
    text = re.sub(r",\\s*([}\\]])", r"\\1", text)
    text = re.sub(r":\\s*\'([^\']*)\'", r\': "\\1"\', text)
    return text

def parse_think_output(raw: str, trace_id: str) -> ThinkOutput:
    candidate = _extract(raw)
    for attempt, text in enumerate([candidate, _repair(candidate)]):
        try:
            data   = json.loads(text)
            merged = {**_DEFAULTS, **data}
            if merged["action_type"] not in ("tool_call", "final_answer"):
                raise ValueError(f"Bad action_type: {merged[\'action_type\']}")
            if merged["action_type"] == "tool_call" and not merged.get("tool_name"):
                log.warning("parse.missing_tool_name",
                            trace_id=trace_id, snippet=raw[:200])
                merged["action_type"] = "final_answer"
                merged["final_answer"] = merged.get("thought") or "Could not determine action."
            return ThinkOutput(**merged)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            if attempt == 0:
                log.warning("parse.repair_triggered", trace_id=trace_id, error=str(e))
            else:
                log.error("parse.failed", trace_id=trace_id,
                          error=str(e), snippet=raw[:400])
    return ThinkOutput(
        thought="JSON parsing failed.",
        action_type="final_answer",
        tool_name=None,
        tool_parameters=None,
        final_answer=f"Formatting issue. Raw: {raw[:500]}",
    )
'''

# ── tools/ ────────────────────────────────────────────────────────────────────
files["tools/__init__.py"] = ""
files["tools/definitions/__init__.py"] = ""

files["tools/schemas.py"] = '''\
from pydantic import BaseModel
from typing import Optional

class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict
    permission_tier: str
    task_types: list[str]
    rate_limit_per_minute: int = 20
    timeout_seconds: int = 10
    dry_run_supported: bool = False

class ToolCallRequest(BaseModel):
    tool_name: str
    parameters: dict
    session_id: str
    user_id: str
    step_number: int
    trace_id: str
    dry_run: bool = False

class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool

class ToolCallResult(BaseModel):
    success: bool
    output: Optional[dict] = None
    error: Optional[ToolError] = None
    latency_ms: int = 0
    from_cache: bool = False
    tool_name: str = ""
    step_number: int = 0
'''

files["tools/registry.py"] = '''\
from typing import Callable
from tools.schemas import ToolSpec
from core.errors import ToolNotFoundError

_REGISTRY: dict[str, tuple[ToolSpec, Callable]] = {}

def register_tool(name: str, description: str, parameters: dict,
                  permission_tier: str, task_types: list[str],
                  rate_limit_per_minute: int = 20,
                  timeout_seconds: int = 10,
                  dry_run_supported: bool = False):
    def decorator(fn: Callable) -> Callable:
        spec = ToolSpec(
            name=name, description=description, parameters=parameters,
            permission_tier=permission_tier, task_types=task_types,
            rate_limit_per_minute=rate_limit_per_minute,
            timeout_seconds=timeout_seconds,
            dry_run_supported=dry_run_supported,
        )
        _REGISTRY[name] = (spec, fn)
        return fn
    return decorator

def get_tool(name: str) -> tuple[ToolSpec, Callable]:
    if name not in _REGISTRY:
        raise ToolNotFoundError(f"Tool \'{name}\' not registered")
    return _REGISTRY[name]

def list_tools() -> list[ToolSpec]:
    return [spec for spec, _ in _REGISTRY.values()]

def load_all_tools():
    import tools.definitions.web_search   # noqa
    import tools.definitions.calculator   # noqa
    import tools.definitions.file_ops     # noqa
    import tools.definitions.python_exec  # noqa
'''

files["tools/sandbox.py"] = '''\
from tools.schemas import ToolSpec
from pydantic import BaseModel

_AUTO_APPROVED: dict[str, set[str]] = {}

class PermissionResult(BaseModel):
    allowed: bool
    reason: str = ""
    requires_confirmation: bool = False

def check_permission(spec: ToolSpec, user_id: str) -> PermissionResult:
    if spec.permission_tier == "read":
        return PermissionResult(allowed=True)
    if spec.permission_tier == "write":
        if spec.name in _AUTO_APPROVED.get(user_id, set()):
            return PermissionResult(allowed=True)
        return PermissionResult(allowed=False, requires_confirmation=True,
                                reason=f"First use of write tool \'{spec.name}\'")
    return PermissionResult(allowed=False, requires_confirmation=True,
                            reason=f"Destructive tool \'{spec.name}\' requires confirmation")

def approve_tool(user_id: str, tool_name: str):
    _AUTO_APPROVED.setdefault(user_id, set()).add(tool_name)
'''

files["tools/executor.py"] = '''\
import asyncio, time
from tools.registry import get_tool
from tools.sandbox import check_permission
from tools.schemas import ToolCallRequest, ToolCallResult, ToolError
from core.config import settings
from core.errors import ToolNotFoundError
from core.observability import get_logger

log = get_logger(__name__)
RETRY_DELAYS = [1, 5]

async def execute(req: ToolCallRequest,
                  max_retries: int = settings.max_retries_per_tool) -> ToolCallResult:
    try:
        spec, tool_fn = get_tool(req.tool_name)
    except ToolNotFoundError:
        return ToolCallResult(
            success=False,
            error=ToolError(code="VALIDATION_ERROR",
                            message=f"Unknown tool: {req.tool_name}",
                            retryable=False),
            tool_name=req.tool_name, step_number=req.step_number)

    perm = check_permission(spec, req.user_id)
    if not perm.allowed:
        return ToolCallResult(
            success=False,
            error=ToolError(code="PERMISSION_DENIED",
                            message=perm.reason, retryable=False),
            tool_name=req.tool_name, step_number=req.step_number)

    retry_count = 0
    while True:
        start = time.monotonic()
        try:
            raw     = await asyncio.wait_for(tool_fn(**req.parameters),
                                             timeout=spec.timeout_seconds)
            latency = int((time.monotonic() - start) * 1000)
            log.info("tool.success", tool=req.tool_name,
                     latency_ms=latency, trace_id=req.trace_id)
            return ToolCallResult(success=True, output=raw, latency_ms=latency,
                                  tool_name=req.tool_name,
                                  step_number=req.step_number)

        except asyncio.CancelledError:
            log.warning("tool.cancelled", tool=req.tool_name, trace_id=req.trace_id)
            raise

        except asyncio.TimeoutError:
            latency = int((time.monotonic() - start) * 1000)
            err = ToolError(code="TIMEOUT",
                            message=f"Exceeded {spec.timeout_seconds}s",
                            retryable=True)
            if retry_count >= max_retries:
                return ToolCallResult(success=False, error=err,
                                      latency_ms=latency,
                                      tool_name=req.tool_name,
                                      step_number=req.step_number)

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            log.error("tool.error", tool=req.tool_name,
                      error=str(e), trace_id=req.trace_id)
            err = ToolError(code="EXTERNAL_API_ERROR",
                            message=str(e), retryable=True)
            if retry_count >= max_retries:
                return ToolCallResult(success=False, error=err,
                                      latency_ms=latency,
                                      tool_name=req.tool_name,
                                      step_number=req.step_number)

        retry_count += 1
        delay = RETRY_DELAYS[retry_count - 1]
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            log.warning("retry.sleep_cancelled", tool=req.tool_name,
                        retry_count=retry_count, trace_id=req.trace_id)
            raise
'''

# ── tool definitions ──────────────────────────────────────────────────────────
files["tools/definitions/calculator.py"] = '''\
from tools.registry import register_tool
import sympy

@register_tool(
    name="calculator",
    description="Evaluate a mathematical expression. Supports arithmetic, algebra, trig, calculus.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string",
                           "description": "e.g. \'2**10\', \'sqrt(144)\', \'integrate(x**2, x)\'"}
        },
        "required": ["expression"]
    },
    permission_tier="read",
    task_types=["calculation", "math", "general"],
)
async def calculator(expression: str) -> dict:
    try:
        result = sympy.sympify(expression)
        return {"result": str(result), "expression": expression}
    except Exception as e:
        return {"error": str(e), "expression": expression}
'''

files["tools/definitions/web_search.py"] = '''\
import httpx
from tools.registry import register_tool

@register_tool(
    name="web_search",
    description="Search the web using DuckDuckGo. Returns up to 5 results with title, URL, and snippet.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query, 3-10 words"}
        },
        "required": ["query"]
    },
    permission_tier="read",
    task_types=["research", "general", "news"],
    timeout_seconds=10,
)
async def web_search(query: str) -> dict:
    url    = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
    async with httpx.AsyncClient(timeout=9.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("RelatedTopics", [])[:5]:
        if "Text" in item and "FirstURL" in item:
            results.append({
                "title":   item.get("Text", "")[:100],
                "url":     item.get("FirstURL", ""),
                "snippet": item.get("Text", ""),
            })
    if not results and data.get("AbstractText"):
        results.append({
            "title":   data.get("Heading", ""),
            "url":     data.get("AbstractURL", ""),
            "snippet": data.get("AbstractText", ""),
        })
    return {"results": results, "query": query, "count": len(results)}
'''

files["tools/definitions/file_ops.py"] = '''\
import aiofiles
from pathlib import Path
from tools.registry import register_tool

_ALLOWED_DIR = Path("/tmp/jarvis_files").resolve()
_ALLOWED_DIR.mkdir(exist_ok=True)

def _safe_path(filename: str) -> Path:
    path = (_ALLOWED_DIR / filename).resolve()
    if not str(path).startswith(str(_ALLOWED_DIR)):
        raise ValueError(f"Path traversal blocked: {filename}")
    return path

@register_tool(
    name="file_read",
    description="Read a text file from /tmp/jarvis_files/.",
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string"}
        },
        "required": ["filename"]
    },
    permission_tier="read",
    task_types=["file", "coding", "general"],
)
async def file_read(filename: str) -> dict:
    path = _safe_path(filename)
    if not path.exists():
        return {"error": f"File not found: {filename}"}
    async with aiofiles.open(path, "r") as f:
        content = await f.read()
    return {"content": content, "filename": filename,
            "size_bytes": path.stat().st_size}

@register_tool(
    name="file_write",
    description="Write text to a file in /tmp/jarvis_files/.",
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "content":  {"type": "string"}
        },
        "required": ["filename", "content"]
    },
    permission_tier="write",
    task_types=["file", "coding"],
)
async def file_write(filename: str, content: str) -> dict:
    path = _safe_path(filename)
    async with aiofiles.open(path, "w") as f:
        await f.write(content)
    return {"written": True, "filename": filename,
            "size_bytes": len(content.encode())}
'''

files["tools/definitions/python_exec.py"] = '''\
import asyncio, tempfile, os, textwrap
from tools.registry import register_tool
from core.config import settings
from core.observability import get_logger

log = get_logger(__name__)

_MAX_OUTPUT_CHARS = 4000
_MAX_CODE_CHARS   = 8000
_SAFE_ENV = {
    "PATH": "/usr/bin:/usr/local/bin",
    "HOME": "/tmp",
    "PYTHONPATH": "",
    "PYTHONDONTWRITEBYTECODE": "1",
}
_BLOCKED = [
    "import os", "import sys", "import subprocess", "import socket",
    "import requests", "import urllib", "import http", "import shutil",
    "__import__", "open(", "eval(", "exec(", "compile(", "importlib",
]

def _static_check(code: str) -> list[str]:
    return [f"Blocked: \'{p}\'" for p in _BLOCKED if p in code]

@register_tool(
    name="python_exec",
    description="Execute a Python snippet. No file I/O or network. Use print() for output.",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code using print() for output."}
        },
        "required": ["code"]
    },
    permission_tier="destructive",
    task_types=["coding", "data", "calculation"],
    timeout_seconds=10,
)
async def python_exec(code: str) -> dict:
    if len(code) > _MAX_CODE_CHARS:
        return {"error": f"Code exceeds {_MAX_CODE_CHARS} char limit.", "stdout": ""}
    violations = _static_check(code)
    if violations:
        return {"error": f"Static check failed: {chr(59).join(violations)}", "stdout": ""}

    wrapper = textwrap.dedent(f"""
        import builtins, sys
        from io import StringIO
        _SAFE = {{k: getattr(builtins,k) for k in [
            \'print\',\'len\',\'range\',\'enumerate\',\'zip\',\'map\',\'filter\',
            \'sorted\',\'reversed\',\'sum\',\'min\',\'max\',\'abs\',\'round\',
            \'int\',\'float\',\'str\',\'bool\',\'list\',\'dict\',\'tuple\',\'set\',
            \'type\',\'isinstance\',\'repr\',\'hash\',
        ]}}
        _out = StringIO()
        sys.stdout = _out
        try:
            exec(compile({repr(code)}, "<code>", "exec"), {{"__builtins__": _SAFE}})
        except Exception as _e:
            print(f"RuntimeError: {{_e}}")
        sys.stdout = sys.__stdout__
        print(_out.getvalue(), end="")
    """)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                     dir="/tmp", delete=False) as f:
        f.write(wrapper)
        tmp = f.name

    proc = await asyncio.create_subprocess_exec(
        "python3", tmp,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_SAFE_ENV,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.tool_timeout_seconds)
        return {
            "stdout":    stdout.decode()[:_MAX_OUTPUT_CHARS],
            "stderr":    stderr.decode()[:500] if proc.returncode != 0 else "",
            "exit_code": proc.returncode,
        }
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.communicate(), timeout=1.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        return {"error": f"Timed out after {settings.tool_timeout_seconds}s",
                "stdout": ""}
    finally:
        os.unlink(tmp)
'''

# ── orchestration/ ────────────────────────────────────────────────────────────
files["orchestration/__init__.py"] = ""

files["orchestration/message_window.py"] = '''\
from core.schemas import Message

SOFT_LIMIT = 12_000
HARD_LIMIT = 20_000
MIN_TAIL   = 6

def truncate_history(messages: list[Message]) -> tuple[list[Message], bool]:
    if not messages:
        return messages, False
    total = sum(len(m.content) for m in messages)
    if total <= SOFT_LIMIT:
        return messages, False
    system = messages[0]
    rest   = messages[1:]
    tail   = rest[-MIN_TAIL:] if len(rest) >= MIN_TAIL else rest
    middle = rest[:-MIN_TAIL] if len(rest) > MIN_TAIL else []
    tail_chars  = sum(len(m.content) for m in tail)
    budget      = SOFT_LIMIT - len(system.content) - tail_chars
    kept_middle = []
    for msg in reversed(middle):
        if len(msg.content) <= budget:
            kept_middle.insert(0, msg)
            budget -= len(msg.content)
    result = [system] + kept_middle + tail
    total  = sum(len(m.content) for m in result)
    if total > HARD_LIMIT and len(result) > 2:
        overflow  = total - HARD_LIMIT
        old       = result[1]
        result[1] = Message(role=old.role,
                            content="[truncated]\\n" + old.content[overflow + 12:])
    return result, True

def truncation_notice(dropped: int) -> Message:
    return Message(role="system",
                   content=f"[{dropped} earlier messages omitted. Continue from below.]")
'''

files["orchestration/loop_guard.py"] = '''\
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
                f"\'{self._last_tool}\' called {self._same_tool_streak} times in a row")
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
'''

files["orchestration/llm_router.py"] = '''\
import anthropic, time
from core.config import settings
from core.observability import get_logger
from pydantic import BaseModel

log = get_logger(__name__)

class LLMResponse(BaseModel):
    content: str
    model_used: str
    tokens_in: int
    tokens_out: int
    latency_ms: int

_client      = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
FAST_MODEL   = "claude-haiku-4-5-20251001"
STRONG_MODEL = "claude-sonnet-4-6"

def _select_model(prompt_tokens: int, task_type: str) -> str:
    if prompt_tokens > 2000 or task_type in ("research", "coding", "analysis"):
        return STRONG_MODEL
    return FAST_MODEL

async def call(messages: list[dict], system: str,
               task_type: str = "general",
               trace_id: str = "") -> LLMResponse:
    prompt_tokens = sum(len(m["content"]) for m in messages) // 4
    model         = _select_model(prompt_tokens, task_type)
    start         = time.monotonic()

    log.info("llm.call_start", model=model, trace_id=trace_id,
             est_prompt_tokens=prompt_tokens)

    response = await _client.messages.create(
        model=model, max_tokens=1024,
        system=system, messages=messages,
    )
    latency = int((time.monotonic() - start) * 1000)
    content = "".join(b.text for b in response.content if hasattr(b, "text"))

    log.info("llm.call_done", model=model, latency_ms=latency,
             tokens_in=response.usage.input_tokens,
             tokens_out=response.usage.output_tokens,
             trace_id=trace_id)

    return LLMResponse(content=content, model_used=model,
                       tokens_in=response.usage.input_tokens,
                       tokens_out=response.usage.output_tokens,
                       latency_ms=latency)
'''

files["orchestration/context_assembler.py"] = '''\
import json
from core.schemas import Message, TaskRequest
from tools.registry import list_tools
from orchestration.message_window import truncate_history, truncation_notice
from core.observability import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT = """You are Jarvis, a capable AI agent with access to tools.

You MUST respond with valid JSON — no other text outside the JSON object.
Schema:
{
  "thought": "<your reasoning>",
  "action_type": "tool_call" | "final_answer",
  "tool_name": "<tool name>" | null,
  "tool_parameters": {...} | null,
  "final_answer": "<answer>" | null
}

Rules:
- Think step by step before acting.
- Use tools when you need current information or to perform an action.
- When you have enough information, set action_type to final_answer.
- final_answer must be a complete, helpful response to the user.
- Never set both tool_name and final_answer in the same response.
"""

def build(request: TaskRequest,
          message_history: list[Message]) -> tuple[str, list[dict]]:
    tools     = list_tools()
    tool_desc = _format_tools(tools)
    system    = SYSTEM_PROMPT + f"\\n## Available tools\\n{tool_desc}"

    trimmed, was_truncated = truncate_history(message_history)
    if was_truncated:
        dropped = len(message_history) - len(trimmed)
        trimmed.insert(1, truncation_notice(dropped))
        log.info("context.truncated", dropped=dropped, trace_id=request.trace_id)

    messages = [{"role": m.role, "content": m.content}
                for m in trimmed if m.role in ("user", "assistant")]
    return system, messages

def _format_tools(tools) -> str:
    lines = []
    for t in tools:
        params = json.dumps(t.parameters.get("properties", {}), indent=2)
        lines.append(f"- **{t.name}** ({t.permission_tier}): {t.description}\\n"
                     f"  Parameters: {params}")
    return "\\n\\n".join(lines)
'''

files["orchestration/react_loop.py"] = '''\
import asyncio, time, json
from core.schemas import TaskRequest, Message
from core.config import settings
from core.llm_parser import parse_think_output
from core.observability import get_logger
from orchestration.llm_router import call as llm_call
from orchestration.context_assembler import build as assemble_context
from orchestration.loop_guard import LoopGuard, Step, hash_params
from tools.executor import execute as tool_execute
from tools.schemas import ToolCallRequest
from pydantic import BaseModel
from typing import Optional

log = get_logger(__name__)

MAX_OBSERVATION_CHARS = 2000

class LoopResult(BaseModel):
    answer: str
    exit_reason: str
    steps: int
    tool_calls_log: list[dict] = []

async def run(request: TaskRequest,
              message_history: list[Message],
              start_time: float) -> LoopResult:

    guard      = LoopGuard(max_steps=settings.max_steps)
    step_count = 0
    trace_id   = request.trace_id

    while True:
        system, messages = assemble_context(request, message_history)
        llm_resp = await llm_call(messages, system, trace_id=trace_id)
        thought  = parse_think_output(llm_resp.content, trace_id)
        request._last_thought = thought.thought

        message_history.append(Message(role="assistant", content=llm_resp.content))

        if thought.action_type == "final_answer":
            log.info("loop.final_answer", steps=step_count, trace_id=trace_id)
            return LoopResult(answer=thought.final_answer or "Done.",
                              exit_reason="completed", steps=step_count,
                              tool_calls_log=request._tool_calls_log)

        violation = guard.check(step_count)
        if violation:
            log.warning("loop.guard_violation", code=violation.code,
                        message=violation.message, trace_id=trace_id)
            return LoopResult(answer=_partial_answer(message_history),
                              exit_reason=violation.code, steps=step_count,
                              tool_calls_log=request._tool_calls_log)

        step_count += 1
        request._steps_completed = step_count

        elapsed          = time.monotonic() - start_time
        budget_exhausted = elapsed > (settings.global_timeout_seconds
                                      * settings.retry_budget_threshold)
        in_retry         = bool(request._tool_calls_log and
                                not request._tool_calls_log[-1]["success"])
        effective_retries = (0 if (budget_exhausted and not in_retry)
                             else settings.max_retries_per_tool)

        call_req = ToolCallRequest(
            tool_name=thought.tool_name,
            parameters=thought.tool_parameters or {},
            session_id=request.session_id,
            user_id=request.user_id,
            step_number=step_count,
            trace_id=trace_id,
        )

        log.info("loop.tool_call", tool=thought.tool_name,
                 step=step_count, trace_id=trace_id)
        result = await tool_execute(call_req, max_retries=effective_retries)

        request._tool_calls_log.append({
            "step":       step_count,
            "tool":       call_req.tool_name,
            "success":    result.success,
            "latency_ms": result.latency_ms,
            "error_code": result.error.code if not result.success else None,
        })

        if result.success:
            observation = json.dumps(result.output)
        else:
            observation = (f"Tool \'{call_req.tool_name}\' failed: {result.error.message}. "
                           + ("Try a different approach." if not result.error.retryable
                              else "Retries exhausted."))

        if len(observation) > MAX_OBSERVATION_CHARS:
            observation = observation[:MAX_OBSERVATION_CHARS] + "... [truncated]"

        message_history.append(Message(
            role="user",
            content=f"<observation>{observation}</observation>"
        ))

        guard.record(Step(
            tool_name=call_req.tool_name,
            params_hash=hash_params(call_req.parameters),
            tool_success=result.success,
            observation_length=len(observation),
        ))

def _partial_answer(history: list[Message]) -> str:
    for msg in reversed(history):
        if msg.role == "assistant" and msg.content:
            return f"Task stopped early. Last reasoning: {msg.content[:300]}"
    return "Task stopped early — no partial result available."
'''

files["orchestration/task_runner.py"] = '''\
import asyncio, time
from core.schemas import TaskRequest, TaskResult, Message
from core.observability import get_logger
from core.config import settings
from orchestration.react_loop import run as run_loop

log = get_logger(__name__)

async def run(request: TaskRequest) -> TaskResult:
    start = time.monotonic()
    try:
        return await asyncio.wait_for(
            _run_inner(request, start),
            timeout=settings.global_timeout_seconds,
        )
    except asyncio.TimeoutError:
        elapsed  = round(time.monotonic() - start, 2)
        log_tail = getattr(request, "_tool_calls_log", [])
        last     = log_tail[-1] if log_tail else {}
        log.error("task.global_timeout",
                  trace_id=request.trace_id,
                  elapsed_seconds=elapsed,
                  last_step=getattr(request, "_steps_completed", 0),
                  last_tool=last.get("tool"),
                  last_thought_snippet=getattr(request, "_last_thought", "")[:200])
        return TaskResult(
            task_id=request.task_id,
            final_answer=(
                "This task took too long to complete. I returned the best result "
                "based on partial progress. Try narrowing the request or splitting "
                "it into smaller steps."
            ),
            status="timeout",
            steps_taken=getattr(request, "_steps_completed", 0),
            tool_calls_log=log_tail,
            trace_id=request.trace_id,
        )
    except asyncio.CancelledError:
        log.warning("task.cancelled", trace_id=request.trace_id)
        raise

async def _run_inner(request: TaskRequest, start: float) -> TaskResult:
    request._steps_completed = 0
    request._tool_calls_log  = []
    request._last_thought    = ""

    message_history = [Message(role="user", content=request.user_input)]
    result = await run_loop(request, message_history, start)

    return TaskResult(
        task_id=request.task_id,
        final_answer=result.answer,
        status=result.exit_reason,
        steps_taken=result.steps,
        tool_calls_log=result.tool_calls_log,
        trace_id=request.trace_id,
    )
'''

# ── api/ ──────────────────────────────────────────────────────────────────────
files["api/__init__.py"] = ""
files["api/middleware/__init__.py"] = ""
files["api/routes/__init__.py"] = ""

files["api/middleware/logger.py"] = '''\
import time, uuid
from fastapi import Request
from core.observability import get_logger

log = get_logger("api")

async def logging_middleware(request: Request, call_next):
    trace_id = uuid.uuid4().hex[:12]
    start    = time.monotonic()
    request.state.trace_id = trace_id
    response = await call_next(request)
    latency  = round((time.monotonic() - start) * 1000)
    log.info("api.request", method=request.method, path=request.url.path,
             status=response.status_code, latency_ms=latency, trace_id=trace_id)
    return response
'''

files["api/routes/chat.py"] = '''\
import uuid
from fastapi import APIRouter
from core.schemas import ChatRequest, ChatResponse, TaskRequest
from orchestration.task_runner import run as run_task

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    task_req   = TaskRequest(user_input=req.message, session_id=session_id)
    result     = await run_task(task_req)
    return ChatResponse(
        response=result.final_answer,
        session_id=session_id,
        trace_id=result.trace_id,
        steps_taken=result.steps_taken,
        tools_used=list({e["tool"] for e in result.tool_calls_log if e.get("tool")}),
        status=result.status,
    )
'''

files["api/routes/tools.py"] = '''\
from fastapi import APIRouter
from tools.registry import list_tools
from tools.sandbox import approve_tool
from pydantic import BaseModel

router = APIRouter()

@router.get("/tools")
async def get_tools():
    return [t.model_dump() for t in list_tools()]

class ApproveRequest(BaseModel):
    user_id: str

@router.post("/tools/{tool_name}/approve")
async def approve(tool_name: str, body: ApproveRequest):
    approve_tool(body.user_id, tool_name)
    return {"approved": True, "tool": tool_name, "user_id": body.user_id}
'''

files["api/app.py"] = '''\
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from api.middleware.logger import logging_middleware
from api.routes.chat import router as chat_router
from api.routes.tools import router as tools_router
from tools.registry import load_all_tools

app = FastAPI(title="Jarvis", version="0.1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(BaseHTTPMiddleware, dispatch=logging_middleware)

@app.on_event("startup")
async def startup():
    load_all_tools()

app.include_router(chat_router)
app.include_router(tools_router)

@app.get("/health")
async def health():
    from tools.registry import list_tools
    return {"status": "ok", "tools_loaded": len(list_tools())}
'''

# ── tests/ ────────────────────────────────────────────────────────────────────
files["tests/__init__.py"] = ""
files["tests/unit/__init__.py"] = ""
files["tests/integration/__init__.py"] = ""

# ── write everything ──────────────────────────────────────────────────────────
for path, content in files.items():
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "w") as f:
        f.write(content)
    print(f"wrote {path}")

print("\nDone. Edit .env and add your ANTHROPIC_API_KEY, then run:")
print("  uvicorn api.app:app --reload --port 8000")