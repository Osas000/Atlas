"""Shared utility functions for the Atlas Core."""

from pathlib import Path
from typing import Optional


def ensure_directory(path: str | Path) -> Path:
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def find_project_root(marker: str = "pyproject.toml") -> Optional[Path]:
    candidate = Path.cwd()
    for _ in range(10):
        if (candidate / marker).exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            return None
        candidate = parent
    return None
