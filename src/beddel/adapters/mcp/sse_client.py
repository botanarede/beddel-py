"""SSE MCP client adapter — connects to remote MCP servers via Server-Sent Events.

This adapter bridges the Beddel domain core to remote MCP servers using the
``mcp`` Python SDK's ``sse_client()`` context manager and ``ClientSession``
for JSON-RPC 2.0 communication over SSE transport.

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
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

__all__ = ["SSEMCPClient"]


class SSEMCPClient:
    """SSE-based MCP client using the ``mcp`` Python SDK.

    Implements the :class:`~beddel.domain.ports.IMCPClient` protocol
    structurally (no explicit inheritance).  Manages the connection
    lifecycle for a remote MCP server communicating via Server-Sent Events.

    Args:
        url: The SSE endpoint URL of the remote MCP server.
        headers: Optional HTTP headers for the SSE connection.
        timeout: Maximum time in seconds for connection operations.
        sse_read_timeout: Maximum time in seconds to wait for SSE events.
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 5.0,
        sse_read_timeout: float = 300.0,
    ) -> None:
        if not _MCP_AVAILABLE:
            raise MCPError(
                code=MCP_CONNECTION_FAILED,
                message="MCP SDK not installed. Install with: pip install beddel[mcp]",
            )
        self._url = url
        self._headers = headers
        self._timeout = timeout
        self._sse_read_timeout = sse_read_timeout
        self._session: ClientSession | None = None
        self._cm: Any = None  # sse_client context manager

    async def connect(self, server_uri: str) -> None:
        """Establish connection to an MCP server via SSE transport.

        The *server_uri* parameter is accepted for
        :class:`~beddel.domain.ports.IMCPClient` interface compliance.
        ``SSEMCPClient`` uses the constructor-provided ``url`` for the
        actual connection — the URI is not used by the SSE transport.

        Args:
            server_uri: Server URI (accepted for interface compliance,
                ignored by SSE transport).

        Raises:
            MCPError: ``BEDDEL-MCP-600`` on connection failure.
        """
        try:
            self._cm = sse_client(
                self._url,
                headers=self._headers,
                timeout=self._timeout,
                sse_read_timeout=self._sse_read_timeout,
            )
            read, write = await self._cm.__aenter__()
            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
        except MCPError:
            raise
        except Exception as exc:
            await self._cleanup()
            raise MCPError(
                code=MCP_CONNECTION_FAILED,
                message=f"Failed to connect to MCP server: {exc}",
                details={"url": self._url},
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

        Gracefully shuts down the session and SSE context manager.
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
