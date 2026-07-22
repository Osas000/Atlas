"""Service registry with dependency resolution and lifecycle tracking."""

from dataclasses import dataclass, field
from typing import Optional

from atlas_core.interfaces import IService


@dataclass
class ServiceDefinition:
    service: IService
    dependencies: list[str] = field(default_factory=list)
    singleton: bool = True


class ServiceRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ServiceDefinition] = {}
        self._instances: dict[str, IService] = {}

    def register(
        self,
        service: IService,
        dependencies: Optional[list[str]] = None,
        singleton: bool = True,
    ) -> None:
        name = service.name
        if name in self._definitions:
            raise ValueError(f"Service '{name}' is already registered")
        resolved = list(service.dependencies) if dependencies is None else dependencies
        self._definitions[name] = ServiceDefinition(
            service=service,
            dependencies=resolved,
            singleton=singleton,
        )

    def resolve(self, name: str) -> Optional[IService]:
        definition = self._definitions.get(name)
        if definition is None:
            return None
        if definition.singleton:
            if name not in self._instances:
                self._instances[name] = definition.service
            return self._instances[name]
        return definition.service

    @property
    def services(self) -> dict[str, ServiceDefinition]:
        return dict(self._definitions)

    @property
    def count(self) -> int:
        return len(self._definitions)

    def dependency_order(self) -> list[str]:
        visited: set[str] = set()
        result: list[str] = []

        def visit(name: str, path: set[str]) -> None:
            if name in path:
                cycle = " -> ".join(list(path) + [name])
                raise ValueError(f"Circular dependency detected: {cycle}")
            if name in visited:
                return
            path.add(name)
            definition = self._definitions.get(name)
            if definition is not None:
                for dep in definition.dependencies:
                    if dep not in self._definitions:
                        raise ValueError(
                            f"Service '{name}' depends on '{dep}' which is not registered"
                        )
                    visit(dep, path)
            path.remove(name)
            visited.add(name)
            result.append(name)

        for sname in self._definitions:
            if sname not in visited:
                visit(sname, set())

        return result
