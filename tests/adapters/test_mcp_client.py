"""Tests for StdioMCPClient adapter.

All MCP SDK interactions are mocked — no real subprocess spawning.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from beddel.domain.errors import MCPError
from beddel.error_codes import MCP_CONNECTION_FAILED, MCP_TOOL_INVOCATION_FAILED

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_tool(
    name: str = "test-tool",
    description: str = "A test tool",
    input_schema: dict[str, Any] | None = None,
) -> SimpleNamespace:
    """Create a mock MCP tool object matching the SDK's Tool shape."""
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema=input_schema or {"type": "object"},
    )


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


class TestImportGuard:
    """Verify the import guard raises MCPError when mcp SDK is missing."""

    def test_stdio_client_import_guard(self) -> None:
        """When mcp SDK is unavailable, constructor raises MCPError."""
        with patch("beddel.adapters.mcp.stdio_client._MCP_AVAILABLE", False):
            from beddel.adapters.mcp.stdio_client import StdioMCPClient

            with pytest.raises(MCPError, match="MCP SDK not installed") as exc_info:
                StdioMCPClient(command="echo")
            assert exc_info.value.code == MCP_CONNECTION_FAILED


# ---------------------------------------------------------------------------
# Connect / Disconnect lifecycle
# ---------------------------------------------------------------------------


class TestConnectDisconnect:
    """Verify connect/disconnect lifecycle with mocked SDK."""

    @pytest.fixture()
    def _mock_mcp_sdk(self) -> Any:
        """Patch the mcp SDK objects used by StdioMCPClient."""
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_read = MagicMock()
        mock_write = MagicMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "beddel.adapters.mcp.stdio_client.stdio_client",
                return_value=mock_cm,
            ) as mock_stdio,
            patch(
                "beddel.adapters.mcp.stdio_client.ClientSession",
                return_value=mock_session,
            ) as mock_cls,
        ):
            yield {
                "stdio_client": mock_stdio,
                "ClientSession": mock_cls,
                "session": mock_session,
                "cm": mock_cm,
                "read": mock_read,
                "write": mock_write,
            }

    @pytest.mark.asyncio()
    async def test_stdio_client_connect_disconnect(self, _mock_mcp_sdk: Any) -> None:
        """Connect creates session and initializes; disconnect cleans up."""
        from beddel.adapters.mcp.stdio_client import StdioMCPClient

        client = StdioMCPClient(command="test-server", args=["--flag"])

        await client.connect("stdio://test-server")

        # Verify stdio_client was called with the stored params
        _mock_mcp_sdk["stdio_client"].assert_called_once_with(client._params)
        # Verify ClientSession was created with read/write streams
        _mock_mcp_sdk["ClientSession"].assert_called_once_with(
            _mock_mcp_sdk["read"], _mock_mcp_sdk["write"]
        )
        # Verify session was initialized
        _mock_mcp_sdk["session"].initialize.assert_awaited_once()

        await client.disconnect()

        # Verify cleanup
        _mock_mcp_sdk["session"].__aexit__.assert_awaited_once()
        _mock_mcp_sdk["cm"].__aexit__.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_stdio_client_connect_error(self, _mock_mcp_sdk: Any) -> None:
        """Connection failure wraps in MCPError(MCP_CONNECTION_FAILED)."""
        from beddel.adapters.mcp.stdio_client import StdioMCPClient

        _mock_mcp_sdk["cm"].__aenter__ = AsyncMock(side_effect=OSError("Connection refused"))

        client = StdioMCPClient(command="bad-server")

        with pytest.raises(MCPError, match="Failed to connect") as exc_info:
            await client.connect("stdio://bad-server")
        assert exc_info.value.code == MCP_CONNECTION_FAILED

    @pytest.mark.asyncio()
    async def test_disconnect_safe_when_not_connected(self) -> None:
        """Disconnect is safe to call when not connected."""
        from beddel.adapters.mcp.stdio_client import StdioMCPClient

        client = StdioMCPClient(command="test-server")
        # Should not raise
        await client.disconnect()


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------


