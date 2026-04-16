import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Optional

from orchestration.agents.base import BaseAgent
from core.logging import get_logger

log = get_logger(__name__)

class AgentRegistry:
    """Singleton registry for managing specialist agents."""
    
    _instance = None
    _agents: dict[str, BaseAgent] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AgentRegistry, cls).__new__(cls)
        return cls._instance

    def register(self, agent: BaseAgent):
        """Register an agent instance."""
        if agent.name in self._agents:
            log.warning("agent.registry.collision", name=agent.name)
        self._agents[agent.name] = agent
        log.info("agent.registered", name=agent.name, tools=agent.tools)

    def get(self, name: str) -> Optional[BaseAgent]:
        """Retrieve an agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[dict]:
        """Return a list of all registered agents and their metadata."""
        return [
            {
                "name": agent.name,
                "description": agent.description,
                "tools": agent.tools
            }
            for agent in self._agents.values()
        ]

    def discover_agents(self):
        """Auto-discover and register agents in the definitions directory."""
        import orchestration.agents.definitions as definitions
        
        # Clear existing to allow for clean re-discovery if needed
        self._agents.clear()
        
        path = Path(definitions.__file__).parent
        for _, name, is_pkg in pkgutil.iter_modules([str(path)]):
            full_module_name = f"orchestration.agents.definitions.{name}"
            try:
                module = importlib.import_module(full_module_name)
                # Find all classes that inherit from BaseAgent
                for _, obj in inspect.getmembers(module):
                    if (inspect.isclass(obj) and 
                        issubclass(obj, BaseAgent) and 
                        obj is not BaseAgent):
                        # Instantiate and register the agent
                        # We assume agents can be instantiated without arguments 
                        # or have a standard implementation.
                        try:
                            instance = obj()
                            self.register(instance)
                        except Exception as e:
                            log.error("agent.instantiation.failed", class_name=obj.__name__, error=str(e))
            except Exception as e:
                log.error("agent.discovery.failed", module=full_module_name, error=str(e))

# Global singleton instance
registry = AgentRegistry()

# Initialize discovery at import time as requested
# Note: This requires orchestration.agents.definitions package to exist.
try:
    # Ensure the package is importable
    import orchestration.agents.definitions
    registry.discover_agents()
except ImportError:
    log.warning("agent.discovery.skipped", reason="definitions package missing")
except Exception as e:
    log.error("agent.discovery.error", error=str(e))
