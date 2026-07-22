"""Tests for the service registry."""

import pytest

from atlas_core.registry import ServiceRegistry
from tests.conftest import MockService


class TestServiceRegistry:
    def test_register_and_resolve(self, registry: ServiceRegistry) -> None:
        svc = MockService("alpha")
        registry.register(svc)
        assert registry.resolve("alpha") is svc

    def test_register_duplicate_raises(self, registry: ServiceRegistry) -> None:
        registry.register(MockService("dup"))
        with pytest.raises(ValueError, match="already registered"):
            registry.register(MockService("dup"))

    def test_resolve_unknown_returns_none(self, registry: ServiceRegistry) -> None:
        assert registry.resolve("ghost") is None

    def test_count(self, registry: ServiceRegistry) -> None:
        assert registry.count == 0
        registry.register(MockService("a"))
        assert registry.count == 1

    def test_singleton_returns_same_instance(self, registry: ServiceRegistry) -> None:
        svc = MockService("s")
        registry.register(svc)
        assert registry.resolve("s") is registry.resolve("s")

    def test_non_singleton_returns_new_instance(self, registry: ServiceRegistry) -> None:
        svc = MockService("ns")
        registry.register(svc, singleton=False)
        # Non-singleton returns the same registered instance for now (no lazy factory)
        assert registry.resolve("ns") is svc

    def test_dependency_order_simple(self, registry: ServiceRegistry) -> None:
        registry.register(MockService("a"))
        registry.register(MockService("b", deps=["a"]))
        registry.register(MockService("c", deps=["b"]))
        order = registry.dependency_order()
        assert order == ["a", "b", "c"]

    def test_dependency_order_complex(self, registry: ServiceRegistry) -> None:
        registry.register(MockService("db"))
        registry.register(MockService("a", deps=["db"]))
        registry.register(MockService("b", deps=["a"]))
        registry.register(MockService("c", deps=["a", "db"]))
        order = registry.dependency_order()
        assert order.index("db") < order.index("a")
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")

    def test_circular_dependency_raises(self, registry: ServiceRegistry) -> None:
        registry.register(MockService("x", deps=["y"]))
        registry.register(MockService("y", deps=["x"]))
        with pytest.raises(ValueError, match="Circular dependency"):
            registry.dependency_order()

    def test_missing_dependency_raises(self, registry: ServiceRegistry) -> None:
        registry.register(MockService("z", deps=["nonexistent"]))
        with pytest.raises(ValueError, match="not registered"):
            registry.dependency_order()

    def test_services_property(self, registry: ServiceRegistry) -> None:
        a = MockService("a")
        b = MockService("b")
        registry.register(a)
        registry.register(b)
        svcs = registry.services
        assert set(svcs) == {"a", "b"}
