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
