"""Integration tests for MCP tool execution through the workflow executor.

Tests the full path: WorkflowExecutor → ToolPrimitive → MCP client,
verifying that MCP tools and local tools coexist in the same workflow
and that ``DefaultDependencies`` correctly stores ``mcp_registry``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from beddel.domain.errors import ExecutionError, MCPError
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


class TestSSEMCPToolFullPath:
    """End-to-end: executor → tool primitive → SSE MCP client → result."""

    @pytest.mark.asyncio
    async def test_sse_mcp_tool_full_path(self) -> None:
        """Mock SSE client wired via DefaultDependencies executes tool end-to-end."""
        mock_sse_client = AsyncMock()
        mock_sse_client.call_tool.return_value = {"status": "ok", "items": ["a", "b"]}

        registry = PrimitiveRegistry()
        register_builtins(registry)

        deps = DefaultDependencies(
            mcp_registry={"sse-server": mock_sse_client},
        )

        executor = WorkflowExecutor(registry, deps=deps)

        step = _tool_step(
            "s-sse",
            "sse-search",
            mcp_server="sse-server",
            arguments={"query": "world"},
        )
        wf = _workflow(step)

        result = await executor.execute(wf, {})

        mock_sse_client.call_tool.assert_awaited_once_with(
            "sse-search",
            {"query": "world"},
        )

        step_result = result["step_results"]["s-sse"]
        assert step_result["tool"] == "sse-search"
        assert step_result["mcp_server"] == "sse-server"
        assert step_result["result"] == {"status": "ok", "items": ["a", "b"]}
        assert step_result["arguments"] == {"query": "world"}
        assert "duration_ms" in step_result


class TestMCPSchemaValidationIntegration:
    """Workflow-level schema validation: list_tools() → validate → call_tool()."""

    @pytest.mark.asyncio
    async def test_schema_validation_pass(self) -> None:
        """Valid arguments pass schema validation and tool executes."""
        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [
            {
                "name": "greet",
                "description": "Greet someone",
                "inputSchema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        ]
        mock_client.call_tool.return_value = "Hello, Alice!"

        registry = PrimitiveRegistry()
        register_builtins(registry)

        deps = DefaultDependencies(
            mcp_registry={"schema-server": mock_client},
        )
        executor = WorkflowExecutor(registry, deps=deps)

        step = Step(
            id="s-schema",
            primitive="tool",
            config={
                "tool": "greet",
                "mcp_server": "schema-server",
                "validate_schema": True,
                "arguments": {"name": "Alice"},
            },
        )
        wf = _workflow(step)

        result = await executor.execute(wf, {})

        mock_client.list_tools.assert_awaited_once()
        mock_client.call_tool.assert_awaited_once_with("greet", {"name": "Alice"})

        step_result = result["step_results"]["s-schema"]
        assert step_result["result"] == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_schema_validation_fail(self) -> None:
        """Invalid arguments fail schema validation with MCPError."""
        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [
            {
                "name": "greet",
                "description": "Greet someone",
                "inputSchema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        ]

        registry = PrimitiveRegistry()
        register_builtins(registry)

        deps = DefaultDependencies(
            mcp_registry={"schema-server": mock_client},
        )
        executor = WorkflowExecutor(registry, deps=deps)

        step = Step(
            id="s-schema-fail",
            primitive="tool",
            config={
                "tool": "greet",
                "mcp_server": "schema-server",
                "validate_schema": True,
                "arguments": {"name": 12345},
            },
        )
        wf = _workflow(step)

        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute(wf, {})

        cause = exc_info.value.__cause__
        assert isinstance(cause, MCPError)
        assert cause.code == "BEDDEL-MCP-603"
        mock_client.list_tools.assert_awaited_once()
        mock_client.call_tool.assert_not_awaited()


class TestMCPMixedTransports:
    """Workflow with local, stdio MCP, and SSE MCP tool steps."""

    @pytest.mark.asyncio
    async def test_mixed_transports(self) -> None:
        """Local, stdio MCP, and SSE MCP tools all execute in one workflow."""

        def local_double(x: int) -> int:
            return x * 2

        mock_stdio = AsyncMock()
        mock_stdio.call_tool.return_value = "stdio-result"

        mock_sse = AsyncMock()
        mock_sse.call_tool.return_value = "sse-result"

        registry = PrimitiveRegistry()
        register_builtins(registry)

        deps = DefaultDependencies(
            tool_registry={"double": local_double},
            mcp_registry={
                "stdio-server": mock_stdio,
                "sse-server": mock_sse,
            },
        )
        executor = WorkflowExecutor(registry, deps=deps)

        local_step = _tool_step("s-local", "double", arguments={"x": 5})
        stdio_step = _tool_step(
            "s-stdio",
            "stdio-tool",
            mcp_server="stdio-server",
            arguments={"input": "abc"},
        )
        sse_step = _tool_step(
            "s-sse",
            "sse-tool",
            mcp_server="sse-server",
            arguments={"input": "xyz"},
        )
        wf = _workflow(local_step, stdio_step, sse_step)

        result = await executor.execute(wf, {})

        # Local tool
        local_result = result["step_results"]["s-local"]
        assert local_result["tool"] == "double"
        assert local_result["result"] == 10
        assert "mcp_server" not in local_result

        # Stdio MCP tool
        stdio_result = result["step_results"]["s-stdio"]
        assert stdio_result["tool"] == "stdio-tool"
        assert stdio_result["mcp_server"] == "stdio-server"
        assert stdio_result["result"] == "stdio-result"

        # SSE MCP tool
        sse_result = result["step_results"]["s-sse"]
        assert sse_result["tool"] == "sse-tool"
        assert sse_result["mcp_server"] == "sse-server"
        assert sse_result["result"] == "sse-result"

        mock_stdio.call_tool.assert_awaited_once_with(
            "stdio-tool",
            {"input": "abc"},
        )
        mock_sse.call_tool.assert_awaited_once_with(
            "sse-tool",
            {"input": "xyz"},
        )
