"""Beddel serve-mcp-kit — expose YAML workflows as MCP servers.

Any MCP-compatible agent (Claude, Kiro, Cursor, OpenClaw) can discover
and execute Beddel workflows via the standard Model Context Protocol.
"""

from __future__ import annotations

from beddel_serve_mcp.server import BeddelMCPServer, create_mcp_server

__all__ = ["BeddelMCPServer", "create_mcp_server"]
