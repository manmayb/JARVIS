from pydantic import BaseModel, Field
from typing import Any, Optional
from datetime import datetime
import uuid

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

    _steps_completed: int = 0
    _tool_calls_log: list = []
    _last_thought: str = ""

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

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str
    trace_id: str
    steps_taken: Optional[int]
    tools_used: list[str]
    status: str
