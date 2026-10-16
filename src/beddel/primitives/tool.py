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

from beddel.domain.errors import BeddelError, PrimitiveError
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

__all__ = [
    "SchemaValidator",
    "ToolPrimitive",
]

#: Callable that checks tool arguments against an input schema and raises a
#: Beddel error on violation.  It is supplied by the composition root (AD-21);
#: this module never imports a kit or computes a path to one.
SchemaValidator = Callable[[dict[str, Any], dict[str, Any]], None]

# Fixed messages for the MCP path.  They never interpolate the server name,
# the tool name, the arguments or any text taken from an exception.
_MCP_NOT_ALLOWED_MESSAGE = "MCP tool is not admitted by the workflow allowed_tools list"
_MCP_CALL_FAILED_MESSAGE = "MCP tool call failed"
_MCP_DISCOVERY_FAILED_MESSAGE = "MCP tool schema discovery failed"
_MCP_NO_VALIDATOR_MESSAGE = (
    "Schema validation requested but no MCP schema validator was supplied by the composition root"
)


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
            Defaults to 60.  For an MCP call it is one budget for the whole
            step: schema discovery and the call share it.
        mcp_server (str): Optional. When present, the call is delegated to
            the MCP client registered under this name.  It is admitted only
            when the workflow ``allowed_tools`` contains the exact qualified
            name ``<mcp_server>:<tool>``.
        validate_schema (bool): Optional, MCP calls only. Validate the
            arguments against the tool's ``inputSchema`` before the call,
            using the validator supplied at construction.

    Example config::

        {
            "tool": "web-search",
            "arguments": {"query": "$input.search_term"},
        }
    """

    def __init__(self, *, schema_validator: SchemaValidator | None = None) -> None:
        """Create the primitive.

        Args:
            schema_validator: Optional validator for MCP tool arguments,
                handed over by the composition root.  Without it a step
                that sets ``validate_schema`` fails with a distinct error.
        """
        self._schema_validator = schema_validator

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
            PrimitiveError: ``BEDDEL-PRIM-304`` if the exact qualified name
                ``<mcp_server>:<tool>`` is not in the workflow allowlist, or
                the workflow has no allowlist (checked before arguments are
                resolved and before any call reaches the client).
            PrimitiveError: ``BEDDEL-PRIM-303`` if the step runs out of its
                timeout.  Schema discovery (``list_tools``) and the call share
                that one budget: the call gets what discovery left, and is not
                made at all when nothing is left.  A cached discovery costs
                none of it.  A ``TimeoutError`` raised by the client's own
                ``list_tools`` (not only one from ``wait_for``) maps to this
                same ``BEDDEL-PRIM-303``, exactly as it does on the call path.
                ``timeout=None`` means no limit: discovery and the call both
                run unbounded (``wait_for(timeout=None)``) and never raise it.
            PrimitiveError: ``BEDDEL-PRIM-301`` if the client raises an
                exception that is not a Beddel error.  The message is fixed
                and ``details`` hold only the exception class name
                (``error_type``) and the step id (``step_id``).
            BeddelError: any Beddel error raised by the client or by the
                schema validator (for example an ``MCPError``) is re-raised
                unchanged, code included.
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

        # Defense in depth (AD-21): runs before the arguments are resolved and
        # before list_tools / call_tool reach the server.
        self._check_mcp_allowlist(
            mcp_server,
            tool_name,
            context.metadata.get("_workflow_allowed_tools"),
            context,
        )

        client = mcp_registry[mcp_server]

        arguments: dict[str, Any] = {}
        if "arguments" in config:
            resolver = VariableResolver()
            arguments = resolver.resolve(config["arguments"], context)

        # One step budget covers discovery and the call: a cached discovery
        # consumes none of it, a slow one leaves the call only the remainder.
        # ``timeout=None`` keeps the pre-E1 meaning of no limit at all.
        timeout: int | float | None = config.get("timeout", 60)
        budget_start = time.monotonic()

        # Optional schema validation — when validate_schema is truthy,
        # fetch the tool's inputSchema via list_tools() (cached per-server)
        # and validate arguments before calling the tool.
        if config.get("validate_schema"):
            validator = self._schema_validator
            if validator is None:
                raise PrimitiveError(
                    code=PRIM_TOOL_EXEC_FAILED,
                    message=_MCP_NO_VALIDATOR_MESSAGE,
                    details={
                        "primitive": "tool",
                        "reason": "schema_validator_unavailable",
                        "step_id": context.current_step_id,
                    },
                )
            cache = context.metadata.setdefault("beddel._mcp_tool_schemas", {})
            if mcp_server not in cache:
                discovery_error: str | None = None
                discovery_timed_out = False
                try:
                    tools = await asyncio.wait_for(
                        client.list_tools(),
                        timeout=self._remaining_budget(timeout, budget_start),
                    )
                    discovered = {t["name"]: t["inputSchema"] for t in tools}
                except TimeoutError:
                    discovery_timed_out = True
                except BeddelError:
                    raise
                except Exception as exc:
                    # Capture the class name only and raise after leaving the
                    # block, so no original exception stays chained.
                    discovery_error = type(exc).__name__
                if discovery_timed_out:
                    raise self._mcp_timeout_error(tool_name, mcp_server, timeout, context)
                if discovery_error is not None:
                    raise PrimitiveError(
                        code=PRIM_TOOL_EXEC_FAILED,
                        message=_MCP_DISCOVERY_FAILED_MESSAGE,
                        details={
                            "error_type": discovery_error,
                            "step_id": context.current_step_id,
                        },
                    )
                cache[mcp_server] = discovered
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
            validator(arguments, tool_schema)

        context.metadata["_tool_context"] = {
            "tool_name": tool_name,
            "mcp_server": mcp_server,
            "arguments": arguments,
        }

        start_time = time.monotonic()
        remaining = self._remaining_budget(timeout, budget_start)
        timed_out = remaining is not None and remaining <= 0
        call_error: str | None = None
        if not timed_out:
            try:
                result = await asyncio.wait_for(
                    client.call_tool(tool_name, arguments),
                    timeout=remaining,
                )
            except TimeoutError:
                timed_out = True
            except BeddelError:
                # Any Beddel error (MCPError included) keeps its code and details.
                raise
            except Exception as exc:
                # Capture the class name only and raise after leaving the block:
                # no raw transport text is copied and neither __cause__ nor
                # __context__ points at the original exception.
                call_error = type(exc).__name__

        if timed_out:
            raise self._mcp_timeout_error(tool_name, mcp_server, timeout, context)
        if call_error is not None:
            raise PrimitiveError(
                code=PRIM_TOOL_EXEC_FAILED,
                message=_MCP_CALL_FAILED_MESSAGE,
                details={"error_type": call_error, "step_id": context.current_step_id},
            )

        duration_ms = int((time.monotonic() - start_time) * 1000)
        return {
            "tool": tool_name,
            "mcp_server": mcp_server,
            "result": result,
            "arguments": arguments,
            "duration_ms": duration_ms,
        }

    @staticmethod
    def _remaining_budget(timeout: float | None, budget_start: float) -> float | None:
        """Time left in the step budget, or ``None`` for an unbounded step.

        ``timeout=None`` means no limit (the pre-E1 meaning): discovery and the
        call both run with ``wait_for(timeout=None)``, i.e. unbounded.
        """
        if timeout is None:
            return None
        return timeout - (time.monotonic() - budget_start)

    @staticmethod
    def _mcp_timeout_error(
        tool_name: str,
        mcp_server: str,
        timeout: int | float | None,
        context: ExecutionContext,
    ) -> PrimitiveError:
        """Build the ``BEDDEL-PRIM-303`` error for an MCP step that ran out of budget.

        Discovery and the call share one budget, so both paths report the
        same error.  The caller raises it outside any ``except`` block, so
        neither ``__cause__`` nor ``__context__`` is set.
        """
        return PrimitiveError(
            code=PRIM_TOOL_TIMEOUT,
            message=f"MCP tool '{tool_name}' on server '{mcp_server}' timed out after {timeout}s",
            details={
                "tool": tool_name,
                "mcp_server": mcp_server,
                "timeout": timeout,
                "step_id": context.current_step_id,
            },
        )

    @staticmethod
    def _check_mcp_allowlist(
        mcp_server: str,
        tool_name: str,
        allowed_tools: list[str] | None,
        context: ExecutionContext,
    ) -> None:
        """Admit an MCP tool only by its exact qualified name.

        The qualified name is ``<mcp_server>:<tool>``.  Admission is an exact
        string match against ``allowed_tools``: a bare tool name, a wildcard,
        a case variant or the bare-suffix rule of the local path never admits
        an MCP tool, and ``allowed_tools is None`` admits none (unlike the
        local path, where ``None`` means unrestricted).

        The refusal message is fixed; it does not interpolate the server
        name, the tool name or the arguments.

        Args:
            mcp_server: Declared MCP server key from the step config.
            tool_name: Server-side tool name from the step config.
            allowed_tools: Allowlist from ``workflow.allowed_tools``, or
                ``None`` when the workflow has none.
            context: Execution context for error details.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-304`` when the qualified name is
                not admitted.
        """
        admitted = (
            allowed_tools is not None
            and isinstance(mcp_server, str)
            and isinstance(tool_name, str)
            and f"{mcp_server}:{tool_name}" in allowed_tools
        )
        if not admitted:
            raise PrimitiveError(
                code=PRIM_TOOL_NOT_ALLOWED,
                message=_MCP_NOT_ALLOWED_MESSAGE,
                details={
                    "primitive": "tool",
                    "step_id": context.current_step_id,
                },
            )

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
        if (
            allowed_tools is not None
            and tool_name not in allowed_tools
            and (":" not in tool_name or tool_name.split(":", 1)[1] not in allowed_tools)
        ):
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
