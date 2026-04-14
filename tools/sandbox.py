from tools.schemas import ToolSpec
from pydantic import BaseModel

_AUTO_APPROVED: dict[str, set[str]] = {}
# Session-scoped only — intentionally cleared on server restart
# Destructive tools must be re-confirmed after every restart
_SESSION_CONFIRMED: dict[str, set[str]] = {}  # user_id → {tool_name}

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
        return PermissionResult(
            allowed=False,
            requires_confirmation=True,
            reason=(
                f"Write tool '{spec.name}' requires one-time approval. "
                f"Call: POST /tools/{spec.name}/approve"
            )
        )

    if spec.permission_tier == "destructive":
        if spec.name in _SESSION_CONFIRMED.get(user_id, set()):
            return PermissionResult(allowed=True)
        return PermissionResult(
            allowed=False,
            requires_confirmation=True,
            reason=(
                f"Destructive tool '{spec.name}' requires confirmation. "
                f"Call: POST /tools/{spec.name}/confirm — "
                f"note: confirmation resets on server restart."
            )
        )

    return PermissionResult(
        allowed=False,
        reason=f"Unknown permission tier: {spec.permission_tier}"
    )

def approve_tool(user_id: str, tool_name: str):
    _AUTO_APPROVED.setdefault(user_id, set()).add(tool_name)

def confirm_destructive(user_id: str, tool_name: str) -> None:
    """Grant session-scoped confirmation for a destructive tool."""
    _SESSION_CONFIRMED.setdefault(user_id, set()).add(tool_name)
