"""Unit tests for ``beddel kit install`` CLI command.

Uses click.testing.CliRunner to invoke commands in isolation.

Note: ``beddel kit list`` tests moved to ``test_kit_flow_commands.py``
after refactoring to IndexStore-backed implementation (Story BC8.2).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from beddel.cli.commands import cli

# ---------------------------------------------------------------------------
# beddel kit install
# ---------------------------------------------------------------------------


class TestKitInstall:
    """Tests for ``beddel kit install`` with temp kit directories."""

    def test_kit_install_valid(self, tmp_path: Path) -> None:
        """Installing a valid kit copies it and prints success."""
        kit_src = tmp_path / "my-kit"
        kit_src.mkdir()
        (kit_src / "kit.yaml").write_text("name: my-kit\nversion: '0.1.0'\ndescription: Test\n")

        runner = CliRunner()
        with runner.isolated_filesystem() as td:
            result = runner.invoke(cli, ["kit", "install", str(kit_src)])

            assert result.exit_code == 0
            assert "Installed" in result.output
            assert "my-kit" in result.output
            # Kit should be copied to ./kits/my-kit/
            installed = Path(td) / "kits" / "my-kit" / "kit.yaml"
            assert installed.exists()

    def test_kit_install_invalid_manifest(self, tmp_path: Path) -> None:
        """Installing a kit with invalid manifest fails with error."""
        kit_src = tmp_path / "bad-kit"
        kit_src.mkdir()
        (kit_src / "kit.yaml").write_text("not: valid\nkit: yaml\n")

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["kit", "install", str(kit_src)])

        assert result.exit_code == 1
        assert "Invalid kit manifest" in result.output

    def test_kit_install_with_dependencies(self, tmp_path: Path) -> None:
        """Installing a kit with deps calls pip install."""
        kit_src = tmp_path / "dep-kit"
        kit_src.mkdir()
        (kit_src / "kit.yaml").write_text(
            "name: dep-kit\nversion: '0.1.0'\n"
            "description: Kit with deps\n"
            "dependencies:\n  - httpx>=0.27\n"
        )

        runner = CliRunner()
        with (
            runner.isolated_filesystem(),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["kit", "install", str(kit_src)])

        assert result.exit_code == 0
        assert "Installed" in result.output
        mock_run.assert_called_once()
        # Verify pip install was called with the dependency
        call_args = mock_run.call_args[0][0]
        assert "httpx>=0.27" in call_args
