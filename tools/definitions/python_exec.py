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
    return [f"Blocked: '{p}'" for p in _BLOCKED if p in code]

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
            'print','len','range','enumerate','zip','map','filter',
            'sorted','reversed','sum','min','max','abs','round',
            'int','float','str','bool','list','dict','tuple','set',
            'type','isinstance','repr','hash',
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
