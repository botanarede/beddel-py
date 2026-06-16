"""Unit tests for interactive kit discovery (Story K3A.6).

Tests: _discover_remote_kits(), _interactive_kit_discovery(), and the
``beddel kit install`` no-arg / --json entry points.

All git operations and external I/O are mocked — no real network calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from beddel.cli.commands import _discover_remote_kits, _interactive_kit_discovery, cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_KIT_YAML = "name: my-test-kit\nversion: 0.1.0\ndescription: A test kit\n"
_VALID_KIT_YAML_2 = "name: agent-demo-kit\nversion: 0.2.0\ndescription: Demo agent kit\n"


def _make_fake_repo(tmp_path: Path, kits: dict[str, str]) -> Path:
    """Create fake sparse-checkout result under tmp_path/repo/kits/."""
    repo_kits = tmp_path / "repo" / "kits"
    for kit_name, content in kits.items():
        kit_dir = repo_kits / kit_name
        kit_dir.mkdir(parents=True)
        (kit_dir / "kit.yaml").write_text(content)
    return tmp_path


# ---------------------------------------------------------------------------
# _discover_remote_kits
# ---------------------------------------------------------------------------


class TestDiscoverRemoteKits:
    """Tests for _discover_remote_kits()."""

    def test_returns_valid_manifests(self, tmp_path: Path) -> None:
        """Parses valid kit.yaml files from mocked sparse-checkout result."""
        fake_repo = _make_fake_repo(tmp_path, {"my-test-kit": _VALID_KIT_YAML})

        with (
            patch("shutil.which", return_value="/usr/bin/git"),
            patch("tempfile.mkdtemp", return_value=str(fake_repo)),
            patch("subprocess.run") as mock_run,
            patch("shutil.rmtree"),
        ):
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            manifests = _discover_remote_kits()

        assert len(manifests) == 1
        assert manifests[0].kit.name == "my-test-kit"
        assert manifests[0].kit.version == "0.1.0"

    def test_skips_invalid_manifest(self, tmp_path: Path) -> None:
        """Invalid kit.yaml is skipped (warning echoed, no exception)."""
        fake_repo = _make_fake_repo(tmp_path, {"bad-kit": "not: valid\nyaml: content\n"})

        with (
            patch("shutil.which", return_value="/usr/bin/git"),
            patch("tempfile.mkdtemp", return_value=str(fake_repo)),
            patch("subprocess.run") as mock_run,
            patch("shutil.rmtree"),
        ):
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            manifests = _discover_remote_kits()

        assert manifests == []

    def test_exits_when_git_not_found(self) -> None:
        """SystemExit(1) when git is not available."""
        with patch("shutil.which", return_value=None), pytest.raises(SystemExit) as exc_info:
            _discover_remote_kits()
        assert exc_info.value.code == 1

    def test_exits_on_git_failure(self, tmp_path: Path) -> None:
        """SystemExit(1) when git clone fails."""
        import subprocess

        with (
            patch("shutil.which", return_value="/usr/bin/git"),
            patch("tempfile.mkdtemp", return_value=str(tmp_path)),
            patch("shutil.rmtree"),
            patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(128, "git", stderr="auth error"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _discover_remote_kits()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _interactive_kit_discovery
# ---------------------------------------------------------------------------


def _fake_manifests() -> list[MagicMock]:
    """Two fake KitManifest objects for mocking _discover_remote_kits."""
    m1 = MagicMock()
    m1.kit.name = "my-test-kit"
    m1.kit.version = "0.1.0"
    m1.kit.description = "A test kit"

    m2 = MagicMock()
    m2.kit.name = "agent-demo-kit"
    m2.kit.version = "0.2.0"
    m2.kit.description = "Demo agent kit"

    return [m1, m2]


class TestInteractiveKitDiscovery:
    """Tests for _interactive_kit_discovery()."""

    def test_no_tty_prints_list_and_returns(self, capsys: pytest.CaptureFixture[str]) -> None:
        """On non-TTY stdin, prints kit list and returns without prompting."""
        manifests = _fake_manifests()

        with (
            patch("beddel.cli.commands._discover_remote_kits", return_value=manifests),
            patch("beddel.cli.commands.Path") as mock_path_cls,
            patch("sys.stdin") as mock_stdin,
        ):
            # Simulate DB not existing
            mock_path_cls.return_value.expanduser.return_value.exists.return_value = False
            mock_stdin.isatty.return_value = False

            _interactive_kit_discovery()

        captured = capsys.readouterr()
        assert "my-test-kit" in captured.out
        assert "agent-demo-kit" in captured.out

    def test_json_flag_outputs_json_array(self) -> None:
        """--json outputs a JSON array with correct fields and exits."""
        manifests = _fake_manifests()

        runner = CliRunner()
        with (
            patch("beddel.cli.commands._discover_remote_kits", return_value=manifests),
            patch("beddel.cli.commands.Path") as mock_path_cls,
        ):
            mock_path_cls.return_value.expanduser.return_value.exists.return_value = False
            result = runner.invoke(cli, ["kit", "install", "--json"])

        # Extract JSON from output (skip non-JSON prefix line)
        output = result.output
        json_start = output.index("[")
        data = json.loads(output[json_start:])
        assert isinstance(data, list)
        assert len(data) == 2
        names = {item["name"] for item in data}
        assert names == {"my-test-kit", "agent-demo-kit"}
        # Check required fields
        for item in data:
            assert "name" in item
            assert "version" in item
            assert "description" in item
            assert "category" in item
            assert "installed" in item

    def test_json_flag_marks_installed_kits(self) -> None:
        """--json marks kits present in index as installed=True."""
        manifests = _fake_manifests()

        mock_store = MagicMock()
        mock_store.list_kits = AsyncMock(return_value=[{"name": "my-test-kit"}])

        runner = CliRunner()
        with (
            patch("beddel.cli.commands._discover_remote_kits", return_value=manifests),
            patch("beddel.cli.commands.Path") as mock_path_cls,
            patch("beddel.adapters.index_store.IndexStore", return_value=mock_store),
        ):
            mock_path_cls.return_value.expanduser.return_value.exists.return_value = True
            result = runner.invoke(cli, ["kit", "install", "--json"])

        output = result.output
        json_start = output.index("[")
        data = json.loads(output[json_start:])
        by_name = {item["name"]: item for item in data}
        assert by_name["my-test-kit"]["installed"] is True
        assert by_name["agent-demo-kit"]["installed"] is False

    def test_no_manifests_prints_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When no manifests returned, prints error to stderr and returns."""
        with patch("beddel.cli.commands._discover_remote_kits", return_value=[]):
            _interactive_kit_discovery()

        captured = capsys.readouterr()
        assert "No kits found" in captured.err


