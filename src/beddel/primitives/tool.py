"""Tool primitive — external tool invocation for Beddel workflows.

Provides :class:`ToolPrimitive`, which implements
:class:`~beddel.domain.ports.IPrimitive` and enables workflows to invoke
registered tool functions (both sync and async) with input validation
and structured result wrapping.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import ExecutionContext
from beddel.domain.ports import IPrimitive
from beddel.domain.resolver import VariableResolver

__all__ = [
    "ToolPrimitive",
]


class ToolPrimitive(IPrimitive):
    """External tool invocation primitive.

    Looks up a tool function by name from ``context.deps.tool_registry``,
    resolves optional arguments via :class:`VariableResolver`, invokes the
    tool (detecting sync vs async automatically), and returns a structured
    result dict.

    Config keys:
        tool (str): Required. Tool name to look up in the registry.
        arguments (dict): Optional. Keyword arguments for the tool function.
            Supports ``$input`` and ``$stepResult`` variable references.

    Example config::

        {
            "tool": "web-search",
            "arguments": {"query": "$input.search_term"},
        }
    """

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute the tool primitive.

        Validates config, extracts the tool registry, resolves the tool
        function, resolves arguments, invokes the tool, and returns a
        structured result.

        Args:
            config: Primitive configuration containing ``tool`` (required)
                and optional ``arguments`` dict.
            context: Execution context providing runtime data and dependencies.

        Returns:
            A dict with ``tool`` (name) and ``result`` (tool output).

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-302`` if ``tool`` key is missing.
            PrimitiveError: ``BEDDEL-PRIM-005`` if tool_registry is missing.
            PrimitiveError: ``BEDDEL-PRIM-300`` if tool not found in registry.
            PrimitiveError: ``BEDDEL-PRIM-301`` if tool execution fails.
        """
        self._validate_config(config, context)
        registry = self._get_tool_registry(context)
        tool_name: str = config["tool"]
        tool_fn = self._resolve_tool(tool_name, registry, context)

        arguments: dict[str, Any] = {}
        if "arguments" in config:
            resolver = VariableResolver()
            arguments = resolver.resolve(config["arguments"], context)

        result = await self._invoke_tool(tool_fn, arguments)
        return {"tool": tool_name, "result": result}

    @staticmethod
    def _validate_config(config: dict[str, Any], context: ExecutionContext) -> None:
        """Validate required config keys.

        Args:
            config: Primitive configuration dict.
            context: Execution context for error details.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-302`` if ``tool`` key is missing.
        """
        if "tool" not in config:
            raise PrimitiveError(
                code="BEDDEL-PRIM-302",
                message="Missing required config key 'tool' for tool primitive",
                details={
                    "primitive": "tool",
                    "step_id": context.current_step_id,
                },
            )

    @staticmethod
    def _get_tool_registry(
        context: ExecutionContext,
    ) -> dict[str, Callable[..., Any]]:
        """Extract tool_registry from context deps.

        Args:
            context: Execution context providing dependencies.

        Returns:
            The tool registry mapping tool names to callables.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-005`` if tool_registry is missing.
        """
        if context.deps.tool_registry is None:
            raise PrimitiveError(
                code="BEDDEL-PRIM-005",
                message="Missing required dependency 'tool_registry' for tool primitive",
                details={
                    "primitive": "tool",
                    "step_id": context.current_step_id,
                },
            )
        return context.deps.tool_registry

    @staticmethod
    def _resolve_tool(
        name: str,
        registry: dict[str, Callable[..., Any]],
        context: ExecutionContext,
    ) -> Callable[..., Any]:
        """Look up a tool by name in the registry.

        Args:
            name: Tool name to look up.
            registry: Mapping of tool names to callables.
            context: Execution context for error details.

        Returns:
            The tool callable.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-300`` if tool not found.
        """
        if name not in registry:
            raise PrimitiveError(
                code="BEDDEL-PRIM-300",
                message=f"Tool '{name}' not found in tool_registry",
                details={
                    "primitive": "tool",
                    "step_id": context.current_step_id,
                    "tool": name,
                    "available_tools": list(registry.keys()),
                },
            )
        return registry[name]

    @staticmethod
    async def _invoke_tool(
        tool_fn: Callable[..., Any],
        arguments: dict[str, Any],
    ) -> Any:
        """Invoke a tool function, handling both sync and async callables.

        Detects whether the tool function is a coroutine function and awaits
        it if so; otherwise calls it directly.

        Args:
            tool_fn: The tool callable to invoke.
            arguments: Keyword arguments to pass to the tool.

        Returns:
            The tool function's return value.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-301`` if tool execution fails.
        """
        try:
            if asyncio.iscoroutinefunction(tool_fn):
                return await tool_fn(**arguments)
            return tool_fn(**arguments)
        except PrimitiveError:
            raise
        except Exception as exc:
            raise PrimitiveError(
                code="BEDDEL-PRIM-301",
                message=f"Tool execution failed: {exc}",
                details={
                    "primitive": "tool",
                    "original_error": str(exc),
                    "error_type": type(exc).__name__,
                },
            ) from exc
