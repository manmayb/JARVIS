"""Configuration settings.

Dependencies used by this project include: anthropic, fastapi, pydantic,
pydantic-settings, aiofiles, httpx, sympy, aiosqlite.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    anthropic_api_key: str
    app_env: str = "development"
    log_level: str = "INFO"

    tool_timeout_seconds: int = 10
    max_retries_per_tool: int = 2
    max_steps: int = 12
    global_timeout_seconds: int = 200
    retry_budget_threshold: float = 0.80
    db_path: str = "jarvis.db"

    # Phase 1 — Memory
    enable_episodic_memory: bool = True
    enable_semantic_memory: bool = True

    # Phase 2 — Redis (optional, falls back to in-memory)
    redis_url: Optional[str] = None

    # Phase 2 — Caching
    llm_cache_ttl: int = 600        # seconds
    tool_cache_ttl: int = 300

    # Phase 3 — Planner
    enable_planner: bool = True

    # ── Integration credentials (all optional) ──
    # Slack
    slack_bot_token: Optional[str] = None

    # Google Calendar (path to OAuth2 credentials JSON)
    google_calendar_credentials_path: Optional[str] = None

    # Email / SMTP
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None

    # Notion
    notion_token: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()