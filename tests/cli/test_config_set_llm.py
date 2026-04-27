"""Tests for `beddel config set llm-provider` CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from beddel.cli.commands import cli


class TestConfigSetLlmProvider:
    """beddel config set llm-provider <value> writes to user_prefs."""

    def test_writes_to_user_prefs(self, tmp_path: Path) -> None:
        """Setting llm-provider calls IndexStore.set_pref and prints confirmation."""
        mock_set_pref = AsyncMock()

        with patch("beddel.adapters.index_store.IndexStore.set_pref", mock_set_pref):
            runner = CliRunner()
            result = runner.invoke(cli, ["config", "set", "llm-provider", "gemini"])

        assert result.exit_code == 0, result.output
        mock_set_pref.assert_called_once_with("llm_provider", "gemini")
        assert "Set llm-provider = gemini (stored in index.db user_prefs)" in result.output

    def test_writes_anthropic_provider(self, tmp_path: Path) -> None:
        """Accepts arbitrary string values for llm-provider."""
        mock_set_pref = AsyncMock()

        with patch("beddel.adapters.index_store.IndexStore.set_pref", mock_set_pref):
            runner = CliRunner()
            result = runner.invoke(cli, ["config", "set", "llm-provider", "anthropic"])

        assert result.exit_code == 0, result.output
        mock_set_pref.assert_called_once_with("llm_provider", "anthropic")
        assert "Set llm-provider = anthropic (stored in index.db user_prefs)" in result.output


class TestConfigSetLlmProviderFallback:
    """Falls back to config.json when index.db is unavailable."""

    def test_falls_back_to_config_json(self, tmp_path: Path) -> None:
        """When IndexStore raises, writes to config.json and prints warning."""
        mock_set_pref = AsyncMock(side_effect=Exception("index.db unavailable"))

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"kits_paths": [], "flows_paths": []}))

        with (
            patch("beddel.adapters.index_store.IndexStore.set_pref", mock_set_pref),
            patch("beddel.cli.config.GLOBAL_CONFIG_PATH", config_file),
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["config", "set", "llm-provider", "openai"])

        assert result.exit_code == 0, result.output
        assert "Warning" in result.output or "warning" in result.output.lower()
        # Verify config.json was updated
        saved = json.loads(config_file.read_text())
        assert saved["llm_provider"] == "openai"


class TestConfigSetKitsPathBackwardCompat:
    """beddel config set kits-path still works after refactor."""

    def test_sets_kits_path(self, tmp_path: Path) -> None:
        """kits-path validates directory exists and writes to config.json."""
        kits_dir = tmp_path / "kits"
        kits_dir.mkdir()

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"kits_paths": [], "flows_paths": []}))

        with patch("beddel.cli.config.GLOBAL_CONFIG_PATH", config_file):
            runner = CliRunner()
            result = runner.invoke(cli, ["config", "set", "kits-path", str(kits_dir)])

        assert result.exit_code == 0, result.output
        assert "Set kits-path" in result.output
        saved = json.loads(config_file.read_text())
        assert str(kits_dir.resolve()) in saved["kits_paths"]

    def test_kits_path_rejects_nonexistent(self, tmp_path: Path) -> None:
        """kits-path errors when directory does not exist."""
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "set", "kits-path", "/nonexistent/path/xyz"])

        assert result.exit_code != 0

    def test_sets_flows_path(self, tmp_path: Path) -> None:
        """flows-path validates directory exists and writes to config.json."""
        flows_dir = tmp_path / "flows"
        flows_dir.mkdir()

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"kits_paths": [], "flows_paths": []}))

        with patch("beddel.cli.config.GLOBAL_CONFIG_PATH", config_file):
            runner = CliRunner()
            result = runner.invoke(cli, ["config", "set", "flows-path", str(flows_dir)])

        assert result.exit_code == 0, result.output
        assert "Set flows-path" in result.output
        saved = json.loads(config_file.read_text())
        assert str(flows_dir.resolve()) in saved["flows_paths"]
