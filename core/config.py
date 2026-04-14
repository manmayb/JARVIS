from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    anthropic_api_key: str
    app_env: str = "development"
    log_level: str = "INFO"

    tool_timeout_seconds: int = 10
    max_retries_per_tool: int = 2
    max_steps: int = 12
    global_timeout_seconds: int = 200
    retry_budget_threshold: float = 0.80

    class Config:
        env_file = ".env"

settings = Settings()