# ---------------------------------------------------------------------------
# kit install CLI entry point
# ---------------------------------------------------------------------------


class TestKitInstallEntryPoint:
    """Tests for the ``beddel kit install`` CLI command."""

    def test_no_source_triggers_discovery(self) -> None:
        """``beddel kit install`` (no arg) calls _interactive_kit_discovery."""
        runner = CliRunner()
        with patch(
            "beddel.cli.commands._interactive_kit_discovery",
        ) as mock_discovery:
            mock_discovery.return_value = None
            result = runner.invoke(cli, ["kit", "install"])

        assert result.exit_code == 0
        mock_discovery.assert_called_once_with(as_json=False)

    def test_no_source_with_json_flag(self) -> None:
        """``beddel kit install --json`` calls discovery with as_json=True."""
        runner = CliRunner()
        with patch(
            "beddel.cli.commands._interactive_kit_discovery",
        ) as mock_discovery:
            mock_discovery.return_value = None
            result = runner.invoke(cli, ["kit", "install", "--json"])

        assert result.exit_code == 0
        mock_discovery.assert_called_once_with(as_json=True)

    def test_with_source_skips_discovery(self, tmp_path: Path) -> None:
        """``beddel kit install <source>`` skips discovery and installs normally."""
        kit_src = tmp_path / "my-kit"
        kit_src.mkdir()
        (kit_src / "kit.yaml").write_text(_VALID_KIT_YAML)

        runner = CliRunner()
        with (
            patch("beddel.cli.commands._interactive_kit_discovery") as mock_discovery,
            runner.isolated_filesystem(),
        ):
            result = runner.invoke(cli, ["kit", "install", str(kit_src)])

        assert result.exit_code == 0
        mock_discovery.assert_not_called()
        assert "Installed" in result.output


