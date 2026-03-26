"""Tests for the internal tool-use loop module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import DefaultDependencies, ExecutionContext
from beddel.error_codes import (
    PRIM_TOOL_NOT_ALLOWED,
    PRIM_TOOL_USE_EXEC_FAILED,
    PRIM_TOOL_USE_MAX_ITERATIONS,
    PRIM_TOOL_USE_NOT_FOUND,
)
from beddel.primitives._tool_use import run_tool_use_loop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context() -> ExecutionContext:
    return ExecutionContext(
        workflow_id="test-wf",
        current_step_id="step-1",
        deps=DefaultDependencies(),
    )


def _text_response(content: str = "Final answer") -> dict[str, Any]:
    return {"content": content, "finish_reason": "stop"}


def _tool_call_response(
    tool_name: str = "get_weather",
    arguments: str = '{"city": "London"}',
    call_id: str = "call_abc123",
) -> dict[str, Any]:
    return {
        "content": None,
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": arguments},
            }
        ],
    }


TOOL_SCHEMAS = [{"type": "function", "function": {"name": "get_weather"}}]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestToolUseLoop:
    async def test_no_tool_calls_returns_immediately(self) -> None:
        provider = AsyncMock()
        provider.complete.return_value = _text_response("Hello")
        ctx = _make_context()
        registry: dict[str, Any] = {"get_weather": lambda city: f"Sunny in {city}"}

        result = await run_tool_use_loop(
            provider,
            "gpt-4o",
            [{"role": "user", "content": "Hi"}],
            TOOL_SCHEMAS,
            registry,
            ctx,
        )

        assert result["content"] == "Hello"
        provider.complete.assert_awaited_once()

    async def test_single_iteration_tool_call(self) -> None:
        provider = AsyncMock()
        provider.complete.side_effect = [
            _tool_call_response("get_weather", '{"city": "London"}', "call_1"),
            _text_response("It's sunny in London"),
        ]
        ctx = _make_context()
        registry = {"get_weather": lambda city: f"Sunny in {city}"}

        messages: list[dict[str, Any]] = [{"role": "user", "content": "Weather?"}]
        result = await run_tool_use_loop(provider, "gpt-4o", messages, TOOL_SCHEMAS, registry, ctx)

        assert result["content"] == "It's sunny in London"
        assert provider.complete.await_count == 2
        # Verify messages were updated with assistant + tool result
        assert messages[1]["role"] == "assistant"
        assert messages[1]["tool_calls"] is not None
        assert messages[2]["role"] == "tool"
        assert messages[2]["tool_call_id"] == "call_1"

    async def test_multi_iteration_tool_calls(self) -> None:
        provider = AsyncMock()
        provider.complete.side_effect = [
            _tool_call_response("get_weather", '{"city": "London"}', "call_1"),
            _tool_call_response("get_weather", '{"city": "Paris"}', "call_2"),
            _text_response("London is sunny, Paris is rainy"),
        ]
        ctx = _make_context()
        registry = {"get_weather": lambda city: f"Weather for {city}"}

        messages: list[dict[str, Any]] = [{"role": "user", "content": "Compare weather"}]
        result = await run_tool_use_loop(provider, "gpt-4o", messages, TOOL_SCHEMAS, registry, ctx)

        assert result["content"] == "London is sunny, Paris is rainy"
        assert provider.complete.await_count == 3

    async def test_max_iterations_exceeded(self) -> None:
        provider = AsyncMock()
        provider.complete.return_value = _tool_call_response()
        ctx = _make_context()
        registry = {"get_weather": lambda city: "Sunny"}

        with pytest.raises(PrimitiveError) as exc_info:
            await run_tool_use_loop(
                provider,
                "gpt-4o",
                [{"role": "user", "content": "Hi"}],
                TOOL_SCHEMAS,
                registry,
                ctx,
                max_iterations=2,
            )

        assert exc_info.value.code == PRIM_TOOL_USE_MAX_ITERATIONS

    async def test_tool_not_found(self) -> None:
        provider = AsyncMock()
        provider.complete.return_value = _tool_call_response("unknown_tool", "{}", "call_1")
        ctx = _make_context()
        registry: dict[str, Any] = {"get_weather": lambda: "Sunny"}

        with pytest.raises(PrimitiveError) as exc_info:
            await run_tool_use_loop(
                provider,
                "gpt-4o",
                [{"role": "user", "content": "Hi"}],
                TOOL_SCHEMAS,
                registry,
                ctx,
            )

        assert exc_info.value.code == PRIM_TOOL_USE_NOT_FOUND
        assert "unknown_tool" in exc_info.value.message

    async def test_tool_execution_failure(self) -> None:
        provider = AsyncMock()
        provider.complete.return_value = _tool_call_response()
        ctx = _make_context()

        def failing_tool(**kwargs: Any) -> None:
            raise ValueError("API down")

        registry = {"get_weather": failing_tool}

        with pytest.raises(PrimitiveError) as exc_info:
            await run_tool_use_loop(
                provider,
                "gpt-4o",
                [{"role": "user", "content": "Hi"}],
                TOOL_SCHEMAS,
                registry,
                ctx,
            )

        assert exc_info.value.code == PRIM_TOOL_USE_EXEC_FAILED
        assert "API down" in exc_info.value.message

    async def test_allowed_tools_enforcement(self) -> None:
        provider = AsyncMock()
        provider.complete.return_value = _tool_call_response("get_weather")
        ctx = _make_context()
        registry = {"get_weather": lambda city: "Sunny"}

        with pytest.raises(PrimitiveError) as exc_info:
            await run_tool_use_loop(
                provider,
                "gpt-4o",
                [{"role": "user", "content": "Hi"}],
                TOOL_SCHEMAS,
                registry,
                ctx,
                allowed_tools=["other_tool"],
            )

        assert exc_info.value.code == PRIM_TOOL_NOT_ALLOWED

    async def test_allowed_tools_none_permits_all(self) -> None:
        provider = AsyncMock()
        provider.complete.side_effect = [
            _tool_call_response(),
            _text_response("Done"),
        ]
        ctx = _make_context()
        registry = {"get_weather": lambda city: "Sunny"}

        result = await run_tool_use_loop(
            provider,
            "gpt-4o",
            [{"role": "user", "content": "Hi"}],
            TOOL_SCHEMAS,
            registry,
            ctx,
            allowed_tools=None,
        )

        assert result["content"] == "Done"

    async def test_tool_use_context_metadata(self) -> None:
        provider = AsyncMock()
        provider.complete.side_effect = [
            _tool_call_response(),
            _text_response("Done"),
        ]
        ctx = _make_context()
        registry = {"get_weather": lambda city: "Sunny"}

        await run_tool_use_loop(
            provider,
            "gpt-4o",
            [{"role": "user", "content": "Hi"}],
            TOOL_SCHEMAS,
            registry,
            ctx,
        )

        tool_ctx = ctx.metadata["_tool_use_context"]
        assert tool_ctx["iteration"] == 1
        assert tool_ctx["is_tool_use_loop"] is True
        assert len(tool_ctx["tool_calls"]) == 1

    async def test_async_tool_execution(self) -> None:
        provider = AsyncMock()
        provider.complete.side_effect = [
            _tool_call_response("async_tool", '{"x": 1}', "call_1"),
            _text_response("Done"),
        ]
        ctx = _make_context()

        async def async_tool(x: int) -> str:
            return f"async result {x}"

        registry: dict[str, Any] = {"async_tool": async_tool}
        schemas = [{"type": "function", "function": {"name": "async_tool"}}]

        messages: list[dict[str, Any]] = [{"role": "user", "content": "Hi"}]
        await run_tool_use_loop(provider, "gpt-4o", messages, schemas, registry, ctx)

        assert messages[2]["content"] == "async result 1"

    async def test_sync_tool_execution(self) -> None:
        provider = AsyncMock()
        provider.complete.side_effect = [
            _tool_call_response("sync_tool", '{"x": 2}', "call_1"),
            _text_response("Done"),
        ]
        ctx = _make_context()

        def sync_tool(x: int) -> str:
            return f"sync result {x}"

        registry: dict[str, Any] = {"sync_tool": sync_tool}
        schemas = [{"type": "function", "function": {"name": "sync_tool"}}]

        messages: list[dict[str, Any]] = [{"role": "user", "content": "Hi"}]
        await run_tool_use_loop(provider, "gpt-4o", messages, schemas, registry, ctx)

        assert messages[2]["content"] == "sync result 2"

    async def test_tool_result_message_format(self) -> None:
        provider = AsyncMock()
        provider.complete.side_effect = [
            _tool_call_response("get_weather", '{"city": "NYC"}', "call_xyz"),
            _text_response("Done"),
        ]
        ctx = _make_context()
        registry = {"get_weather": lambda city: f"Weather: {city}"}

        messages: list[dict[str, Any]] = [{"role": "user", "content": "Hi"}]
        await run_tool_use_loop(provider, "gpt-4o", messages, TOOL_SCHEMAS, registry, ctx)

        tool_msg = messages[2]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call_xyz"
        assert tool_msg["content"] == "Weather: NYC"
