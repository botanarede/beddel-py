"""Tests for ``beddel serve --mcp`` CLI command (Story K1.7, Task 3)."""

from __future__ import annotations

import sys
import textwrap
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from beddel.cli.commands import cli

SIMPLE_WORKFLOW_YAML = textwrap.dedent("""\
    id: hello-world
    name: Hello World
    description: A test workflow for MCP serving.
    input_schema:
      type: object
      properties:
        topic:
          type: string
      required:
        - topic
    steps:
      - id: greet
        primitive: llm
        config:
          model: test/model
          prompt: "Hello $input.topic"
""")


@pytest.fixture()
def _fake_serve_mcp(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a fake ``beddel_serve_mcp.server`` module into sys.modules.

    The serve command uses lazy imports inside the function body after
    ``_ensure_kit_paths()`` adds kit directories to ``sys.path``.  In the
    test environment the kit package is not installed, so we synthesise
    the module with mock objects.
    """
    mock_server_instance = MagicMock()
    mock_server_instance.tool_count = 1

    mock_cls = MagicMock(return_value=mock_server_instance)

    mock_create = MagicMock(return_value=mock_server_instance)

    fake_mod = types.ModuleType("beddel_serve_mcp")
    fake_server_mod = types.ModuleType("beddel_serve_mcp.server")
    fake_server_mod.BeddelMCPServer = mock_cls  # type: ignore[attr-defined]
    fake_server_mod.create_mcp_server = mock_create  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "beddel_serve_mcp", fake_mod)
    monkeypatch.setitem(sys.modules, "beddel_serve_mcp.server", fake_server_mod)

    # Bundle both mocks for assertions
    result = MagicMock()
    result.server_cls = mock_cls
    result.server_instance = mock_server_instance
    result.create_mcp_server = mock_create
    return result


class TestMcpDashboardMutualExclusion:
    """3.1 — ``--mcp`` with ``--dashboard`` produces error exit."""

    def test_mcp_with_dashboard_errors(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--mcp", "--dashboard"])
        assert result.exit_code != 0
        assert "Error" in result.output


class TestMcpRemoteMutualExclusion:
    """3.2 — ``--mcp`` with ``--remote`` produces error exit."""

    def test_mcp_with_remote_errors(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--mcp", "--remote"])
        assert result.exit_code != 0
        assert "Error" in result.output


class TestMcpWithWorkflowFlag:
    """3.3 — ``--mcp`` with ``-w`` invokes BeddelMCPServer and its run method."""

    @pytest.mark.usefixtures("_fake_serve_mcp")
    def test_mcp_with_workflow_file(self, _fake_serve_mcp: MagicMock, tmp_path: Path) -> None:
        wf_file = tmp_path / "hello.yaml"
        wf_file.write_text(SIMPLE_WORKFLOW_YAML)

        mocks = _fake_serve_mcp

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--mcp", "-w", str(wf_file)])

        assert result.exit_code == 0, result.output
        mocks.server_cls.assert_called_once()
        mocks.server_instance.register_workflow.assert_called_once()
        mocks.server_instance.run.assert_called_once_with(
            transport="stdio", host="127.0.0.1", port=8000
        )


class TestMcpDirectoryScanDefault:
    """3.4 — ``--mcp`` without ``-w`` defaults to current directory scan."""

    @pytest.mark.usefixtures("_fake_serve_mcp")
    def test_mcp_directory_scan(self, _fake_serve_mcp: MagicMock) -> None:
        mocks = _fake_serve_mcp

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--mcp"])

        assert result.exit_code == 0, result.output
        mocks.create_mcp_server.assert_called_once_with(Path("."), name="Beddel Workflows")
        mocks.server_instance.run.assert_called_once_with(
            transport="stdio", host="127.0.0.1", port=8000
        )


class TestMcpStreamableHttpTransport:
    """3.5 — ``--transport streamable-http`` passes correct transport to server."""

    @pytest.mark.usefixtures("_fake_serve_mcp")
    def test_streamable_http_transport(self, _fake_serve_mcp: MagicMock) -> None:
        mocks = _fake_serve_mcp

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["serve", "--mcp", "--transport", "streamable-http"],
        )

        assert result.exit_code == 0, result.output
        mocks.server_instance.run.assert_called_once_with(
            transport="streamable-http", host="127.0.0.1", port=8000
        )


class TestMcpCustomName:
    """3.6 — ``--name`` option passes custom name to server."""

    @pytest.mark.usefixtures("_fake_serve_mcp")
    def test_custom_name(self, _fake_serve_mcp: MagicMock) -> None:
        mocks = _fake_serve_mcp

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--mcp", "--name", "My Custom Server"])

        assert result.exit_code == 0, result.output
        mocks.create_mcp_server.assert_called_once_with(Path("."), name="My Custom Server")
        assert "My Custom Server" in result.output
