"""Tests for beddel.cli.config — dev mode and dashboard URL resolution."""

from __future__ import annotations

import json
from pathlib import Path

from beddel.cli import config as config_mod

# ---------------------------------------------------------------------------
# resolve_dev_mode
# ---------------------------------------------------------------------------


class TestResolveDevModeDefault:
    """Default is True (dev mode) when no config exists."""

    def test_returns_true_when_no_config(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]
        # No project config
        mp.setattr(config_mod, "find_project_config", lambda: None)
        # Global config does not exist
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", tmp_path / "missing.json")

        assert config_mod.resolve_dev_mode() is True


class TestResolveDevModeGlobal:
    """Global config sets dev mode."""

    def test_reads_false_from_global(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]
        mp.setattr(config_mod, "find_project_config", lambda: None)

        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"dev": False}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_dev_mode() is False

    def test_reads_true_from_global(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]
        mp.setattr(config_mod, "find_project_config", lambda: None)

        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"dev": True}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_dev_mode() is True


class TestResolveDevModeProjectWins:
    """Project config overrides global config."""

    def test_project_false_overrides_global_true(
        self, monkeypatch: object, tmp_path: Path
    ) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # Project config: dev=False
        project_cfg = tmp_path / ".beddel.json"
        project_cfg.write_text(json.dumps({"dev": False}))
        mp.setattr(config_mod, "find_project_config", lambda: project_cfg)

        # Global config: dev=True
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"dev": True}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_dev_mode() is False

    def test_project_true_overrides_global_false(
        self, monkeypatch: object, tmp_path: Path
    ) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        project_cfg = tmp_path / ".beddel.json"
        project_cfg.write_text(json.dumps({"dev": True}))
        mp.setattr(config_mod, "find_project_config", lambda: project_cfg)

        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"dev": False}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_dev_mode() is True


class TestResolveDevModeMissingKey:
    """Missing 'dev' key falls through to next layer or default."""

    def test_missing_in_project_falls_to_global(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # Project config without dev key
        project_cfg = tmp_path / ".beddel.json"
        project_cfg.write_text(json.dumps({"kits_paths": []}))
        mp.setattr(config_mod, "find_project_config", lambda: project_cfg)

        # Global config with dev=False
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"dev": False}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_dev_mode() is False

    def test_missing_everywhere_returns_default(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # Project config without dev key
        project_cfg = tmp_path / ".beddel.json"
        project_cfg.write_text(json.dumps({"kits_paths": []}))
        mp.setattr(config_mod, "find_project_config", lambda: project_cfg)

        # Global config without dev key
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"kits_paths": []}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_dev_mode() is True


# ---------------------------------------------------------------------------
# resolve_dashboard_url
# ---------------------------------------------------------------------------


class TestResolveDashboardUrlDevDefault:
    """Default URL for dev mode is localhost:3000."""

    def test_returns_localhost_when_dev_mode(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]
        mp.setattr(config_mod, "find_project_config", lambda: None)
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", tmp_path / "missing.json")

        # dev defaults to True → dashboard defaults to localhost
        assert config_mod.resolve_dashboard_url() == "http://localhost:3000"


class TestResolveDashboardUrlRemoteDefault:
    """Default URL for remote mode is connect.beddel.com.br."""

    def test_returns_remote_url_when_not_dev(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # Global config: dev=False, no dashboard_url
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"dev": False}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)
        mp.setattr(config_mod, "find_project_config", lambda: None)

        assert config_mod.resolve_dashboard_url() == "https://connect.beddel.com.br"


class TestResolveDashboardUrlFromConfig:
    """Explicit dashboard_url in config overrides defaults."""

    def test_reads_from_global(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]
        mp.setattr(config_mod, "find_project_config", lambda: None)

        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"dashboard_url": "https://custom.example.com"}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_dashboard_url() == "https://custom.example.com"

    def test_reads_from_project(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        project_cfg = tmp_path / ".beddel.json"
        project_cfg.write_text(json.dumps({"dashboard_url": "https://project.example.com"}))
        mp.setattr(config_mod, "find_project_config", lambda: project_cfg)

        # Global has a different URL — project should win
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"dashboard_url": "https://global.example.com"}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_dashboard_url() == "https://project.example.com"


class TestResolveDashboardUrlMissingKey:
    """Missing dashboard_url falls through to default based on dev mode."""

    def test_missing_in_project_falls_to_global(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # Project config without dashboard_url
        project_cfg = tmp_path / ".beddel.json"
        project_cfg.write_text(json.dumps({"kits_paths": []}))
        mp.setattr(config_mod, "find_project_config", lambda: project_cfg)

        # Global config with dashboard_url
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"dashboard_url": "https://from-global.example.com"}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        assert config_mod.resolve_dashboard_url() == "https://from-global.example.com"

    def test_missing_everywhere_returns_dev_default(
        self, monkeypatch: object, tmp_path: Path
    ) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # No dashboard_url anywhere, dev mode defaults to True
        mp.setattr(config_mod, "find_project_config", lambda: None)
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", tmp_path / "missing.json")

        assert config_mod.resolve_dashboard_url() == "http://localhost:3000"

    def test_missing_everywhere_returns_remote_default(
        self, monkeypatch: object, tmp_path: Path
    ) -> None:
        mp = monkeypatch  # type: ignore[assignment]

        # No dashboard_url, but dev=False in global
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"dev": False}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)
        mp.setattr(config_mod, "find_project_config", lambda: None)

        assert config_mod.resolve_dashboard_url() == "https://connect.beddel.com.br"


# ---------------------------------------------------------------------------
# load_project_config / load_global_config preserve new keys
# ---------------------------------------------------------------------------


class TestLoadProjectConfigPreservesNewKeys:
    """load_project_config extracts dev and dashboard_url."""

    def test_preserves_dev_and_dashboard_url(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / ".beddel.json"
        cfg_file.write_text(json.dumps({"dev": False, "dashboard_url": "https://example.com"}))

        result = config_mod.load_project_config(cfg_file)

        assert result["dev"] is False
        assert result["dashboard_url"] == "https://example.com"

    def test_missing_keys_use_sentinel(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / ".beddel.json"
        cfg_file.write_text(json.dumps({"kits_paths": []}))

        result = config_mod.load_project_config(cfg_file)

        assert result["dev"] is config_mod._SENTINEL
        assert result["dashboard_url"] is config_mod._SENTINEL


class TestLoadGlobalConfigPreservesNewKeys:
    """load_global_config extracts dev and dashboard_url."""

    def test_preserves_dev_and_dashboard_url(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(
            json.dumps({"dev": True, "dashboard_url": "https://global.example.com"})
        )
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        result = config_mod.load_global_config()

        assert result["dev"] is True
        assert result["dashboard_url"] == "https://global.example.com"

    def test_missing_keys_use_sentinel(self, monkeypatch: object, tmp_path: Path) -> None:
        mp = monkeypatch  # type: ignore[assignment]
        global_cfg = tmp_path / "config.json"
        global_cfg.write_text(json.dumps({"flows_paths": []}))
        mp.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)

        result = config_mod.load_global_config()

        assert result["dev"] is config_mod._SENTINEL
        assert result["dashboard_url"] is config_mod._SENTINEL
