"""Stdio MCP client adapter — connects to local MCP servers via stdin/stdout.

This adapter bridges the Beddel domain core to local MCP servers using the
``mcp`` Python SDK's ``stdio_client()`` context manager and ``ClientSession``
for JSON-RPC 2.0 communication over stdio transport.

The ``mcp`` SDK is an optional dependency (``pip install beddel[mcp]``).
Imports are guarded with ``try/except ImportError`` to provide a clear
error message when the extra is not installed.
"""

from __future__ import annotations

import contextlib
from typing import Any

from beddel.domain.errors import MCPError
from beddel.error_codes import (
    MCP_CONNECTION_FAILED,
    MCP_TOOL_INVOCATION_FAILED,
)

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

__all__ = ["StdioMCPClient"]


class StdioMCPClient:
    """Stdio-based MCP client using the ``mcp`` Python SDK.

    Implements the :class:`~beddel.domain.ports.IMCPClient` protocol
    structurally (no explicit inheritance).  Manages the subprocess
    lifecycle for a local MCP server communicating via stdin/stdout
    JSON-RPC.

    Args:
        command: The executable command to spawn the MCP server
            (e.g. ``"uvx"``, ``"npx"``).
        args: Optional arguments for the command
            (e.g. ``["some-mcp-server"]``).
        env: Optional environment variables for the subprocess.
        timeout: Maximum time in seconds for operations.
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not _MCP_AVAILABLE:
            raise MCPError(
                code=MCP_CONNECTION_FAILED,
                message=("MCP SDK not installed. Install with: pip install beddel[mcp]"),
            )
        self._params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env,
        )
        self._timeout = timeout
        self._session: ClientSession | None = None
        self._cm: Any = None  # stdio_client context manager
        self._read: Any = None
        self._write: Any = None

    async def connect(self, server_uri: str) -> None:
        """Establish connection to an MCP server via stdio transport.

        The *server_uri* parameter is accepted for
        :class:`~beddel.domain.ports.IMCPClient` interface compliance.
        ``StdioMCPClient`` uses the constructor-provided ``command``/``args``
        for the actual subprocess — the URI is not used by the stdio
        transport.

        Args:
            server_uri: Server URI (accepted for interface compliance,
                ignored by stdio transport).

        Raises:
            MCPError: ``BEDDEL-MCP-600`` on connection failure.
        """
        try:
            self._cm = stdio_client(self._params)
            self._read, self._write = await self._cm.__aenter__()
            self._session = ClientSession(self._read, self._write)
            await self._session.__aenter__()
            await self._session.initialize()
        except MCPError:
            raise
        except Exception as exc:
            await self._cleanup()
            raise MCPError(
                code=MCP_CONNECTION_FAILED,
                message=f"Failed to connect to MCP server: {exc}",
                details={"command": self._params.command, "args": list(self._params.args)},
            ) from exc

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover available tools on the connected server.

        Returns:
            List of tool descriptors with ``name``, ``description``, and
            ``inputSchema`` keys.

        Raises:
            MCPError: ``BEDDEL-MCP-600`` if not connected.
            MCPError: ``BEDDEL-MCP-602`` on invocation failure.
        """
        self._ensure_connected()
        assert self._session is not None  # for type narrowing
        try:
            result = await self._session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": getattr(tool, "description", None) or "",
                    "inputSchema": getattr(tool, "inputSchema", None) or {},
                }
                for tool in result.tools
            ]
        except MCPError:
            raise
        except Exception as exc:
            raise MCPError(
                code=MCP_TOOL_INVOCATION_FAILED,
                message=f"Failed to list tools: {exc}",
            ) from exc

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool on the connected server.

        Args:
            name: Tool name as returned by :meth:`list_tools`.
            arguments: Tool arguments matching the tool's input schema.

        Returns:
            Tool execution result content.

        Raises:
            MCPError: ``BEDDEL-MCP-600`` if not connected.
            MCPError: ``BEDDEL-MCP-602`` on invocation failure.
        """
        self._ensure_connected()
        assert self._session is not None  # for type narrowing
        try:
            result = await self._session.call_tool(name, arguments)
            return result.content
        except MCPError:
            raise
        except Exception as exc:
            raise MCPError(
                code=MCP_TOOL_INVOCATION_FAILED,
                message=f"MCP tool '{name}' invocation failed: {exc}",
                details={"tool": name, "arguments": arguments},
            ) from exc

    async def disconnect(self) -> None:
        """Close the connection to the MCP server.

        Gracefully shuts down the session and stdio context manager.
        Safe to call multiple times.
        """
        await self._cleanup()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        """Raise if the client is not connected."""
        if self._session is None:
            raise MCPError(
                code=MCP_CONNECTION_FAILED,
                message="Not connected to MCP server. Call connect() first.",
            )

    async def _cleanup(self) -> None:
        """Clean up session and context manager resources."""
        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.__aexit__(None, None, None)
            self._session = None
        if self._cm is not None:
            with contextlib.suppress(Exception):
                await self._cm.__aexit__(None, None, None)
            self._cm = None
        self._read = None
        self._write = None
