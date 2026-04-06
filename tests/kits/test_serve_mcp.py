"""Tests for serve-mcp-kit — BeddelMCPServer and create_mcp_server."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from beddel.domain.models import Workflow
from beddel.domain.parser import WorkflowParser
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
def simple_workflow() -> Workflow:
    return WorkflowParser.parse(SIMPLE_WORKFLOW_YAML)


@pytest.fixture()
def registry() -> PrimitiveRegistry:
    reg = PrimitiveRegistry()
    register_builtins(reg)
    return reg


# ---------------------------------------------------------------------------
# BeddelMCPServer tests
# ---------------------------------------------------------------------------


class TestBeddelMCPServer:
    def test_register_workflow_creates_tool(self, simple_workflow: Workflow) -> None:
        """Registering a workflow should create an MCP tool with matching name."""
        from beddel_serve_mcp.server import BeddelMCPServer

        server = BeddelMCPServer("Test")
        server.register_workflow(simple_workflow)

        assert server.tool_count == 1
        assert "hello-world" in server._workflows

    def test_register_multiple_workflows(self) -> None:
        """Multiple workflows should each become a separate tool."""
        from beddel_serve_mcp.server import BeddelMCPServer

        server = BeddelMCPServer("Test")

        wf1 = WorkflowParser.parse(SIMPLE_WORKFLOW_YAML)
        wf2_yaml = SIMPLE_WORKFLOW_YAML.replace("hello-world", "goodbye-world")
        wf2 = WorkflowParser.parse(wf2_yaml)

        server.register_workflows([wf1, wf2])
        assert server.tool_count == 2

    def test_mcp_property_returns_fastmcp(self) -> None:
        """The mcp property should return the underlying FastMCP instance."""
        from beddel_serve_mcp.server import BeddelMCPServer

        server = BeddelMCPServer("Test")
        assert server.mcp is not None

    def test_invalid_transport_raises(self) -> None:
        """An unsupported transport should raise ValueError."""
        from beddel_serve_mcp.server import BeddelMCPServer

        server = BeddelMCPServer("Test")
        with pytest.raises(ValueError, match="Unsupported transport"):
            server.run(transport="invalid")


# ---------------------------------------------------------------------------
# create_mcp_server tests
# ---------------------------------------------------------------------------


class TestCreateMCPServer:
    def test_discovers_yaml_files(self, tmp_path: Path) -> None:
        """Factory should discover and register all *.yaml files."""
        from beddel_serve_mcp.server import create_mcp_server

        (tmp_path / "wf1.yaml").write_text(SIMPLE_WORKFLOW_YAML)
        wf2 = SIMPLE_WORKFLOW_YAML.replace("hello-world", "wf2")
        (tmp_path / "wf2.yaml").write_text(wf2)
        (tmp_path / "not-yaml.txt").write_text("ignore me")

        server = create_mcp_server(tmp_path)
        assert server.tool_count == 2

    def test_empty_directory_returns_server(self, tmp_path: Path) -> None:
        """An empty directory should return a server with zero tools."""
        from beddel_serve_mcp.server import create_mcp_server

        server = create_mcp_server(tmp_path)
        assert server.tool_count == 0

    def test_nonexistent_directory_raises(self) -> None:
        """A nonexistent directory should raise FileNotFoundError."""
        from beddel_serve_mcp.server import create_mcp_server

        with pytest.raises(FileNotFoundError):
            create_mcp_server("/nonexistent/path")

    def test_invalid_yaml_skipped(self, tmp_path: Path) -> None:
        """Invalid YAML files should be skipped without crashing."""
        from beddel_serve_mcp.server import create_mcp_server

        (tmp_path / "valid.yaml").write_text(SIMPLE_WORKFLOW_YAML)
        (tmp_path / "broken.yaml").write_text("not: a: valid: workflow:")

        server = create_mcp_server(tmp_path)
        assert server.tool_count == 1