class TestListTools:
    """Verify list_tools delegates to session and converts results."""

    @pytest.mark.asyncio()
    async def test_stdio_client_list_tools(self) -> None:
        """list_tools converts SDK Tool objects to dicts."""
        from beddel.adapters.mcp.stdio_client import StdioMCPClient

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.initialize = AsyncMock()

        tools = [
            _make_mock_tool("tool-a", "Tool A", {"type": "object", "properties": {}}),
            _make_mock_tool("tool-b", "Tool B", {"type": "string"}),
        ]
        mock_session.list_tools = AsyncMock(return_value=SimpleNamespace(tools=tools))

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "beddel.adapters.mcp.stdio_client.stdio_client",
                return_value=mock_cm,
            ),
            patch(
                "beddel.adapters.mcp.stdio_client.ClientSession",
                return_value=mock_session,
            ),
        ):
            client = StdioMCPClient(command="test-server")
            await client.connect("stdio://test")

            result = await client.list_tools()

        assert len(result) == 2
        assert result[0] == {
            "name": "tool-a",
            "description": "Tool A",
            "inputSchema": {"type": "object", "properties": {}},
        }
        assert result[1]["name"] == "tool-b"


# ---------------------------------------------------------------------------
# call_tool
# ---------------------------------------------------------------------------


class TestCallTool:
    """Verify call_tool delegates to session and returns content."""

    @pytest.mark.asyncio()
    async def test_stdio_client_call_tool(self) -> None:
        """call_tool returns result content from session."""
        from beddel.adapters.mcp.stdio_client import StdioMCPClient

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(
            return_value=SimpleNamespace(content=[{"type": "text", "text": "hello"}])
        )

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "beddel.adapters.mcp.stdio_client.stdio_client",
                return_value=mock_cm,
            ),
            patch(
                "beddel.adapters.mcp.stdio_client.ClientSession",
                return_value=mock_session,
            ),
        ):
            client = StdioMCPClient(command="test-server")
            await client.connect("stdio://test")

            result = await client.call_tool("my-tool", {"arg": "value"})

        assert result == [{"type": "text", "text": "hello"}]
        mock_session.call_tool.assert_awaited_once_with("my-tool", {"arg": "value"})

    @pytest.mark.asyncio()
    async def test_stdio_client_call_tool_error(self) -> None:
        """call_tool wraps exceptions in MCPError(MCP_TOOL_INVOCATION_FAILED)."""
        from beddel.adapters.mcp.stdio_client import StdioMCPClient

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=RuntimeError("tool crashed"))

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "beddel.adapters.mcp.stdio_client.stdio_client",
                return_value=mock_cm,
            ),
            patch(
                "beddel.adapters.mcp.stdio_client.ClientSession",
                return_value=mock_session,
            ),
        ):
            client = StdioMCPClient(command="test-server")
            await client.connect("stdio://test")

            with pytest.raises(MCPError, match="invocation failed") as exc_info:
                await client.call_tool("bad-tool", {})
            assert exc_info.value.code == MCP_TOOL_INVOCATION_FAILED

    @pytest.mark.asyncio()
    async def test_call_tool_not_connected_raises(self) -> None:
        """call_tool raises MCPError when not connected."""
        from beddel.adapters.mcp.stdio_client import StdioMCPClient

        client = StdioMCPClient(command="test-server")

        with pytest.raises(MCPError, match="Not connected") as exc_info:
            await client.call_tool("tool", {})
        assert exc_info.value.code == MCP_CONNECTION_FAILED


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Verify StdioMCPClient satisfies IMCPClient protocol."""

    def test_satisfies_imcp_client_protocol(self) -> None:
        """StdioMCPClient is structurally compatible with IMCPClient."""
        from beddel.adapters.mcp.stdio_client import StdioMCPClient

        # Verify all required methods exist with correct names
        for method_name in ("connect", "list_tools", "call_tool", "disconnect"):
            assert hasattr(StdioMCPClient, method_name), f"StdioMCPClient missing {method_name}"

        # Verify methods are callable
        client = StdioMCPClient(command="test")
        for method_name in ("connect", "list_tools", "call_tool", "disconnect"):
            assert callable(getattr(client, method_name))
