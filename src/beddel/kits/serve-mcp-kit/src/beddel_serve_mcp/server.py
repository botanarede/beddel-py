"""Beddel MCP Server — exposes YAML workflows as MCP tools.

Each workflow becomes one MCP tool:
- ``workflow.id`` → tool name
- ``workflow.description`` → tool description
- ``workflow.input_schema`` → MCP ``inputSchema``
- ``WorkflowExecutor.execute()`` → tool handler
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import DefaultDependencies, Workflow
from beddel.domain.parser import WorkflowParser
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins

logger = logging.getLogger(__name__)


class BeddelMCPServer:
    """Wraps Beddel workflows as MCP tools via FastMCP.

    Args:
        name: Server name shown to MCP clients.
        registry: Primitive registry (auto-populated with builtins if None).
        deps: Execution dependencies (optional).
    """

    def __init__(
        self,
        name: str = "Beddel Workflows",
        *,
        registry: PrimitiveRegistry | None = None,
        deps: DefaultDependencies | None = None,
    ) -> None:
        self._mcp = FastMCP(name)
        self._registry = registry or self._default_registry()
        self._deps = deps
        self._workflows: dict[str, Workflow] = {}

    @staticmethod
    def _default_registry() -> PrimitiveRegistry:
        reg = PrimitiveRegistry()
        register_builtins(reg)
        return reg

    def register_workflow(self, workflow: Workflow) -> None:
        """Register a workflow as an MCP tool.

        The workflow's ``id`` becomes the tool name, its ``description``
        becomes the tool description, and its ``input_schema`` becomes
        the MCP ``inputSchema``.
        """
        self._workflows[workflow.id] = workflow
        tool_name = workflow.id
        tool_desc = workflow.description or f"Execute the '{workflow.id}' workflow"

        # Build the async handler that executes the workflow
        async def _handler(**kwargs: Any) -> str:
            executor = WorkflowExecutor(self._registry, deps=self._deps)
            result = await executor.execute(workflow, inputs=kwargs)
            step_results = result.get("step_results", {})
            return json.dumps(step_results, default=str, ensure_ascii=False)

        # Register with FastMCP using add_tool for dynamic registration
        # FastMCP.tool() is a decorator; for dynamic use we access the
        # underlying server's tool registration.
        self._mcp.tool(name=tool_name, description=tool_desc)(_handler)
        logger.info("Registered MCP tool: %s", tool_name)

    def register_workflows(self, workflows: list[Workflow]) -> None:
        """Register multiple workflows as MCP tools."""
        for wf in workflows:
            self.register_workflow(wf)

    @property
    def mcp(self) -> FastMCP:
        """Access the underlying FastMCP instance."""
        return self._mcp

    @property
    def tool_count(self) -> int:
        """Number of registered workflow tools."""
        return len(self._workflows)

    def run(
        self,
        transport: str = "stdio",
        host: str = "127.0.0.1",
        port: int = 8000,
    ) -> None:
        """Start the MCP server.

        Args:
            transport: ``"stdio"`` (default) or ``"streamable-http"``.
            host: Bind address for HTTP transports.
            port: Bind port for HTTP transports.
        """
        if transport == "stdio":
            self._mcp.run(transport="stdio")
        elif transport in ("streamable-http", "sse"):
            self._mcp.run(transport=transport, host=host, port=port)
        else:
            msg = f"Unsupported transport: {transport!r}. Use 'stdio' or 'streamable-http'."
            raise ValueError(msg)


def create_mcp_server(
    workflow_dir: str | Path,
    *,
    name: str = "Beddel Workflows",
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    registry: PrimitiveRegistry | None = None,
    deps: DefaultDependencies | None = None,
) -> BeddelMCPServer:
    """Scan a directory for YAML workflows and create an MCP server.

    Each ``*.yaml`` file is parsed as a Beddel workflow and registered
    as an MCP tool.  The server can then be started with ``.run()``.

    Args:
        workflow_dir: Directory containing ``*.yaml`` workflow files.
        name: Server name shown to MCP clients.
        transport: ``"stdio"`` (default) or ``"streamable-http"``.
        host: Bind address for HTTP transports.
        port: Bind port for HTTP transports.
        registry: Primitive registry (auto-populated if None).
        deps: Execution dependencies (optional).

    Returns:
        A configured :class:`BeddelMCPServer` ready to ``.run()``.
    """
    workflow_path = Path(workflow_dir)
    if not workflow_path.is_dir():
        msg = f"Workflow directory not found: {workflow_path}"
        raise FileNotFoundError(msg)

    server = BeddelMCPServer(name, registry=registry, deps=deps)

    yaml_files = sorted(workflow_path.glob("*.yaml"))
    if not yaml_files:
        logger.warning("No *.yaml files found in %s", workflow_path)
        return server

    for yaml_file in yaml_files:
        try:
            workflow = WorkflowParser.parse(yaml_file.read_text())
            server.register_workflow(workflow)
            logger.info("Loaded workflow: %s from %s", workflow.id, yaml_file.name)
        except Exception:
            logger.exception("Failed to parse %s — skipping", yaml_file.name)

    logger.info(
        "MCP server ready: %d workflow(s) registered as tools", server.tool_count
    )
    return server
