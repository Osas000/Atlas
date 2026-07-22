"""Configuration loading, validation, and management."""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator


class AtlasConfig(BaseModel):
    app_name: str = "Atlas"
    version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"
    log_dir: str = "logs"
    data_dir: str = "data"
    database_url: str = "sqlite:///data/atlas.db"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            msg = f"Invalid log_level: {v}. Must be one of {allowed}"
            raise ValueError(msg)
        return upper


class EnvLoader:
    def __init__(self, env_path: Optional[Path] = None) -> None:
        self._env_path = env_path or Path(".env")

    def load(self) -> dict[str, str]:
        if self._env_path.exists():
            load_dotenv(self._env_path, override=True)
        return {k: v for k, v in os.environ.items()}


class YamlConfigLoader:
    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir

    def load_defaults(self) -> dict[str, Any]:
        path = self._config_dir / "default.yaml"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}

    def load_profile(self, profile: str = "development") -> dict[str, Any]:
        path = self._config_dir / f"{profile}.yaml"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}


class ConfigurationManager:
    def __init__(self, config_dir: str | Path = "config") -> None:
        self._config_dir = Path(config_dir)
        self._config: Optional[AtlasConfig] = None

    def initialize(self) -> AtlasConfig:
        EnvLoader().load()

        yaml_loader = YamlConfigLoader(self._config_dir)
        raw: dict[str, Any] = {}
        raw.update(yaml_loader.load_defaults())

        env_profile = os.environ.get("ATLAS_ENV", "development")
        raw.update(yaml_loader.load_profile(env_profile))

        env_overrides = {
            "app_name": os.environ.get("ATLAS_APP_NAME"),
            "debug": self._parse_bool(os.environ.get("ATLAS_DEBUG")),
            "log_level": os.environ.get("ATLAS_LOG_LEVEL"),
            "log_dir": os.environ.get("ATLAS_LOG_DIR"),
            "data_dir": os.environ.get("ATLAS_DATA_DIR"),
            "database_url": os.environ.get("ATLAS_DATABASE_URL"),
        }
        for key, value in env_overrides.items():
            if value is not None:
                raw[key] = value

        self._config = AtlasConfig(**raw)
        return self._config

    @property
    def config(self) -> AtlasConfig:
        if self._config is None:
            raise RuntimeError("ConfigurationManager has not been initialized")
        return self._config

    @staticmethod
    def _parse_bool(value: Optional[str]) -> Optional[bool]:
        if value is None:
            return None
        return value.strip().lower() in ("1", "true", "yes")
