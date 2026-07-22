"""Tests for the configuration subsystem."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas_core.config import AtlasConfig, ConfigurationManager, EnvLoader, YamlConfigLoader


class TestAtlasConfig:
    def test_defaults(self) -> None:
        cfg = AtlasConfig()
        assert cfg.app_name == "Atlas"
        assert cfg.version == "0.1.0"
        assert cfg.debug is False
        assert cfg.log_level == "INFO"

    def test_env_override(self) -> None:
        cfg = AtlasConfig(app_name="Override", debug=True, log_level="DEBUG")
        assert cfg.app_name == "Override"
        assert cfg.debug is True
        assert cfg.log_level == "DEBUG"

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(ValidationError):
            AtlasConfig(log_level="TRACE")


class TestEnvLoader:
    def test_load_returns_env(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("ATLAS_APP_NAME=EnvTest\nATLAS_DEBUG=true\n")
        loader = EnvLoader(env_file)
        env = loader.load()
        # dotenv populates os.environ; we just verify it runs
        assert isinstance(env, dict)


class TestYamlConfigLoader:
    def test_load_defaults(self, tmp_config_dir: Path, default_yaml: Path) -> None:
        loader = YamlConfigLoader(tmp_config_dir)
        data = loader.load_defaults()
        assert data["app_name"] == "TestAtlas"
        assert data["version"] == "9.9.9"

    def test_load_missing_defaults(self, tmp_config_dir: Path) -> None:
        loader = YamlConfigLoader(tmp_config_dir)
        data = loader.load_defaults()
        assert data == {}

    def test_load_profile(self, tmp_config_dir: Path) -> None:
        profile = tmp_config_dir / "staging.yaml"
        profile.write_text("debug: true\nlog_level: WARNING\n")
        loader = YamlConfigLoader(tmp_config_dir)
        data = loader.load_profile("staging")
        assert data["debug"] is True
        assert data["log_level"] == "WARNING"


class TestConfigurationManager:
    def test_initialize_with_default_yaml(self, tmp_config_dir: Path, default_yaml: Path) -> None:
        mgr = ConfigurationManager(tmp_config_dir)
        cfg = mgr.initialize()
        assert cfg.app_name == "TestAtlas"
        assert cfg.version == "9.9.9"

    def test_initialize_fallback_defaults(self, tmp_config_dir: Path) -> None:
        mgr = ConfigurationManager(tmp_config_dir)
        cfg = mgr.initialize()
        assert cfg.app_name == "Atlas"  # pydantic default
        assert cfg.log_level == "INFO"

    def test_config_property_before_init_raises(self, tmp_path: Path) -> None:
        mgr = ConfigurationManager(tmp_path / "nonexistent")
        with pytest.raises(RuntimeError):
            _ = mgr.config

    def test_initialize_merges_profile(self, tmp_config_dir: Path) -> None:
        (tmp_config_dir / "default.yaml").write_text(
            "app_name: Base\nlog_level: INFO\n"
        )
        (tmp_config_dir / "development.yaml").write_text(
            "log_level: DEBUG\ndebug: true\n"
        )
        mgr = ConfigurationManager(tmp_config_dir)
        cfg = mgr.initialize()
        assert cfg.app_name == "Base"
        assert cfg.log_level == "DEBUG"
        assert cfg.debug is True
