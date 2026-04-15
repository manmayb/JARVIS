"""Core Pydantic schemas shared across the JARVIS V4 system."""

from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel, Field, PrivateAttr

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
    status: str


class ErrorResponse(BaseModel):
    """Standard error envelope returned on all 4xx/5xx chat failures."""
    error: str
    error_code: str
    trace_id: str
    session_id: Optional[str] = None
