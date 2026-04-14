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
                                reason=f"First use of write tool '{spec.name}'")
    return PermissionResult(allowed=False, requires_confirmation=True,
                            reason=f"Destructive tool '{spec.name}' requires confirmation")

def approve_tool(user_id: str, tool_name: str):
    _AUTO_APPROVED.setdefault(user_id, set()).add(tool_name)
