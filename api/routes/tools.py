from fastapi import APIRouter
from tools.registry import list_tools, get_tool
from tools.sandbox import approve_tool, confirm_destructive
from core.errors import ToolNotFoundError
from core.schemas import APIResponse
from core.exceptions import ResourceNotFound, ValidationException
from pydantic import BaseModel

router = APIRouter()

@router.get("/tools", response_model=APIResponse)
async def get_tools():
    return APIResponse(success=True, data=[t.model_dump() for t in list_tools()])

class ApproveRequest(BaseModel):
    user_id: str

def _get_tool_spec(tool_name: str):
    """Resolve the tool spec, raising ResourceNotFound if not found."""
    try:
        spec, _ = get_tool(tool_name)
        return spec
    except ToolNotFoundError:
        raise ResourceNotFound(f"Tool '{tool_name}' not found.")

@router.post("/tools/{tool_name}/approve", response_model=APIResponse)
async def approve(tool_name: str, body: ApproveRequest):
    spec = _get_tool_spec(tool_name)
    if spec.permission_tier != "write":
        raise ValidationException(
            f"Tool '{tool_name}' has tier '{spec.permission_tier}', expected 'write'."
        )
    approve_tool(body.user_id, tool_name)
    return APIResponse(
        success=True, 
        data={"approved": True, "tool": tool_name}, 
        message="Interaction protocol authorized"
    )

@router.post("/tools/{tool_name}/confirm", response_model=APIResponse)
async def confirm_tool(tool_name: str, body: ApproveRequest):
    spec = _get_tool_spec(tool_name)
    if spec.permission_tier != "destructive":
        raise ValidationException(
            f"Tool '{tool_name}' has tier '{spec.permission_tier}', expected 'destructive'."
        )
    confirm_destructive(body.user_id, tool_name)
    return APIResponse(
        success=True,
        data={"confirmed": True, "tool": tool_name, "scope": "session"},
        message="Destructive protocol confirmed"
    )
