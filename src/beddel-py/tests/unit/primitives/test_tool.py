"""Unit tests for the Tool primitive."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    PrimitiveError,
)
from beddel.primitives.tool import tool_primitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(registry: dict[str, Any] | None = None) -> ExecutionContext:
    """Execution context with optional tool registry."""
    meta: dict[str, Any] = {}
    if registry is not None:
        meta["tool_registry"] = registry
    return ExecutionContext(metadata=meta)


# ---------------------------------------------------------------------------
# 3.2 Happy path: sync tool function returns expected output
# ---------------------------------------------------------------------------


async def test_sync_tool_returns_expected_output() -> None:
    """Sync tool function is invoked and its return value is returned."""
    def add(a: int, b: int) -> int:
        return a + b

    result = await tool_primitive(
        {"name": "add", "args": {"a": 2, "b": 3}},
        _ctx(registry={"add": add}),
    )
    assert result == 5


# ---------------------------------------------------------------------------
# 3.3 Happy path: async tool function returns expected output
# ---------------------------------------------------------------------------


async def test_async_tool_returns_expected_output() -> None:
    """Async tool function is awaited and its return value is returned."""
    async def greet(name: str) -> str:
        return f"hello {name}"

    result = await tool_primitive(
        {"name": "greet", "args": {"name": "world"}},
        _ctx(registry={"greet": greet}),
    )
    assert result == "hello world"


# ---------------------------------------------------------------------------
# 3.4 Missing `name` raises PrimitiveError with BEDDEL-EXEC-001
# ---------------------------------------------------------------------------


async def test_missing_name_raises() -> None:
    """Missing 'name' in config raises PrimitiveError with BEDDEL-EXEC-001."""
    with pytest.raises(PrimitiveError, match="name") as exc_info:
        await tool_primitive({"args": {}}, _ctx(registry={"x": lambda: None}))
    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 3.5 Missing `tool_registry` in metadata raises PrimitiveError
# ---------------------------------------------------------------------------


async def test_missing_tool_registry_raises() -> None:
    """Missing 'tool_registry' in context.metadata raises PrimitiveError."""
    with pytest.raises(PrimitiveError, match="tool_registry") as exc_info:
        await tool_primitive({"name": "foo"}, _ctx())  # no registry
    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 3.6 Unknown tool name raises PrimitiveError with BEDDEL-EXEC-001
# ---------------------------------------------------------------------------


async def test_unknown_tool_name_raises() -> None:
    """Tool name not found in registry raises PrimitiveError."""
    with pytest.raises(PrimitiveError, match="not found") as exc_info:
        await tool_primitive({"name": "missing"}, _ctx(registry={}))
    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 3.7 Default args {} when config["args"] not provided
# ---------------------------------------------------------------------------


async def test_default_args_empty_dict() -> None:
    """When 'args' is omitted from config, tool is called with no arguments."""
    def no_args() -> str:
        return "ok"

    result = await tool_primitive(
        {"name": "no_args"},
        _ctx(registry={"no_args": no_args}),
    )
    assert result == "ok"


# ---------------------------------------------------------------------------
# 3.8 Tool function raising exception wraps error in PrimitiveError
# ---------------------------------------------------------------------------


async def test_tool_exception_wrapped_in_primitive_error() -> None:
    """Exception raised by tool function is wrapped in PrimitiveError."""
    def boom() -> None:
        msg = "kaboom"
        raise ValueError(msg)

    with pytest.raises(PrimitiveError, match="kaboom") as exc_info:
        await tool_primitive({"name": "boom"}, _ctx(registry={"boom": boom}))
    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 3.9 Timeout triggers PrimitiveError with BEDDEL-EXEC-003
# ---------------------------------------------------------------------------


async def test_timeout_raises_primitive_error() -> None:
    """Async tool exceeding timeout raises PrimitiveError with BEDDEL-EXEC-003."""
    async def slow_tool() -> str:
        await asyncio.sleep(5)
        return "done"

    with pytest.raises(PrimitiveError, match="timed out") as exc_info:
        await tool_primitive(
            {"name": "slow", "timeout": 0.01},
            _ctx(registry={"slow": slow_tool}),
        )
    assert exc_info.value.code == ErrorCode.EXEC_TIMEOUT


# ---------------------------------------------------------------------------
# 3.10 No timeout (default) allows long-running tool to complete
# ---------------------------------------------------------------------------


async def test_no_timeout_allows_completion() -> None:
    """Without timeout config, async tool runs to completion."""
    async def brief_tool() -> str:
        await asyncio.sleep(0.01)
        return "finished"

    result = await tool_primitive(
        {"name": "brief"},
        _ctx(registry={"brief": brief_tool}),
    )
    assert result == "finished"


# ---------------------------------------------------------------------------
# 3.11 Args are passed as keyword arguments to tool function
# ---------------------------------------------------------------------------


async def test_args_passed_as_kwargs() -> None:
    """Args dict is unpacked as keyword arguments to the tool function."""
    def concat(first: str, second: str) -> str:
        return f"{first}-{second}"

    result = await tool_primitive(
        {"name": "concat", "args": {"first": "a", "second": "b"}},
        _ctx(registry={"concat": concat}),
    )
    assert result == "a-b"


# ---------------------------------------------------------------------------
# 3.12 Context is accepted but not passed to tool function
# ---------------------------------------------------------------------------


async def test_context_not_forwarded_to_tool() -> None:
    """Context is used for metadata lookup but not forwarded to the tool."""
    received_args: list[str] = []

    def spy(**kwargs: Any) -> str:
        received_args.extend(kwargs.keys())
        return "done"

    ctx = ExecutionContext(
        workflow_id="test-wf",
        input={"should": "be-ignored"},
        metadata={"tool_registry": {"spy": spy}, "extra": "data"},
    )
    result = await tool_primitive({"name": "spy", "args": {"x": 1}}, ctx)
    assert result == "done"
    assert received_args == ["x"]  # only explicit args, no context
