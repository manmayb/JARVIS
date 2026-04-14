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
