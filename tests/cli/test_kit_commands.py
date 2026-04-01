"""Unit tests for ``beddel kit list`` and ``beddel kit install`` CLI commands.

Uses click.testing.CliRunner to invoke commands in isolation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from beddel.cli.commands import cli

# ---------------------------------------------------------------------------
# beddel kit list
# ---------------------------------------------------------------------------


class TestKitList:
    """Tests for ``beddel kit list`` output format."""

    def test_kit_list_no_kits_found(self) -> None:
        """When no kits exist, prints 'No kits found.'."""
        from beddel.domain.kit import KitDiscoveryResult

        empty_result = KitDiscoveryResult(manifests=[], collisions=[])

        runner = CliRunner()
        with (
            patch("beddel.cli.commands._ensure_kit_paths"),
            patch(
                "beddel.tools.kits.discover_kits",
                return_value=empty_result,
            ),
        ):
            result = runner.invoke(cli, ["kit", "list"])

        assert result.exit_code == 0
        assert "No kits found" in result.output

    def test_kit_list_shows_table_headers(self, tmp_path: Path) -> None:
        """Output contains NAME, VERSION, STATUS, PATH headers."""
        from datetime import UTC, datetime

        from beddel.domain.kit import KitDiscoveryResult, KitManifest, SolutionKit

        kit = SolutionKit(
            name="test-kit",
            version="0.1.0",
            description="Test",
        )
        manifest = KitManifest(
            kit=kit,
            root_path=tmp_path,
            loaded_at=datetime.now(UTC),
        )
        discovery = KitDiscoveryResult(manifests=[manifest], collisions=[])

        runner = CliRunner()
        with (
            patch("beddel.cli.commands._ensure_kit_paths"),
            patch(
                "beddel.tools.kits.discover_kits",
                return_value=discovery,
            ),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={},
            ),
        ):
            result = runner.invoke(cli, ["kit", "list"])

        assert result.exit_code == 0
        assert "NAME" in result.output
        assert "VERSION" in result.output
        assert "STATUS" in result.output
        assert "PATH" in result.output

    def test_kit_list_shows_kit_name_and_version(self, tmp_path: Path) -> None:
        """Output contains the kit name and version."""
        from datetime import UTC, datetime

        from beddel.domain.kit import KitDiscoveryResult, KitManifest, SolutionKit

        kit = SolutionKit(
            name="my-cool-kit",
            version="1.2.3",
            description="Cool kit",
        )
        manifest = KitManifest(
            kit=kit,
            root_path=tmp_path,
            loaded_at=datetime.now(UTC),
        )
        discovery = KitDiscoveryResult(manifests=[manifest], collisions=[])

        runner = CliRunner()
        with (
            patch("beddel.cli.commands._ensure_kit_paths"),
            patch(
                "beddel.tools.kits.discover_kits",
                return_value=discovery,
            ),
            patch(
                "beddel.tools.kits.load_kit",
                return_value={},
            ),
        ):
            result = runner.invoke(cli, ["kit", "list"])

        assert result.exit_code == 0
        assert "my-cool-kit" in result.output
        assert "1.2.3" in result.output
        assert "loaded" in result.output

    def test_kit_list_missing_deps_status(self, tmp_path: Path) -> None:
        """Kit with missing deps shows 'missing-deps' status."""
        from datetime import UTC, datetime

        from beddel.domain.errors import KitDependencyError
        from beddel.domain.kit import KitDiscoveryResult, KitManifest, SolutionKit

        kit = SolutionKit(
            name="broken-kit",
            version="0.1.0",
            description="Broken",
            dependencies=["nonexistent>=1.0"],
        )
        manifest = KitManifest(
            kit=kit,
            root_path=tmp_path,
            loaded_at=datetime.now(UTC),
        )
        discovery = KitDiscoveryResult(manifests=[manifest], collisions=[])

        runner = CliRunner()
        with (
            patch("beddel.cli.commands._ensure_kit_paths"),
            patch(
                "beddel.tools.kits.discover_kits",
                return_value=discovery,
            ),
            patch(
                "beddel.tools.kits.load_kit",
                side_effect=KitDependencyError(
                    code="BEDDEL-KIT-653",
                    message="Missing deps",
                    missing_packages=["nonexistent>=1.0"],
                ),
            ),
        ):
            result = runner.invoke(cli, ["kit", "list"])

        assert result.exit_code == 0
        assert "missing-deps" in result.output


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
