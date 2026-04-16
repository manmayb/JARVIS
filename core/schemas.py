from datetime import datetime
from typing import Any, Generic, Optional, TypeVar, Union
import uuid

from pydantic import BaseModel, Field, PrivateAttr

T = TypeVar("T")

class APIResponse(BaseModel, Generic[T]):
    """Standard success/error wrapper for all JARVIS API responses."""
    success: bool
    message: Optional[str] = None
    data: Optional[T] = None
    error_code: Optional[int] = None

class PaginatedResponse(APIResponse, Generic[T]):
    """Common structure for all paginated lists in the system."""
    total: int
    page: int
    limit: int

class Message(BaseModel):
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class TaskRequest(BaseModel):
    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    user_input: str
    session_id: str
    user_id: str = "default_user"
    trace_id: str = Field(default_factory=lambda: f"tr_{uuid.uuid4().hex[:12]}")
    allowed_tools: Optional[list[str]] = None

    # Private mutable state — isolated per instance, excluded from serialization
    _steps_completed: int = PrivateAttr(default=0)
    _tool_calls_log: list = PrivateAttr(default_factory=list)
    _last_thought: str = PrivateAttr(default="")

class TaskResult(BaseModel):
    task_id: str
    final_answer: str
    status: str
    steps_taken: Optional[int] = None
    tool_calls_log: list[dict] = []
    agent_plan: list[dict] = []
    trace_id: str = ""

class ThinkOutput(BaseModel):
    thought: str
    action_type: str
    tool_name: Optional[str]
    tool_parameters: Optional[dict]
    final_answer: Optional[str]


# ── HTTP Layer Schemas ──

class ChatRequest(BaseModel):
    """Inbound chat request."""
    message: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None

class ChatResponse(BaseModel):
    """Standard chat response envelope."""
    response: str
    session_id: str
    trace_id: str
    steps_taken: Optional[int] = None
    tools_used: list[str] = []
    tool_calls_made: int = 0
    agent_plan: list[dict] = []
    status: str


# No separate ErrorResponse needed; we use APIResponse[None] with success=False
