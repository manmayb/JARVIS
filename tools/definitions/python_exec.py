import asyncio, tempfile, os, textwrap, ast
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

# Modules that must never be imported, even transitively
_BLOCKED_MODULES = {
    "os", "sys", "subprocess", "socket", "requests", "urllib",
    "http", "shutil", "importlib", "builtins", "ctypes", "threading",
    "multiprocessing", "signal", "pathlib", "glob", "tempfile",
    "pickle", "shelve", "marshal", "pty", "tty", "termios",
}

# Top-level names that must never be called directly
_BLOCKED_BUILTINS = {"eval", "exec", "compile", "open", "__import__", "breakpoint"}

# Dunder attributes that grant class hierarchy introspection / escape hatches
_BLOCKED_ATTRS = {
    "__class__", "__bases__", "__subclasses__", "__mro__",
    "__globals__", "__builtins__", "__code__", "__closure__",
    "__reduce__", "__reduce_ex__",
}


class _ASTSecurityVisitor(ast.NodeVisitor):
    """Walk the AST and collect policy violations."""

    def __init__(self):
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _BLOCKED_MODULES:
                self.violations.append(f"Blocked import: '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        root = (node.module or "").split(".")[0]
        if root in _BLOCKED_MODULES:
            self.violations.append(f"Blocked import: 'from {node.module} import ...'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # Catch bare calls: eval(...), exec(...), open(...)
        if isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_BUILTINS:
            self.violations.append(f"Blocked call: '{node.func.id}()'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr in _BLOCKED_ATTRS:
            self.violations.append(f"Blocked attribute access: '.{node.attr}'")
        self.generic_visit(node)


def _ast_check(code: str) -> list[str]:
    """
    Parse the code into an AST and run the security visitor.
    Returns a list of violation strings; empty means clean.
    A SyntaxError itself is returned as a violation so malformed
    code that might confuse a string scanner is always rejected.
    """
    try:
        tree = ast.parse(code, filename="<sandbox>")
    except SyntaxError as e:
        return [f"SyntaxError: {e}"]
    visitor = _ASTSecurityVisitor()
    visitor.visit(tree)
    return visitor.violations

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
    violations = _ast_check(code)
    if violations:
        return {"error": "AST security check failed", "violations": violations, "stdout": ""}

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
