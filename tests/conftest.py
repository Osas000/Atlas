"""Shared fixtures for Atlas Core tests."""

import os
from collections.abc import Generator
from pathlib import Path
from typing import Optional

import pytest

from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.registry import ServiceRegistry

# Environment variables set by Atlas tests — saved and restored by env_snapshot
_ATLAS_ENV_KEYS = frozenset({
    "ATLAS_APP_NAME", "ATLAS_DEBUG", "ATLAS_LOG_LEVEL",
    "ATLAS_LOG_DIR", "ATLAS_DATA_DIR", "ATLAS_DATABASE_URL", "ATLAS_ENV",
})


@pytest.fixture(autouse=True)
def env_snapshot() -> Generator[None, None, None]:
    """Save / restore Atlas-related environment variables around each test."""
    snapshot = {k: os.environ.get(k) for k in _ATLAS_ENV_KEYS}
    # Also save ATLAS_ENV if present
    old_atlas_env = os.environ.pop("ATLAS_ENV", None)
    try:
        yield
    finally:
        for k in _ATLAS_ENV_KEYS:
            val = snapshot.get(k)
            if val is not None:
                os.environ[k] = val
            else:
                os.environ.pop(k, None)
        if old_atlas_env is not None:
            os.environ["ATLAS_ENV"] = old_atlas_env
        else:
            os.environ.pop("ATLAS_ENV", None)


# ------------------------------------------------------------------
# Helper: a configurable mock service
# ------------------------------------------------------------------

class MockService(IService):
    def __init__(
        self,
        name: str,
        deps: Optional[list[str]] = None,
        fail_init: bool = False,
        fail_start: bool = False,
        fail_stop: bool = False,
        fail_health: bool = False,
        health_override: bool = True,
    ) -> None:
        self._name = name
        self._deps = deps or []
        self._fail_init = fail_init
        self._fail_start = fail_start
        self._fail_stop = fail_stop
        self._fail_health = fail_health
        self._health_override = health_override
        self.initialized = False
        self.started = False
        self.stopped = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def dependencies(self) -> list[str]:
        return self._deps

    async def initialize(self) -> None:
        if self._fail_init:
            msg = f"{self._name} failed to initialize"
            raise RuntimeError(msg)
        self.initialized = True

    async def start(self) -> None:
        if self._fail_start:
            msg = f"{self._name} failed to start"
            raise RuntimeError(msg)
        self.started = True

    async def stop(self) -> None:
        if self._fail_stop:
            msg = f"{self._name} failed to stop"
            raise RuntimeError(msg)
        self.stopped = True

    async def health_check(self) -> ServiceHealth:
        if self._fail_health:
            msg = f"{self._name} health check failed"
            raise RuntimeError(msg)
        return ServiceHealth(
            healthy=self._health_override,
            state=ServiceState.RUNNING,
        )


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def registry() -> ServiceRegistry:
    return ServiceRegistry()


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.fixture
def default_yaml(tmp_config_dir: Path) -> Path:
    path = tmp_config_dir / "default.yaml"
    path.write_text(
        "app_name: TestAtlas\n"
        "version: 9.9.9\n"
        "log_level: DEBUG\n"
    )
    return path
