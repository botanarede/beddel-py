"""Tool primitive — Invoke registered Python functions by name."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    PrimitiveError,
)

logger = logging.getLogger("beddel.primitives.tool")


async def tool_primitive(
    config: dict[str, Any],
    context: ExecutionContext,
) -> Any:
    """Invoke a registered tool function by name.

    Looks up a callable in ``context.metadata["tool_registry"]`` and invokes
    it with the keyword arguments from ``config["args"]``.  Supports both
    sync and async callables via the ``inspect.isawaitable()`` pattern.
    An optional ``config["timeout"]`` wraps the call in
    ``asyncio.wait_for()``.
    """
    # AC 2: Extract tool name (required)
    if "name" not in config:
        raise PrimitiveError(
            "tool requires 'name' in config",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "tool", "hint": "Add name field to config"},
        )
    tool_name: str = config["name"]

    # AC 3: Extract args (default {})
    args: dict[str, Any] = config.get("args", {})

    # AC 4: Retrieve tool_registry from context metadata
    tool_registry: dict[str, Any] | None = context.metadata.get("tool_registry")
    if tool_registry is None:
        raise PrimitiveError(
            "tool requires 'tool_registry' in context.metadata",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "tool", "hint": "Provide tool_registry in metadata"},
        )

    # AC 5: Look up tool function by name
    tool_fn = tool_registry.get(tool_name)
    if tool_fn is None:
        raise PrimitiveError(
            f"tool '{tool_name}' not found in tool_registry",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "tool", "tool_name": tool_name},
        )

    # AC 8: Optional timeout
    timeout: float | None = config.get("timeout")

    # AC 9: Log invocation start
    logger.debug(
        "Invoking tool: name=%s, args_keys=%s, timeout=%s",
        tool_name,
        list(args.keys()),
        timeout,
    )

    start = time.monotonic()
    try:
        # AC 6: Invoke — support both sync and async callables
        result = tool_fn(**args)
        if inspect.isawaitable(result):
            if timeout is not None:
                result = await asyncio.wait_for(result, timeout=timeout)
            else:
                result = await result
    except TimeoutError as exc:
        # AC 8: Timeout handling
        duration_ms = (time.monotonic() - start) * 1000
        logger.debug(
            "Tool timed out: name=%s, duration_ms=%.1f, timeout=%s",
            tool_name,
            duration_ms,
            timeout,
        )
        raise PrimitiveError(
            f"tool '{tool_name}' timed out after {timeout}s",
            code=ErrorCode.EXEC_TIMEOUT,
            details={
                "primitive": "tool",
                "tool_name": tool_name,
                "timeout": timeout,
                "duration_ms": duration_ms,
            },
        ) from exc
    except PrimitiveError:
        raise
    except Exception as exc:
        # AC 7: Wrap unexpected errors
        duration_ms = (time.monotonic() - start) * 1000
        logger.debug(
            "Tool failed: name=%s, duration_ms=%.1f, error=%s",
            tool_name,
            duration_ms,
            str(exc),
        )
        raise PrimitiveError(
            f"tool '{tool_name}' raised an error: {exc}",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={
                "primitive": "tool",
                "tool_name": tool_name,
                "error": str(exc),
                "duration_ms": duration_ms,
            },
        ) from exc

    # AC 9: Log success
    duration_ms = (time.monotonic() - start) * 1000
    logger.debug(
        "Tool completed: name=%s, duration_ms=%.1f, success=True",
        tool_name,
        duration_ms,
    )
    return result
