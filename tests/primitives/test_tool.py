"""Unit tests for beddel.primitives.tool module."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from _helpers import make_context

from beddel.domain.errors import PrimitiveError
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins
from beddel.primitives.tool import ToolPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sync_add(a: int, b: int) -> int:
    return a + b


async def _async_multiply(x: int, y: int) -> int:
    return x * y


def _sync_greet() -> str:
    return "hello"


async def _async_ping() -> str:
    return "pong"


# ---------------------------------------------------------------------------
# Tests: Sync tool invocation (subtask 5.2)
# ---------------------------------------------------------------------------


class TestSyncInvocation:
    async def test_sync_tool_called_with_arguments(self) -> None:
        registry = {"add": _sync_add}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "add", "arguments": {"a": 3, "b": 4}}, ctx)

        assert result["result"] == 7

    async def test_sync_tool_result_wrapped_in_structured_format(self) -> None:
        registry = {"add": _sync_add}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "add", "arguments": {"a": 1, "b": 2}}, ctx)

        assert result["tool"] == "add"
        assert result["result"] == 3
        assert result["arguments"] == {"a": 1, "b": 2}
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# Tests: Async tool invocation (subtask 5.3)
# ---------------------------------------------------------------------------


class TestAsyncInvocation:
    async def test_async_tool_awaited_with_arguments(self) -> None:
        registry = {"multiply": _async_multiply}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute(
            {"tool": "multiply", "arguments": {"x": 5, "y": 6}}, ctx
        )

        assert result["result"] == 30

    async def test_async_tool_result_wrapped_in_structured_format(self) -> None:
        registry = {"multiply": _async_multiply}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute(
            {"tool": "multiply", "arguments": {"x": 2, "y": 3}}, ctx
        )

        assert result["tool"] == "multiply"
        assert result["result"] == 6
        assert result["arguments"] == {"x": 2, "y": 3}
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# Tests: Missing tool_registry (subtask 5.4)
# ---------------------------------------------------------------------------


class TestMissingToolRegistry:
    async def test_raises_prim_005_when_tool_registry_none(self) -> None:
        ctx = make_context(workflow_id="wf-tool", tool_registry=None)

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-005") as exc_info:
            await ToolPrimitive().execute({"tool": "anything"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-005"

    async def test_error_details_contain_primitive_and_step_id(self) -> None:
        ctx = make_context(workflow_id="wf-tool", tool_registry=None, step_id="my-step")

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"tool": "anything"}, ctx)

        assert exc_info.value.details["primitive"] == "tool"
        assert exc_info.value.details["step_id"] == "my-step"


# ---------------------------------------------------------------------------
# Tests: Tool not found in registry (subtask 5.5)
# ---------------------------------------------------------------------------


class TestToolNotFound:
    async def test_raises_prim_300_when_tool_not_in_registry(self) -> None:
        registry = {"existing": _sync_greet}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-300") as exc_info:
            await ToolPrimitive().execute({"tool": "missing"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-300"

    async def test_error_details_contain_available_tools(self) -> None:
        registry = {"alpha": _sync_greet, "beta": _sync_add}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"tool": "gamma"}, ctx)

        details = exc_info.value.details
        assert details["tool"] == "gamma"
        assert sorted(details["available_tools"]) == ["alpha", "beta"]
        assert details["primitive"] == "tool"


# ---------------------------------------------------------------------------
# Tests: Tool execution failure (subtask 5.6)
# ---------------------------------------------------------------------------


def _failing_tool() -> None:
    raise ValueError("boom")


class TestToolExecutionFailure:
    async def test_raises_prim_301_wrapping_original_exception(self) -> None:
        registry = {"bad": _failing_tool}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-301") as exc_info:
            await ToolPrimitive().execute({"tool": "bad"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-301"

    async def test_error_details_contain_original_error_info(self) -> None:
        registry = {"bad": _failing_tool}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"tool": "bad"}, ctx)

        details = exc_info.value.details
        assert details["original_error"] == "boom"
        assert details["error_type"] == "ValueError"
        assert details["primitive"] == "tool"

    async def test_primitive_error_passthrough_not_wrapped(self) -> None:
        def _raise_prim_error() -> None:
            raise PrimitiveError(
                code="BEDDEL-PRIM-999",
                message="inner primitive error",
            )

        registry = {"prim_err": _raise_prim_error}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"tool": "prim_err"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-999"


# ---------------------------------------------------------------------------
# Tests: Missing tool config key (subtask 5.7)
# ---------------------------------------------------------------------------


class TestMissingToolConfig:
    async def test_raises_prim_302_when_tool_key_missing(self) -> None:
        registry = {"something": _sync_greet}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-302") as exc_info:
            await ToolPrimitive().execute({}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-302"

    async def test_error_details_contain_primitive_and_step_id(self) -> None:
        ctx = make_context(workflow_id="wf-tool", tool_registry={}, step_id="cfg-step")

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"arguments": {"a": 1}}, ctx)

        details = exc_info.value.details
        assert details["primitive"] == "tool"
        assert details["step_id"] == "cfg-step"


# ---------------------------------------------------------------------------
# Tests: Tool with no arguments (subtask 5.8)
# ---------------------------------------------------------------------------


class TestNoArguments:
    async def test_sync_tool_called_with_empty_dict_when_no_arguments(self) -> None:
        registry = {"greet": _sync_greet}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "greet"}, ctx)

        assert result["tool"] == "greet"
        assert result["result"] == "hello"
        assert result["arguments"] == {}
        assert isinstance(result["duration_ms"], int)

    async def test_async_tool_called_with_no_arguments(self) -> None:
        registry = {"ping": _async_ping}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "ping"}, ctx)

        assert result["tool"] == "ping"
        assert result["result"] == "pong"
        assert result["arguments"] == {}
        assert isinstance(result["duration_ms"], int)


# ---------------------------------------------------------------------------
# Tests: Structured result format (subtask 5.9)
# ---------------------------------------------------------------------------


class TestStructuredResult:
    async def test_result_contains_tool_and_result_keys(self) -> None:
        registry = {"greet": _sync_greet}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "greet"}, ctx)

        assert set(result.keys()) == {"tool", "result", "arguments", "duration_ms"}

    async def test_result_with_dict_output(self) -> None:
        def _dict_tool() -> dict[str, int]:
            return {"count": 42}

        registry = {"info": _dict_tool}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "info"}, ctx)

        assert result["tool"] == "info"
        assert result["result"] == {"count": 42}
        assert result["arguments"] == {}
        assert isinstance(result["duration_ms"], int)

    async def test_result_with_list_output(self) -> None:
        def _list_tool() -> list[str]:
            return ["a", "b", "c"]

        registry = {"items": _list_tool}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "items"}, ctx)

        assert result["tool"] == "items"
        assert result["result"] == ["a", "b", "c"]
        assert result["arguments"] == {}
        assert isinstance(result["duration_ms"], int)

    async def test_result_with_none_output(self) -> None:
        def _void_tool() -> None:
            return None

        registry = {"noop": _void_tool}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "noop"}, ctx)

        assert result["tool"] == "noop"
        assert result["result"] is None
        assert result["arguments"] == {}
        assert isinstance(result["duration_ms"], int)


# ---------------------------------------------------------------------------
# Tests: Variable resolution in arguments (code review M2)
# ---------------------------------------------------------------------------


class TestVariableResolution:
    """Tests for $input and $stepResult resolution in tool arguments."""

    async def test_resolves_input_ref_in_arguments(self) -> None:
        """Verify $input refs in config.arguments are resolved before calling tool."""

        def _echo(**kwargs: Any) -> dict[str, Any]:
            return kwargs

        registry = {"echo": _echo}
        ctx = make_context(workflow_id="wf-tool", inputs={"term": "hello"}, tool_registry=registry)

        result = await ToolPrimitive().execute(
            {"tool": "echo", "arguments": {"query": "$input.term"}}, ctx
        )

        assert result["result"]["query"] == "hello"

    async def test_resolves_step_result_ref_in_arguments(self) -> None:
        """Verify $stepResult refs in config.arguments are resolved."""

        def _echo(**kwargs: Any) -> dict[str, Any]:
            return kwargs

        registry = {"echo": _echo}
        ctx = make_context(
            workflow_id="wf-tool",
            step_results={"prev": {"data": "resolved"}},
            tool_registry=registry,
        )

        result = await ToolPrimitive().execute(
            {"tool": "echo", "arguments": {"val": "$stepResult.prev.data"}}, ctx
        )

        assert result["result"]["val"] == "resolved"

    async def test_empty_arguments_dict_passes_empty_dict(self) -> None:
        """Verify explicit empty arguments dict results in empty kwargs."""

        def _echo(**kwargs: Any) -> dict[str, Any]:
            return kwargs

        registry = {"echo": _echo}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "echo", "arguments": {}}, ctx)

        assert result["result"] == {}


# ---------------------------------------------------------------------------
# Tests: register_builtins includes "tool" (subtask 5.10)
# ---------------------------------------------------------------------------


class TestRegisterBuiltins:
    def test_registers_tool_primitive(self) -> None:
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert registry.get("tool") is not None

    def test_registered_is_tool_primitive_instance(self) -> None:
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert isinstance(registry.get("tool"), ToolPrimitive)


# ---------------------------------------------------------------------------
# Tests: Per-tool timeout (Task 3 — AC1)
# ---------------------------------------------------------------------------


async def _slow_tool() -> str:
    await asyncio.sleep(10)
    return "done"


class TestToolTimeout:
    """Tests for per-tool timeout via asyncio.wait_for (AC1)."""

    async def test_timeout_raises_prim_303(self) -> None:
        """Tool exceeding timeout raises PRIM_TOOL_TIMEOUT."""
        registry = {"slow": _slow_tool}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry, step_id="t-step")

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-303") as exc_info:
            await ToolPrimitive().execute({"tool": "slow", "timeout": 0.1}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-303"

    async def test_timeout_error_details(self) -> None:
        """Timeout error includes tool name, timeout value, and step_id."""
        registry = {"slow": _slow_tool}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry, step_id="timeout-step")

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"tool": "slow", "timeout": 0.1}, ctx)

        details = exc_info.value.details
        assert details["tool"] == "slow"
        assert details["timeout"] == 0.1
        assert details["step_id"] == "timeout-step"

    async def test_timeout_error_message_contains_tool_name(self) -> None:
        """Timeout error message mentions the tool name and duration."""
        registry = {"slow": _slow_tool}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"tool": "slow", "timeout": 0.1}, ctx)

        assert "slow" in exc_info.value.message
        assert "0.1" in exc_info.value.message

    async def test_default_timeout_is_60(self) -> None:
        """When no timeout in config, default 60s is used (tool completes fast)."""
        registry = {"greet": _sync_greet}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        # Fast tool should succeed with default 60s timeout
        result = await ToolPrimitive().execute({"tool": "greet"}, ctx)
        assert result["tool"] == "greet"
        assert result["result"] == "hello"
        assert isinstance(result["duration_ms"], int)

    async def test_tool_completes_within_timeout(self) -> None:
        """Tool that finishes before timeout returns normally."""

        async def _fast_tool() -> str:
            await asyncio.sleep(0.01)
            return "fast"

        registry = {"fast": _fast_tool}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "fast", "timeout": 5}, ctx)
        assert result["tool"] == "fast"
        assert result["result"] == "fast"
        assert isinstance(result["duration_ms"], int)


# ---------------------------------------------------------------------------
# Tests: Allowlist validation (Task 3 — AC2)
# ---------------------------------------------------------------------------


class TestToolAllowlist:
    """Tests for workflow allowed_tools validation (AC2)."""

    async def test_disallowed_tool_raises_prim_304(self) -> None:
        """Tool not in allowlist raises PRIM_TOOL_NOT_ALLOWED."""
        registry = {"forbidden": _sync_greet}
        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry=registry,
            metadata={"_workflow_allowed_tools": ["allowed-tool"]},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-304") as exc_info:
            await ToolPrimitive().execute({"tool": "forbidden"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-304"

    async def test_disallowed_tool_error_details(self) -> None:
        """Allowlist error includes tool name, allowed list, and step_id."""
        registry = {"blocked": _sync_greet}
        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry=registry,
            step_id="allow-step",
            metadata={"_workflow_allowed_tools": ["web-search", "calculator"]},
        )

        with pytest.raises(PrimitiveError) as exc_info:
            await ToolPrimitive().execute({"tool": "blocked"}, ctx)

        details = exc_info.value.details
        assert details["tool"] == "blocked"
        assert details["allowed_tools"] == ["web-search", "calculator"]
        assert details["step_id"] == "allow-step"

    async def test_allowed_tool_passes_validation(self) -> None:
        """Tool in allowlist executes normally."""
        registry = {"web-search": _sync_greet}
        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry=registry,
            metadata={"_workflow_allowed_tools": ["web-search", "calculator"]},
        )

        result = await ToolPrimitive().execute({"tool": "web-search"}, ctx)
        assert result["tool"] == "web-search"
        assert result["result"] == "hello"
        assert isinstance(result["duration_ms"], int)

    async def test_none_allowlist_permits_all_tools(self) -> None:
        """When allowed_tools is None, all tools are permitted (backward-compat)."""
        registry = {"any-tool": _sync_greet}
        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry=registry,
            # No _workflow_allowed_tools in metadata → None
        )

        result = await ToolPrimitive().execute({"tool": "any-tool"}, ctx)
        assert result["tool"] == "any-tool"
        assert result["result"] == "hello"
        assert isinstance(result["duration_ms"], int)

    async def test_explicit_none_allowlist_permits_all(self) -> None:
        """Explicit None in metadata permits all tools."""
        registry = {"any-tool": _sync_greet}
        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry=registry,
            metadata={"_workflow_allowed_tools": None},
        )

        result = await ToolPrimitive().execute({"tool": "any-tool"}, ctx)
        assert result["tool"] == "any-tool"
        assert result["result"] == "hello"
        assert isinstance(result["duration_ms"], int)

    async def test_empty_allowlist_blocks_all_tools(self) -> None:
        """Empty allowlist blocks all tools."""
        registry = {"any-tool": _sync_greet}
        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry=registry,
            metadata={"_workflow_allowed_tools": []},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-304"):
            await ToolPrimitive().execute({"tool": "any-tool"}, ctx)


# ---------------------------------------------------------------------------
# Tests: Lifecycle hook enrichment (Task 4 — AC4)
# ---------------------------------------------------------------------------


class TestToolHookEnrichment:
    """Tests for lifecycle hook enrichment with tool context (AC4)."""

    async def test_result_contains_duration_ms(self) -> None:
        """Result dict includes duration_ms as a non-negative integer."""
        registry = {"greet": _sync_greet}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "greet"}, ctx)

        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0

    async def test_result_contains_arguments(self) -> None:
        """Result dict includes the resolved arguments."""
        registry = {"add": _sync_add}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "add", "arguments": {"a": 5, "b": 3}}, ctx)

        assert result["arguments"] == {"a": 5, "b": 3}

    async def test_result_arguments_empty_when_no_args(self) -> None:
        """Result arguments is empty dict when no arguments provided."""
        registry = {"greet": _sync_greet}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "greet"}, ctx)

        assert result["arguments"] == {}

    async def test_tool_context_set_in_metadata(self) -> None:
        """context.metadata['_tool_context'] is set with tool_name and arguments."""
        registry = {"add": _sync_add}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        await ToolPrimitive().execute({"tool": "add", "arguments": {"a": 1, "b": 2}}, ctx)

        tool_ctx = ctx.metadata["_tool_context"]
        assert tool_ctx["tool_name"] == "add"
        assert tool_ctx["arguments"] == {"a": 1, "b": 2}

    async def test_duration_ms_reflects_actual_time(self) -> None:
        """duration_ms is at least as long as the tool's execution time."""

        async def _delay_tool() -> str:
            await asyncio.sleep(0.05)
            return "delayed"

        registry = {"delay": _delay_tool}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "delay", "timeout": 5}, ctx)

        # Should be at least 50ms (the sleep duration)
        assert result["duration_ms"] >= 40  # allow small timing variance