# ---------------------------------------------------------------------------
# HTTP path tests (Story K3A.7)
# ---------------------------------------------------------------------------

from beddel.cli.commands import _KitManifestLike, _fetch_registry_http  # noqa: E402

_REGISTRY_JSON = json.dumps(
    [
        {"name": "agent-demo-kit", "version": "0.2.0", "description": "Demo", "category": "agent"},
        {"name": "my-test-kit", "version": "0.1.0", "description": "A test kit", "category": "my"},
    ]
)


def _make_http_response(body: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body.encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestDiscoverRemoteKitsHTTP:
    """Tests for HTTP-first path in _discover_remote_kits() (Story K3A.7)."""

    def test_http_success_returns_entries_no_git(self) -> None:
        """HTTP success: returns _KitManifestLike entries, no subprocess called."""
        mock_resp = _make_http_response(_REGISTRY_JSON)

        with (
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch("subprocess.run") as mock_run,
        ):
            manifests = _discover_remote_kits()

        mock_run.assert_not_called()
        assert len(manifests) == 2
        names = {m.kit.name for m in manifests}
        assert names == {"agent-demo-kit", "my-test-kit"}
        assert all(isinstance(m, _KitManifestLike) for m in manifests)

    def test_http_success_entry_fields(self) -> None:
        """HTTP entries carry name, version, description."""
        mock_resp = _make_http_response(_REGISTRY_JSON)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            manifests = _discover_remote_kits()

        entry = next(m for m in manifests if m.kit.name == "my-test-kit")
        assert entry.kit.version == "0.1.0"
        assert entry.kit.description == "A test kit"

    def test_http_network_error_falls_back_to_git(self, tmp_path: Path) -> None:
        """On urllib exception, falls back to git sparse-checkout path."""
        import urllib.error

        fake_repo = _make_fake_repo(tmp_path, {"my-test-kit": _VALID_KIT_YAML})

        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("unreachable")),
            patch("shutil.which", return_value="/usr/bin/git"),
            patch("tempfile.mkdtemp", return_value=str(fake_repo)),
            patch("subprocess.run") as mock_run,
            patch("shutil.rmtree"),
        ):
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            manifests = _discover_remote_kits()

        # Git path was invoked
        assert mock_run.called
        assert len(manifests) == 1
        assert manifests[0].kit.name == "my-test-kit"

    def test_http_timeout_falls_back_to_git(self, tmp_path: Path) -> None:
        """On timeout, falls back to git sparse-checkout path."""
        import socket

        fake_repo = _make_fake_repo(tmp_path, {"my-test-kit": _VALID_KIT_YAML})

        with (
            patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")),
            patch("shutil.which", return_value="/usr/bin/git"),
            patch("tempfile.mkdtemp", return_value=str(fake_repo)),
            patch("subprocess.run") as mock_run,
            patch("shutil.rmtree"),
        ):
            mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            manifests = _discover_remote_kits()

        assert mock_run.called
        assert len(manifests) == 1

    def test_fetch_registry_http_non_200_raises(self) -> None:
        """_fetch_registry_http() raises OSError on non-200 status."""
        mock_resp = _make_http_response("Not Found", status=404)

        with (
            patch("urllib.request.urlopen", return_value=mock_resp),
            pytest.raises(OSError, match="HTTP 404"),
        ):
            _fetch_registry_http()
