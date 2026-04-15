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
    cache_ttl_seconds: int = 0
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
