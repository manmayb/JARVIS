from fastapi import APIRouter, HTTPException
from tools.registry import list_tools, get_tool
from tools.sandbox import approve_tool, confirm_destructive
from core.errors import ToolNotFoundError
from pydantic import BaseModel

router = APIRouter()

@router.get("/tools")
async def get_tools():
    return [t.model_dump() for t in list_tools()]

class ApproveRequest(BaseModel):
    user_id: str

def _get_tool_or_404(tool_name: str):
    """Resolve the tool spec, raising 404 if not found."""
    try:
        spec, _ = get_tool(tool_name)
        return spec
    except ToolNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")

@router.post("/tools/{tool_name}/approve")
async def approve(tool_name: str, body: ApproveRequest):
    spec = _get_tool_or_404(tool_name)
    if spec.permission_tier != "write":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tool '{tool_name}' has tier '{spec.permission_tier}', not 'write'. "
                f"Use /confirm for destructive tools."
            ),
        )
    approve_tool(body.user_id, tool_name)
    return {"approved": True, "tool": tool_name, "user_id": body.user_id}

@router.post("/tools/{tool_name}/confirm")
async def confirm_tool(tool_name: str, body: ApproveRequest):
    """
    Grant session-scoped confirmation for a destructive tool.
    This resets when the server restarts — by design.
    """
    spec = _get_tool_or_404(tool_name)
    if spec.permission_tier != "destructive":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tool '{tool_name}' has tier '{spec.permission_tier}', not 'destructive'. "
                f"Use /approve for write tools."
            ),
        )
    confirm_destructive(body.user_id, tool_name)
    return {
        "confirmed": True,
        "tool": tool_name,
        "user_id": body.user_id,
        "scope": "session",
        "note": "Confirmation is session-scoped. Re-confirm after server restart.",
    }
