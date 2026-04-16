"""Tool registry — decorator-based registration with env-var gating.

Tools declare their required environment variables via ``requires=[...]``.
During ``load_all_tools()``, any tool whose env vars are missing or empty
is skipped so the LLM never sees it.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Callable, Optional
from tools.schemas import ToolSpec
from core.errors import ToolNotFoundError
from core.logging import get_logger

log = get_logger("tools.registry")

_REGISTRY: dict[str, tuple[ToolSpec, Callable]] = {}

# Deferred registration queue: tools register here first, then
# load_all_tools() filters by env-var availability and promotes to _REGISTRY.
_PENDING: list[tuple[ToolSpec, Callable, list[str]]] = []


def register_tool(name: str, description: str, parameters: dict,
                  permission_tier: str, task_types: list[str],
                  rate_limit_per_minute: int = 20,
                  timeout_seconds: int = 10,
                  cache_ttl_seconds: int = 0,
                  dry_run_supported: bool = False,
                  requires: Optional[list[str]] = None):
    """Decorator to register a tool with the system.

    Args:
        requires: Optional list of environment variable names that MUST be
                  set for this tool to be registered.  If any are missing or
                  empty, the tool is silently excluded from the registry so
                  the LLM never sees it.
    """
    def decorator(fn: Callable) -> Callable:
        spec = ToolSpec(
            name=name, description=description, parameters=parameters,
            permission_tier=permission_tier, task_types=task_types,
            rate_limit_per_minute=rate_limit_per_minute,
            timeout_seconds=timeout_seconds,
            cache_ttl_seconds=cache_ttl_seconds,
            dry_run_supported=dry_run_supported,
        )
        _PENDING.append((spec, fn, requires or []))
        return fn
    return decorator


# Backwards-compatible alias for the decorator name referenced in docs.
tool = register_tool


def _check_env_vars(required: list[str]) -> list[str]:
    """Return list of missing or empty env var names."""
    missing = []
    for var in required:
        val = os.environ.get(var, "").strip()
        if not val:
            missing.append(var)
    return missing


def load_all_tools():
    """Import all tool modules and promote env-var-gated tools to the registry."""
    _REGISTRY.clear()
    _PENDING.clear()

    # Import all tool definition modules — this populates _PENDING.
    # Reloading makes the registry idempotent across repeated calls.
    module_names = [
        "tools.definitions.web_search",
        "tools.definitions.calculator",
        "tools.definitions.file_ops",
        "tools.definitions.python_exec",
        "tools.definitions.calendar",
        "tools.definitions.email",
        "tools.definitions.notion",
        "tools.definitions.slack",
    ]
    for module_name in module_names:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            importlib.import_module(module_name)

    # Gate by env vars
    for spec, fn, required_vars in _PENDING:
        if required_vars:
            missing = _check_env_vars(required_vars)
            if missing:
                log.warning(
                    f"Tool '{spec.name}' not registered — missing env vars: {missing}"
                )
                continue
        _REGISTRY[spec.name] = (spec, fn)
        log.info("tool.registered", tool=spec.name)


def get_tool(name: str) -> tuple[ToolSpec, Callable]:
    if name not in _REGISTRY:
        raise ToolNotFoundError(f"Tool '{name}' not registered")
    return _REGISTRY[name]


def list_tools() -> list[ToolSpec]:
    return [spec for spec, _ in _REGISTRY.values()]
