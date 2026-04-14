from typing import Callable
from tools.schemas import ToolSpec
from core.errors import ToolNotFoundError

_REGISTRY: dict[str, tuple[ToolSpec, Callable]] = {}

def register_tool(name: str, description: str, parameters: dict,
                  permission_tier: str, task_types: list[str],
                  rate_limit_per_minute: int = 20,
                  timeout_seconds: int = 10,
                  dry_run_supported: bool = False):
    def decorator(fn: Callable) -> Callable:
        spec = ToolSpec(
            name=name, description=description, parameters=parameters,
            permission_tier=permission_tier, task_types=task_types,
            rate_limit_per_minute=rate_limit_per_minute,
            timeout_seconds=timeout_seconds,
            dry_run_supported=dry_run_supported,
        )
        _REGISTRY[name] = (spec, fn)
        return fn
    return decorator

def get_tool(name: str) -> tuple[ToolSpec, Callable]:
    if name not in _REGISTRY:
        raise ToolNotFoundError(f"Tool '{name}' not registered")
    return _REGISTRY[name]

def list_tools() -> list[ToolSpec]:
    return [spec for spec, _ in _REGISTRY.values()]

def load_all_tools():
    import tools.definitions.web_search   # noqa
    import tools.definitions.calculator   # noqa
    import tools.definitions.file_ops     # noqa
    import tools.definitions.python_exec  # noqa
