"""Internal tool-use loop for LLM function calling.

Shared by :class:`~beddel.primitives.llm.LLMPrimitive` and
:class:`~beddel.primitives.chat.ChatPrimitive` to support multi-turn
function calling (tool-use loops).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import ExecutionContext
from beddel.domain.ports import ILLMProvider
from beddel.error_codes import (
    PRIM_TOOL_NOT_ALLOWED,
    PRIM_TOOL_USE_EXEC_FAILED,
    PRIM_TOOL_USE_MAX_ITERATIONS,
    PRIM_TOOL_USE_NOT_FOUND,
)

__all__: list[str] = []  # Internal module — no public exports


async def run_tool_use_loop(
    provider: ILLMProvider,
    model: str,
    messages: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
    tool_registry: dict[str, Callable[..., Any]],
    context: ExecutionContext,
    *,
    max_iterations: int = 10,
    allowed_tools: list[str] | None = None,
    provider_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a tool-use loop until the LLM produces a final response.

    Args:
        provider: LLM provider for completion calls.
        model: Model identifier.
        messages: Message history (mutated in-place with tool results).
        tool_schemas: JSON Schema tool definitions for the LLM.
        tool_registry: Mapping of tool names to callables.
        context: Execution context for metadata and error details.
        max_iterations: Maximum loop iterations (default 10).
        allowed_tools: Optional security allowlist.
        provider_kwargs: Extra kwargs forwarded to provider.complete().

    Returns:
        The final LLM response dict (no tool_calls).

    Raises:
        PrimitiveError: BEDDEL-PRIM-310 if max iterations exceeded.
        PrimitiveError: BEDDEL-PRIM-311 if tool not found in registry.
        PrimitiveError: BEDDEL-PRIM-312 if tool execution fails.
        PrimitiveError: BEDDEL-PRIM-304 if tool not in allowed_tools.
    """
    kwargs = dict(provider_kwargs or {})
    kwargs["tools"] = tool_schemas

    for iteration in range(1, max_iterations + 1):
        response = await provider.complete(model, messages, **kwargs)

        tool_calls = response.get("tool_calls")
        if not tool_calls:
            return response

        # Update metadata for lifecycle hooks
        context.metadata["_tool_use_context"] = {
            "iteration": iteration,
            "tool_calls": tool_calls,
            "is_tool_use_loop": True,
        }

        # Build assistant message with tool_calls
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.get("content"),
            "tool_calls": tool_calls,
        }
        messages.append(assistant_msg)

        # Execute each tool call and append results
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            _check_tool_allowed(fn_name, allowed_tools, context)

            if fn_name not in tool_registry:
                raise PrimitiveError(
                    code=PRIM_TOOL_USE_NOT_FOUND,
                    message=f"Tool '{fn_name}' requested by LLM not found in tool_registry",
                    details={
                        "tool": fn_name,
                        "available_tools": list(tool_registry.keys()),
                        "step_id": context.current_step_id,
                        "iteration": iteration,
                    },
                )

            try:
                arguments = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, TypeError) as exc:
                raise PrimitiveError(
                    code=PRIM_TOOL_USE_EXEC_FAILED,
                    message=f"Failed to parse arguments for tool '{fn_name}': {exc}",
                    details={
                        "tool": fn_name,
                        "raw_arguments": tc["function"]["arguments"],
                        "step_id": context.current_step_id,
                        "iteration": iteration,
                    },
                ) from exc

            result = await _execute_tool(
                tool_registry[fn_name], arguments, fn_name, context, iteration
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result),
                }
            )

    # If we exit the loop, max iterations exceeded
    raise PrimitiveError(
        code=PRIM_TOOL_USE_MAX_ITERATIONS,
        message=f"Tool-use loop exceeded max iterations ({max_iterations})",
        details={
            "max_iterations": max_iterations,
            "step_id": context.current_step_id,
        },
    )


async def _execute_tool(
    tool_fn: Callable[..., Any],
    arguments: dict[str, Any],
    tool_name: str,
    context: ExecutionContext,
    iteration: int,
) -> Any:
    """Execute a tool function, handling both sync and async callables.

    Args:
        tool_fn: The tool callable.
        arguments: Parsed keyword arguments.
        tool_name: Tool name for error reporting.
        context: Execution context for error details.
        iteration: Current loop iteration for error details.

    Returns:
        The tool function's return value.

    Raises:
        PrimitiveError: BEDDEL-PRIM-312 if tool execution fails.
    """
    try:
        if asyncio.iscoroutinefunction(tool_fn):
            return await tool_fn(**arguments)
        return tool_fn(**arguments)
    except PrimitiveError:
        raise
    except Exception as exc:
        raise PrimitiveError(
            code=PRIM_TOOL_USE_EXEC_FAILED,
            message=f"Tool '{tool_name}' execution failed: {exc}",
            details={
                "tool": tool_name,
                "original_error": str(exc),
                "error_type": type(exc).__name__,
                "step_id": context.current_step_id,
                "iteration": iteration,
            },
        ) from exc


def _check_tool_allowed(
    tool_name: str,
    allowed_tools: list[str] | None,
    context: ExecutionContext,
) -> None:
    """Validate that a tool is permitted by the allowlist.

    Args:
        tool_name: Name of the tool to validate.
        allowed_tools: Allowlist, or None if unrestricted.
        context: Execution context for error details.

    Raises:
        PrimitiveError: BEDDEL-PRIM-304 if tool not in allowlist.
    """
    if allowed_tools is not None and tool_name not in allowed_tools:
        raise PrimitiveError(
            code=PRIM_TOOL_NOT_ALLOWED,
            message=f"Tool '{tool_name}' is not in the allowed_tools list",
            details={
                "tool": tool_name,
                "allowed_tools": allowed_tools,
                "step_id": context.current_step_id,
            },
        )
