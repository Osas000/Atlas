"""Plugin and module discovery system.

In Phase 1 this is a minimal skeleton. The full dynamic-discovery
mechanism will be implemented in a later phase when the plugin API is
stable.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from atlas_core.interfaces import IPlugin


@dataclass
class ModuleDefinition:
    name: str
    version: str = "0.1.0"
    module_path: Optional[Path] = None
    plugin_class: Optional[type[IPlugin]] = None
    dependencies: list[str] = field(default_factory=list)
    enabled: bool = True


class ModuleLoader:
    def __init__(self) -> None:
        self._modules: dict[str, ModuleDefinition] = {}

    def register(self, definition: ModuleDefinition) -> None:
        if definition.name in self._modules:
            raise ValueError(f"Module '{definition.name}' is already registered")
        self._modules[definition.name] = definition

    def discover(self, plugin_dirs: list[Path]) -> list[ModuleDefinition]:
        discovered: list[ModuleDefinition] = []
        for plugin_dir in plugin_dirs:
            if not plugin_dir.is_dir():
                continue
            for entry in plugin_dir.iterdir():
                if entry.is_dir() and (entry / "__init__.py").exists():
                    discovered.append(
                        ModuleDefinition(
                            name=entry.name,
                            version="0.1.0",
                            module_path=entry,
                        )
                    )
        return discovered

    def resolve(self, name: str) -> Optional[ModuleDefinition]:
        return self._modules.get(name)

    @property
    def modules(self) -> dict[str, ModuleDefinition]:
        return dict(self._modules)
