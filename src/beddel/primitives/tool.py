"""Tool primitive — external tool invocation for Beddel workflows.

Provides :class:`ToolPrimitive`, which implements
:class:`~beddel.domain.ports.IPrimitive` and enables workflows to invoke
registered tool functions (both sync and async) with input validation
and structured result wrapping.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import ExecutionContext
from beddel.domain.ports import IPrimitive
from beddel.domain.resolver import VariableResolver
from beddel.error_codes import (
    PRIM_MISSING_TOOL_REGISTRY,
    PRIM_TOOL_EXEC_FAILED,
    PRIM_TOOL_MISSING_CONFIG,
    PRIM_TOOL_NOT_ALLOWED,
    PRIM_TOOL_NOT_FOUND,
    PRIM_TOOL_TIMEOUT,
)

try:
    from beddel.adapters.mcp.schema_validator import validate_tool_arguments
except ImportError:
    validate_tool_arguments = None  # type: ignore[assignment]

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
        timeout (int): Optional. Timeout in seconds for tool execution.
            Defaults to 60.

    Example config::

        {
            "tool": "web-search",
            "arguments": {"query": "$input.search_term"},
        }
    """

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute the tool primitive.

        Validates config, extracts the tool registry, resolves the tool
        function, checks the workflow allowlist, resolves arguments,
        invokes the tool with timeout, and returns a structured result.

        Args:
            config: Primitive configuration containing ``tool`` (required),
                optional ``arguments`` dict, and optional ``timeout`` int.
            context: Execution context providing runtime data and dependencies.

        Returns:
            A dict with ``tool`` (name), ``result`` (tool output),
            ``arguments`` (resolved kwargs), and ``duration_ms``
            (execution time in milliseconds).

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-302`` if ``tool`` key is missing.
            PrimitiveError: ``BEDDEL-PRIM-005`` if tool_registry is missing.
            PrimitiveError: ``BEDDEL-PRIM-300`` if tool not found in registry.
            PrimitiveError: ``BEDDEL-PRIM-304`` if tool not in allowlist.
            PrimitiveError: ``BEDDEL-PRIM-303`` if tool execution times out.
            PrimitiveError: ``BEDDEL-PRIM-301`` if tool execution fails.
        """
        self._validate_config(config, context)

        # MCP delegation path — when mcp_server is present, route to MCP
        # client instead of the local tool_registry.
        if config.get("mcp_server"):
            return await self._execute_mcp_tool(config, context)

        registry = self._get_tool_registry(context)
        tool_name: str = config["tool"]
        tool_fn = self._resolve_tool(tool_name, registry, context)

        self._check_allowlist(
            tool_name,
            context.metadata.get("_workflow_allowed_tools"),
            context,
        )

        arguments: dict[str, Any] = {}
        if "arguments" in config:
            resolver = VariableResolver()
            arguments = resolver.resolve(config["arguments"], context)

        context.metadata["_tool_context"] = {
            "tool_name": tool_name,
            "arguments": arguments,
        }

        timeout: int | float = config.get("timeout", 60)
        start_time = time.monotonic()
        try:
            result = await asyncio.wait_for(self._invoke_tool(tool_fn, arguments), timeout=timeout)
        except TimeoutError:
            raise PrimitiveError(
                code=PRIM_TOOL_TIMEOUT,
                message=f"Tool '{tool_name}' timed out after {timeout}s",
                details={
                    "tool": tool_name,
                    "timeout": timeout,
                    "step_id": context.current_step_id,
                },
            ) from None

        duration_ms = int((time.monotonic() - start_time) * 1000)
        return {
            "tool": tool_name,
            "result": result,
            "arguments": arguments,
            "duration_ms": duration_ms,
        }

    async def _execute_mcp_tool(
        self,
        config: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Delegate tool execution to an MCP server.

        Extracts the MCP server name and tool name from config, resolves
        the MCP client from ``context.deps.mcp_registry``, resolves
        arguments via :class:`VariableResolver`, invokes the tool via
        the MCP client, and returns a structured result dict.

        Args:
            config: Primitive configuration containing ``mcp_server``
                (required), ``tool`` (required), optional ``arguments``
                dict, and optional ``timeout`` int.
            context: Execution context providing runtime data and
                dependencies.

        Returns:
            A dict with ``tool`` (name), ``mcp_server`` (server name),
            ``result`` (tool output), ``arguments`` (resolved kwargs),
            and ``duration_ms`` (execution time in milliseconds).

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-005`` if mcp_registry is not
                configured or the server is not found.
            PrimitiveError: ``BEDDEL-PRIM-303`` if tool execution times out.
            PrimitiveError: ``BEDDEL-PRIM-301`` if tool execution fails.
        """
        mcp_server: str = config["mcp_server"]
        tool_name: str = config["tool"]

        mcp_registry = context.deps.mcp_registry
        if mcp_registry is None or mcp_server not in mcp_registry:
            raise PrimitiveError(
                code=PRIM_MISSING_TOOL_REGISTRY,
                message=(f"MCP registry not configured or server '{mcp_server}' not found"),
                details={
                    "primitive": "tool",
                    "mcp_server": mcp_server,
                    "step_id": context.current_step_id,
                },
            )

        client = mcp_registry[mcp_server]

        arguments: dict[str, Any] = {}
        if "arguments" in config:
            resolver = VariableResolver()
            arguments = resolver.resolve(config["arguments"], context)

        # Optional schema validation — when validate_schema is truthy,
        # fetch the tool's inputSchema via list_tools() (cached per-server)
        # and validate arguments before calling the tool.
        if config.get("validate_schema"):
            if validate_tool_arguments is None:
                raise PrimitiveError(
                    code=PRIM_TOOL_EXEC_FAILED,
                    message=(
                        "Schema validation requested but jsonschema is not installed. "
                        "Install with: pip install beddel[mcp]"
                    ),
                    details={
                        "tool": tool_name,
                        "mcp_server": mcp_server,
                        "step_id": context.current_step_id,
                    },
                )
            cache = context.metadata.setdefault("_mcp_tool_schemas", {})
            if mcp_server not in cache:
                tools = await client.list_tools()
                cache[mcp_server] = {t["name"]: t["inputSchema"] for t in tools}
            tool_schema = cache[mcp_server].get(tool_name)
            if tool_schema is None:
                raise PrimitiveError(
                    code=PRIM_TOOL_EXEC_FAILED,
                    message=(
                        f"Tool '{tool_name}' not found on MCP server "
                        f"'{mcp_server}' during schema discovery"
                    ),
                    details={
                        "tool": tool_name,
                        "mcp_server": mcp_server,
                        "step_id": context.current_step_id,
                    },
                )
            validate_tool_arguments(arguments, tool_schema)

        context.metadata["_tool_context"] = {
            "tool_name": tool_name,
            "mcp_server": mcp_server,
            "arguments": arguments,
        }

        timeout: int | float = config.get("timeout", 60)
        start_time = time.monotonic()
        try:
            result = await asyncio.wait_for(
                client.call_tool(tool_name, arguments),
                timeout=timeout,
            )
        except TimeoutError:
            raise PrimitiveError(
                code=PRIM_TOOL_TIMEOUT,
                message=(
                    f"MCP tool '{tool_name}' on server '{mcp_server}' timed out after {timeout}s"
                ),
                details={
                    "tool": tool_name,
                    "mcp_server": mcp_server,
                    "timeout": timeout,
                    "step_id": context.current_step_id,
                },
            ) from None
        except PrimitiveError:
            raise
        except Exception as exc:
            raise PrimitiveError(
                code=PRIM_TOOL_EXEC_FAILED,
                message=(f"MCP tool '{tool_name}' on server '{mcp_server}' failed: {exc}"),
                details={
                    "primitive": "tool",
                    "tool": tool_name,
                    "mcp_server": mcp_server,
                    "original_error": str(exc),
                    "error_type": type(exc).__name__,
                },
            ) from exc

        duration_ms = int((time.monotonic() - start_time) * 1000)
        return {
            "tool": tool_name,
            "mcp_server": mcp_server,
            "result": result,
            "arguments": arguments,
            "duration_ms": duration_ms,
        }

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
                code=PRIM_TOOL_MISSING_CONFIG,
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
                code=PRIM_MISSING_TOOL_REGISTRY,
                message="Missing required dependency 'tool_registry' for tool primitive",
                details={
                    "primitive": "tool",
                    "step_id": context.current_step_id,
                },
            )
        return context.deps.tool_registry

    @staticmethod
    def _check_allowlist(
        tool_name: str,
        allowed_tools: list[str] | None,
        context: ExecutionContext,
    ) -> None:
        """Validate that the tool is permitted by the workflow allowlist.

        When ``allowed_tools`` is ``None``, all tools are permitted
        (backward-compatible default).  When it is a list, the tool name
        must appear in it.

        Args:
            tool_name: Name of the tool to validate.
            allowed_tools: Allowlist from ``workflow.allowed_tools``, or
                ``None`` if unrestricted.
            context: Execution context for error details.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-304`` if tool not in allowlist.
        """
        if allowed_tools is not None and tool_name not in allowed_tools:
            raise PrimitiveError(
                code=PRIM_TOOL_NOT_ALLOWED,
                message=f"Tool '{tool_name}' is not in the workflow allowed_tools list",
                details={
                    "tool": tool_name,
                    "allowed_tools": allowed_tools,
                    "step_id": context.current_step_id,
                },
            )

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
                code=PRIM_TOOL_NOT_FOUND,
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
                code=PRIM_TOOL_EXEC_FAILED,
                message=f"Tool execution failed: {exc}",
                details={
                    "primitive": "tool",
                    "original_error": str(exc),
                    "error_type": type(exc).__name__,
                },
            ) from exc