# ---------------------------------------------------------------------------
# Tests: MCP delegation path (Story 4.7a — Task 5)
# ---------------------------------------------------------------------------


class TestMCPDelegation:
    """Tests for MCP tool delegation via mcp_server config key."""

    async def test_tool_mcp_delegation(self) -> None:
        """Config with mcp_server delegates to mock MCP client."""
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={"content": "mcp-result"})

        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry={"local": _sync_greet},
            mcp_registry={"test-server": mock_client},
        )

        result = await ToolPrimitive().execute(
            {
                "tool": "remote-search",
                "mcp_server": "test-server",
                "arguments": {"query": "hello"},
            },
            ctx,
        )

        assert result["tool"] == "remote-search"
        assert result["mcp_server"] == "test-server"
        assert result["result"] == {"content": "mcp-result"}
        assert result["arguments"] == {"query": "hello"}
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0
        mock_client.call_tool.assert_awaited_once_with("remote-search", {"query": "hello"})

    async def test_tool_mcp_no_registry(self) -> None:
        """Config with mcp_server but no mcp_registry raises PRIM-005."""
        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry={"local": _sync_greet},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-005") as exc_info:
            await ToolPrimitive().execute(
                {"tool": "remote-tool", "mcp_server": "missing-server"},
                ctx,
            )

        assert exc_info.value.code == "BEDDEL-PRIM-005"
        assert "missing-server" in exc_info.value.message

    async def test_tool_mcp_server_not_found(self) -> None:
        """Config with mcp_server not in registry raises PRIM-005."""
        mock_client = AsyncMock()
        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry={"local": _sync_greet},
            mcp_registry={"other-server": mock_client},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-005") as exc_info:
            await ToolPrimitive().execute(
                {"tool": "remote-tool", "mcp_server": "unknown-server"},
                ctx,
            )

        assert exc_info.value.code == "BEDDEL-PRIM-005"
        assert "unknown-server" in exc_info.value.message
        assert exc_info.value.details["mcp_server"] == "unknown-server"

    async def test_tool_mcp_call_error(self) -> None:
        """MCP client raises, verify error wrapping as PRIM-301."""
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))

        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry={"local": _sync_greet},
            mcp_registry={"test-server": mock_client},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-301") as exc_info:
            await ToolPrimitive().execute(
                {"tool": "failing-tool", "mcp_server": "test-server"},
                ctx,
            )

        assert exc_info.value.code == "BEDDEL-PRIM-301"
        assert exc_info.value.details["original_error"] == "connection lost"
        assert exc_info.value.details["mcp_server"] == "test-server"
        assert exc_info.value.details["tool"] == "failing-tool"

    async def test_tool_no_mcp_server_backward_compat(self) -> None:
        """Config without mcp_server uses local registry (existing behavior)."""
        registry = {"greet": _sync_greet}
        ctx = make_context(workflow_id="wf-tool", tool_registry=registry)

        result = await ToolPrimitive().execute({"tool": "greet"}, ctx)

        assert result["tool"] == "greet"
        assert result["result"] == "hello"
        assert "mcp_server" not in result
        assert isinstance(result["duration_ms"], int)

    async def test_tool_mcp_resolves_variable_arguments(self) -> None:
        """MCP path resolves $input refs in arguments."""
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value="resolved-result")

        ctx = make_context(
            workflow_id="wf-tool",
            inputs={"term": "world"},
            tool_registry={"local": _sync_greet},
            mcp_registry={"test-server": mock_client},
        )

        result = await ToolPrimitive().execute(
            {
                "tool": "search",
                "mcp_server": "test-server",
                "arguments": {"query": "$input.term"},
            },
            ctx,
        )

        assert result["arguments"] == {"query": "world"}
        mock_client.call_tool.assert_awaited_once_with("search", {"query": "world"})

    async def test_tool_mcp_timeout(self) -> None:
        """MCP tool exceeding timeout raises PRIM-303."""

        async def _slow_mcp_call(name: str, arguments: dict[str, Any]) -> str:
            await asyncio.sleep(10)
            return "done"

        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(side_effect=_slow_mcp_call)

        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry={"local": _sync_greet},
            mcp_registry={"test-server": mock_client},
            step_id="mcp-step",
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-303") as exc_info:
            await ToolPrimitive().execute(
                {"tool": "slow-mcp", "mcp_server": "test-server", "timeout": 0.1},
                ctx,
            )

        assert exc_info.value.code == "BEDDEL-PRIM-303"
        assert exc_info.value.details["mcp_server"] == "test-server"
        assert exc_info.value.details["tool"] == "slow-mcp"

    async def test_tool_mcp_sets_tool_context_metadata(self) -> None:
        """MCP path sets _tool_context in metadata with mcp_server."""
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value="ok")

        ctx = make_context(
            workflow_id="wf-tool",
            tool_registry={"local": _sync_greet},
            mcp_registry={"test-server": mock_client},
        )

        await ToolPrimitive().execute(
            {
                "tool": "my-tool",
                "mcp_server": "test-server",
                "arguments": {"key": "val"},
            },
            ctx,
        )

        tool_ctx = ctx.metadata["_tool_context"]
        assert tool_ctx["tool_name"] == "my-tool"
        assert tool_ctx["mcp_server"] == "test-server"
        assert tool_ctx["arguments"] == {"key": "val"}
