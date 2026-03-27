"""Integration tests for MCP tool execution through the workflow executor.

Tests the full path: WorkflowExecutor → ToolPrimitive → MCP client,
verifying that MCP tools and local tools coexist in the same workflow
and that ``DefaultDependencies`` correctly stores ``mcp_registry``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import DefaultDependencies, Step, Workflow
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins


def _tool_step(
    step_id: str,
    tool: str,
    *,
    mcp_server: str | None = None,
    arguments: dict[str, Any] | None = None,
) -> Step:
    """Build a tool step with optional MCP server routing."""
    config: dict[str, Any] = {"tool": tool}
    if mcp_server is not None:
        config["mcp_server"] = mcp_server
    if arguments is not None:
        config["arguments"] = arguments
    return Step(id=step_id, primitive="tool", config=config)


def _workflow(*steps: Step) -> Workflow:
    return Workflow(id="wf-mcp-test", name="MCP Test", steps=list(steps))


class TestMCPToolFullPath:
    """End-to-end: executor → tool primitive → MCP client → result."""

    @pytest.mark.asyncio
    async def test_mcp_tool_full_path(self) -> None:
        """Mock MCP client wired via DefaultDependencies executes tool end-to-end."""
        # Arrange — mock MCP client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"status": "ok", "data": [1, 2, 3]}

        registry = PrimitiveRegistry()
        register_builtins(registry)

        deps = DefaultDependencies(
            mcp_registry={"test-server": mock_client},
        )

        executor = WorkflowExecutor(registry, deps=deps)

        step = _tool_step(
            "s1",
            "remote-search",
            mcp_server="test-server",
            arguments={"query": "hello"},
        )
        wf = _workflow(step)

        # Act
        result = await executor.execute(wf, {})

        # Assert — MCP client was called with correct args
        mock_client.call_tool.assert_awaited_once_with(
            "remote-search",
            {"query": "hello"},
        )

        # Result is structured with mcp_server key
        step_result = result["step_results"]["s1"]
        assert step_result["tool"] == "remote-search"
        assert step_result["mcp_server"] == "test-server"
        assert step_result["result"] == {"status": "ok", "data": [1, 2, 3]}
        assert step_result["arguments"] == {"query": "hello"}
        assert "duration_ms" in step_result


class TestMCPAndLocalToolsCoexist:
    """Workflow with both local and MCP tool steps in the same execution."""

    @pytest.mark.asyncio
    async def test_mcp_and_local_tools_coexist(self) -> None:
        """Both a local tool and an MCP tool execute correctly in one workflow."""

        # Arrange — local tool
        def local_add(a: int, b: int) -> int:
            return a + b

        # Arrange — mock MCP client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = "mcp-result-42"

        registry = PrimitiveRegistry()
        register_builtins(registry)

        deps = DefaultDependencies(
            tool_registry={"add": local_add},
            mcp_registry={"calc-server": mock_client},
        )

        executor = WorkflowExecutor(registry, deps=deps)

        local_step = _tool_step(
            "s-local",
            "add",
            arguments={"a": 3, "b": 7},
        )
        mcp_step = _tool_step(
            "s-mcp",
            "multiply",
            mcp_server="calc-server",
            arguments={"x": 6, "y": 7},
        )
        wf = _workflow(local_step, mcp_step)

        # Act
        result = await executor.execute(wf, {})

        # Assert — local tool result
        local_result = result["step_results"]["s-local"]
        assert local_result["tool"] == "add"
        assert local_result["result"] == 10
        assert "mcp_server" not in local_result

        # Assert — MCP tool result
        mcp_result = result["step_results"]["s-mcp"]
        assert mcp_result["tool"] == "multiply"
        assert mcp_result["mcp_server"] == "calc-server"
        assert mcp_result["result"] == "mcp-result-42"

        mock_client.call_tool.assert_awaited_once_with(
            "multiply",
            {"x": 6, "y": 7},
        )


class TestMCPRegistryInDefaultDeps:
    """Verify DefaultDependencies correctly stores and returns mcp_registry."""

    def test_mcp_registry_stored_and_returned(self) -> None:
        """mcp_registry passed to constructor is accessible via property."""
        mock_a = AsyncMock()
        mock_b = AsyncMock()
        reg = {"server-a": mock_a, "server-b": mock_b}

        deps = DefaultDependencies(mcp_registry=reg)

        assert deps.mcp_registry is reg
        assert deps.mcp_registry["server-a"] is mock_a
        assert deps.mcp_registry["server-b"] is mock_b

    def test_mcp_registry_defaults_to_none(self) -> None:
        """mcp_registry is None when not provided."""
        deps = DefaultDependencies()

        assert deps.mcp_registry is None

    def test_mcp_registry_survives_build_deps(self) -> None:
        """mcp_registry is preserved through WorkflowExecutor._build_deps."""
        mock_client = AsyncMock()
        deps = DefaultDependencies(mcp_registry={"srv": mock_client})

        registry = PrimitiveRegistry()
        register_builtins(registry)
        executor = WorkflowExecutor(registry, deps=deps)

        # Access the internal _build_deps to verify passthrough
        built = executor._build_deps()
        assert built.mcp_registry is not None
        assert built.mcp_registry["srv"] is mock_client
