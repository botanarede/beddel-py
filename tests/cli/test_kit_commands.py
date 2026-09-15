"""Unit tests for ``beddel kit install`` CLI command.

Uses click.testing.CliRunner to invoke commands in isolation.

Note: ``beddel kit list`` tests moved to ``test_kit_flow_commands.py``
after refactoring to IndexStore-backed implementation (Story BC8.2).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from beddel.cli.commands import cli
from beddel.cli.init import install_requirements, resolve_install_command

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
        """Installing a kit with deps runs the resolved installer once."""
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
        # Verify the requirement reached the installer command
        call_args = mock_run.call_args[0][0]
        assert "httpx>=0.27" in call_args

    def test_kit_install_dependency_failure_exits(self, tmp_path: Path) -> None:
        """A failing installer aborts the kit installation."""
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
            mock_run.return_value = MagicMock(returncode=1, stderr="boom")
            result = runner.invoke(cli, ["kit", "install", str(kit_src)])

        assert result.exit_code == 1
        assert "Failed to install dependencies" in result.output


class TestResolveInstallCommand:
    """Backend selection for kit requirement installation."""

    def test_prefers_uv_when_available(self) -> None:
        """With uv on PATH the command targets the running interpreter."""
        with patch("beddel.cli.init.shutil.which", return_value="/usr/bin/uv"):
            command = resolve_install_command(["httpx>=0.27"])

        assert command[:5] == ["/usr/bin/uv", "pip", "install", "--python", sys.executable]
        assert command[-1] == "httpx>=0.27"
        assert "--quiet" not in command

    def test_uv_quiet_flag(self) -> None:
        """Quiet mode is forwarded to uv."""
        with patch("beddel.cli.init.shutil.which", return_value="/usr/bin/uv"):
            command = resolve_install_command(["httpx>=0.27"], quiet=True)

        assert "--quiet" in command

    def test_falls_back_to_pip_module(self) -> None:
        """Without uv, the interpreter's own pip module is used."""
        with (
            patch("beddel.cli.init.shutil.which", return_value=None),
            patch("beddel.cli.init.importlib.util.find_spec", return_value=object()),
        ):
            command = resolve_install_command(["httpx>=0.27"])

        assert command[:4] == [sys.executable, "-m", "pip", "install"]
        assert command[-1] == "httpx>=0.27"

    def test_raises_when_no_backend_available(self) -> None:
        """A uv-managed environment without pip and without uv fails loudly."""
        with (
            patch("beddel.cli.init.shutil.which", return_value=None),
            patch("beddel.cli.init.importlib.util.find_spec", return_value=None),
            pytest.raises(RuntimeError, match="No Python package installer available"),
        ):
            resolve_install_command(["httpx>=0.27"])

    def test_install_requirements_reports_missing_backend(self) -> None:
        """The failure is surfaced to the user instead of raising."""
        with (
            patch("beddel.cli.init.shutil.which", return_value=None),
            patch("beddel.cli.init.importlib.util.find_spec", return_value=None),
        ):
            assert install_requirements(["httpx>=0.27"]) is False

    def test_install_requirements_noop_without_packages(self) -> None:
        """No packages means nothing is executed."""
        with patch("beddel.cli.init.subprocess.run") as mock_run:
            assert install_requirements([]) is True

        mock_run.assert_not_called()
