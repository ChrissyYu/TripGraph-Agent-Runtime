"""Central registry for tool discovery and schema export."""

import importlib
import pkgutil
from typing import Self

from core.logging import get_logger
from schemas.tool import ToolDefinition
from tools.base import BaseTool
from tools.decorator import clear_pending_tools, get_pending_tools

logger = get_logger(__name__)


class ToolRegistry:
    """In-process tool registry with auto-discovery support."""

    def __init__(self, *, auto_discover: bool = False) -> None:
        self._tools: dict[str, BaseTool] = {}
        if auto_discover:
            self.discover()

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def register_many(self, tools: list[BaseTool]) -> None:
        for item in tools:
            self.register(item)

    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            available = ", ".join(self.list_names()) or "(none)"
            raise KeyError(f"Unknown tool: {name}. Available: {available}") from exc

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def get_definitions(self) -> list[ToolDefinition]:
        return [tool.get_definition() for tool in self._tools.values()]

    def to_openai_schemas(self) -> list[dict]:
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def discover(self, package: str = "tools.builtin") -> int:
        """Import package submodules and register all @tool-decorated functions."""
        pkg = importlib.import_module(package)
        count = 0

        for item in get_pending_tools():
            if not self.has(item.name):
                self.register(item)
                count += 1

        if hasattr(pkg, "__path__"):
            for module_info in pkgutil.iter_modules(pkg.__path__, prefix=f"{package}."):
                module = importlib.import_module(module_info.name)
                count += self._collect_from_module(module)

        clear_pending_tools()
        logger.info("Discovered %d tools from %s", count, package)
        return count

    def _collect_from_module(self, module: object) -> int:
        count = 0
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name, None)
            instance = getattr(attr, "_tool_instance", None)
            if instance is not None and hasattr(instance, "name"):
                if not self.has(instance.name):
                    self.register(instance)
                    count += 1
        return count

    @classmethod
    def default(cls) -> Self:
        """Create a registry with all built-in tools auto-discovered."""
        registry = cls()
        registry.discover("tools.builtin")
        return registry

