from fastapi import APIRouter
from tools.registry import list_tools
from tools.sandbox import approve_tool, confirm_destructive
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

@router.post("/tools/{tool_name}/confirm")
async def confirm_tool(tool_name: str, body: ApproveRequest):
    """
    Grant session-scoped confirmation for a destructive tool.
    This resets when the server restarts — by design.
    """
    confirm_destructive(body.user_id, tool_name)
    return {
        "confirmed": True,
        "tool": tool_name,
        "user_id": body.user_id,
        "scope": "session",
        "note": "Confirmation is session-scoped. Re-confirm after server restart."
    }
