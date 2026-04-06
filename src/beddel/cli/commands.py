"""Beddel CLI commands."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kit sys.path helper (ADR-0008, Story 5.1.1 Task 5)
# ---------------------------------------------------------------------------
# commands.py lives at: <project_root>/src/beddel-py/src/beddel/cli/commands.py
#   parents[0] = cli/
#   parents[1] = beddel/
#   parents[2] = src/          (beddel-py/src)
#   parents[3] = beddel-py/
#   parents[4] = src/          (top-level src/)
#   parents[5] = <project_root>
_PROJECT_ROOT = Path(__file__).resolve().parents[5]


def _ensure_kit_paths() -> None:
    """Add all kit ``src/`` directories to ``sys.path`` if not already present.

    Scans both bundled kits (``beddel/kits/``) and project-local kits
    (``<project_root>/kits/``).
    """
    from beddel.kits import BUNDLED_KITS_PATH

    # Bundled kits shipped inside the package
    if BUNDLED_KITS_PATH.is_dir():
        for kit_dir in BUNDLED_KITS_PATH.iterdir():
            kit_src = kit_dir / "src"
            if kit_src.is_dir() and str(kit_src) not in sys.path:
                sys.path.insert(0, str(kit_src))

    # Project-local kits
    kits_dir = _PROJECT_ROOT / "kits"
    if not kits_dir.is_dir():
        return
    for kit_dir in kits_dir.iterdir():
        kit_src = kit_dir / "src"
        if kit_src.is_dir() and str(kit_src) not in sys.path:
            sys.path.insert(0, str(kit_src))


def _build_tool_registry(
    workflow: Any,
    parsed_tools: dict[str, Callable[..., Any]],
    *,
    kit_paths: list[Path] | None = None,
    no_kits: bool = False,
) -> dict[str, Callable[..., Any]]:
    """Build a merged tool registry using the 3-layer override pattern.

    Merge order (later layers override earlier ones):
      1. Kit tools — discovered via ``discover_kits()`` / ``load_kit()``
      2. ``workflow.metadata["_inline_tools"]`` — inline YAML ``tools:`` section
      3. ``parsed_tools`` — CLI ``--tool`` flags

    Args:
        workflow: Parsed :class:`~beddel.domain.models.Workflow` instance.
        parsed_tools: Dict of tools resolved from ``--tool`` CLI flags.
        kit_paths: Directories to scan for kits. *None* uses defaults.
        no_kits: When *True*, skip kit discovery entirely.

    Returns:
        Merged dict mapping tool names to callables.
    """
    merged: dict[str, Callable[..., Any]] = {}

    # Layer 1: kit tools
    if not no_kits:
        import os

        from beddel.domain.errors import KitDependencyError, KitManifestError
        from beddel.domain.kit import KitDiscoveryResult
        from beddel.error_codes import KIT_RESOLUTION_AMBIGUOUS
        from beddel.tools.kits import discover_kits, load_kit

        strict = os.environ.get("BEDDEL_KIT_STRICT", "").lower() == "true"
        discovery_result: KitDiscoveryResult = discover_kits(kit_paths)

        # Build set of collided tool names and log warnings
        collided_names: set[str] = set()
        for collision in discovery_result.collisions:
            collided_names.add(collision.tool_name)
            logger.warning(
                "Kit tool collision: '%s' declared by %s. Use namespaced form.",
                collision.tool_name,
                collision.kit_names,
            )

        for manifest in discovery_result.manifests:
            kit_name = manifest.kit.name
            try:
                kit_tools = load_kit(manifest)
            except KitDependencyError as exc:
                logger.warning(
                    "BEDDEL-KIT-658: Kit '%s' skipped — missing dependencies: %s",
                    kit_name,
                    exc.missing_packages,
                )
                continue
            except KitManifestError as exc:
                logger.warning("Skipping kit '%s': %s", kit_name, exc.message)
                continue
            for tool_name, tool_fn in kit_tools.items():
                # Always register namespaced form
                merged[f"{kit_name}:{tool_name}"] = tool_fn
                # Register unnamespaced form only when no collision
                if tool_name not in collided_names:
                    merged[tool_name] = tool_fn

        # Strict mode: raise on ambiguous unnamespaced references
        if strict and collided_names:
            raise KitManifestError(
                code=KIT_RESOLUTION_AMBIGUOUS,
                message=(
                    f"Ambiguous unnamespaced tool name(s): "
                    f"{', '.join(sorted(collided_names))}. "
                    f"Use namespaced form or disable strict mode."
                ),
                details={"collided_names": sorted(collided_names)},
            )

    merged.update(workflow.metadata.get("_inline_tools", {}))
    merged.update(parsed_tools)
    return merged


def _parse_tool_flags(tools: tuple[str, ...]) -> dict[str, Callable[..., Any]]:
    """Parse ``--tool name=module:function`` flags into a callable registry.

    Args:
        tools: Tuple of tool specifications in ``name=module:function`` format.

    Returns:
        Dict mapping tool names to resolved callables.

    Raises:
        click.BadParameter: If format is invalid, import fails, or target
            is not callable.
    """
    registry: dict[str, Callable[..., Any]] = {}
    for spec in tools:
        if "=" not in spec:
            raise click.BadParameter(
                f"Expected format 'name=module:function', got {spec!r}",
                param_hint="'--tool'",
            )
        name, target = spec.split("=", 1)
        if not name:
            raise click.BadParameter(
                f"Tool name must not be empty in {spec!r}",
                param_hint="'--tool'",
            )
        if ":" not in target:
            raise click.BadParameter(
                f"Expected format 'name=module:function', got {spec!r}",
                param_hint="'--tool'",
            )
        module_path, func_name = target.split(":", 1)
        try:
            mod = importlib.import_module(module_path)
            obj = getattr(mod, func_name)
        except (ImportError, AttributeError, ValueError) as exc:
            raise click.BadParameter(
                f"Cannot import tool '{name}': {module_path}:{func_name} — {exc}",
                param_hint="'--tool'",
            ) from exc
        if not callable(obj):
            raise click.BadParameter(
                f"Tool '{name}': {module_path}:{func_name} is not callable"
                f" (got {type(obj).__name__})",
                param_hint="'--tool'",
            )
        registry[name] = obj
    return registry


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def cli(*, verbose: bool) -> None:
    """Beddel — declarative YAML-based AI workflow engine."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@cli.command()
def version() -> None:
    """Print the Beddel version."""
    from beddel import __version__

    click.echo(f"beddel {__version__}")


@cli.command()
@click.argument("workflow_path", type=click.Path(exists=True, path_type=Path))
def validate(workflow_path: Path) -> None:
    """Validate a YAML workflow file."""
    from beddel.domain.errors import ParseError
    from beddel.domain.parser import WorkflowParser

    yaml_str = workflow_path.read_text()
    try:
        workflow = WorkflowParser.parse(yaml_str)
    except ParseError as exc:
        click.echo(f"INVALID: {exc.message}", err=True)
        raise SystemExit(1) from None

    primitives = [s.primitive for s in workflow.steps]
    click.echo(f"OK: {workflow.id}")
    click.echo(f"  name: {workflow.name}")
    click.echo(f"  steps: {len(workflow.steps)}")
    click.echo(f"  primitives: {', '.join(primitives)}")


@cli.command("list-primitives")
def list_primitives() -> None:
    """List all registered built-in primitives."""
    from beddel.domain.registry import PrimitiveRegistry
    from beddel.primitives import register_builtins

    registry = PrimitiveRegistry()
    register_builtins(registry)
    for name in registry.list_primitives():
        click.echo(name)


@cli.command()
@click.argument("workflow_path", type=click.Path(exists=True, path_type=Path))
@click.option("--input", "-i", "inputs", multiple=True, help="Input as key=value.")
@click.option("--json-output", "as_json", is_flag=True, help="Output raw JSON.")
@click.option(
    "--tool",
    "-t",
    "tools",
    multiple=True,
    help="Register tool as name=module:function.",
)
@click.option(
    "--kit",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="Load kit from path.",
)
@click.option("--no-kits", is_flag=True, default=False, help="Disable kit discovery.")
def run(
    workflow_path: Path,
    inputs: tuple[str, ...],
    tools: tuple[str, ...],
    kit: tuple[Path, ...],
    *,
    as_json: bool,
    no_kits: bool,
) -> None:
    """Execute a workflow and print results."""
    _ensure_kit_paths()
    from beddel_agent_kiro.adapter import KiroCLIAgentAdapter
    from beddel_provider_litellm.adapter import LiteLLMAdapter

    from beddel.domain.errors import BeddelError
    from beddel.domain.executor import WorkflowExecutor
    from beddel.domain.models import DefaultDependencies, Workflow
    from beddel.domain.parser import WorkflowParser
    from beddel.domain.registry import PrimitiveRegistry
    from beddel.primitives import register_builtins

    # Parse inputs
    input_dict: dict[str, Any] = {}
    for item in inputs:
        if "=" not in item:
            click.echo(f"Invalid input format: {item!r} (expected key=value)", err=True)
            raise SystemExit(1)
        key, value = item.split("=", 1)
        input_dict[key] = value

    # Load workflow
    yaml_str = workflow_path.read_text()
    try:
        workflow = WorkflowParser.parse(yaml_str)
    except BeddelError as exc:
        click.echo(f"Error: {exc.message}", err=True)
        raise SystemExit(1) from None

    # Build executor
    registry = PrimitiveRegistry()
    register_builtins(registry)
    adapter = LiteLLMAdapter()

    def _safe_workflow_loader(name: str) -> Workflow:
        """Load a sub-workflow by name, confined to the parent directory."""
        target = (workflow_path.parent / name).resolve()
        root = workflow_path.parent.resolve()
        if not target.is_relative_to(root):
            raise BeddelError(
                code="BEDDEL-CLI-001",
                message=f"Workflow path escapes base directory: {name}",
            )
        if not target.exists():
            raise BeddelError(
                code="BEDDEL-CLI-002",
                message=f"Sub-workflow not found: {name} (resolved: {target})",
            )
        return WorkflowParser.parse(target.read_text())

    parsed_tools = _parse_tool_flags(tools)
    merged_tools = _build_tool_registry(
        workflow,
        parsed_tools,
        kit_paths=list(kit) if kit else None,
        no_kits=no_kits,
    )
    deps = DefaultDependencies(
        llm_provider=adapter,
        agent_registry={"kiro-cli": KiroCLIAgentAdapter()},
        tool_registry=merged_tools,
        workflow_loader=_safe_workflow_loader,
        registry=registry,
    )
    executor = WorkflowExecutor(registry, deps=deps)

    # Execute
    try:
        result = asyncio.run(executor.execute(workflow, input_dict))
    except BeddelError as exc:
        click.echo(f"Execution error [{exc.code}]: {exc.message}", err=True)
        raise SystemExit(1) from None

    # Output
    if as_json:
        output = {}
        for step_id, step_result in result.get("step_results", {}).items():
            try:
                json.dumps(step_result)
                output[step_id] = step_result
            except (TypeError, ValueError):
                output[step_id] = str(step_result)
        click.echo(json.dumps(output, indent=2))
    else:
        for step_id, step_result in result.get("step_results", {}).items():
            click.echo(f"[{step_id}]")
            if isinstance(step_result, dict) and "content" in step_result:
                click.echo(step_result["content"])
            else:
                click.echo(str(step_result))
            click.echo()


@cli.command()
def status() -> None:
    """Show connection status for the remote dashboard."""
    _ensure_kit_paths()
    from beddel_auth_github.provider import (  # type: ignore[import-not-found]
        check_token_validity,
        load_credentials,
    )

    creds = load_credentials()
    if creds is None:
        click.echo("Not connected to any remote server.")
        return

    click.echo(f"Server: {creds.get('server_url') or 'https://connect.beddel.com.br'}")
    click.echo(f"User: {creds['github_user']}")
    click.echo(f"Created: {creds['created_at']}")

    valid = asyncio.run(check_token_validity(creds["access_token"]))
    if valid:
        click.echo("Token: valid")
    else:
        click.echo("Token: expired. Run `beddel connect` to re-authenticate.")


@cli.command()
@click.option("--status", "show_status", is_flag=True, help="Show auth status.")
@click.option("--logout", is_flag=True, help="Remove stored credentials.")
@click.option("--server", type=str, default=None, help="Set dashboard server URL.")
@click.option("--listen", is_flag=True, help="Listen for commands from dashboard.")
def connect(*, show_status: bool, logout: bool, server: str | None, listen: bool) -> None:
    """Authenticate with GitHub for remote dashboard access."""
    import datetime
    import os

    _ensure_kit_paths()
    from beddel_auth_github.provider import (
        CredentialData,
        delete_credentials,
        get_github_user,
        initiate_device_flow,
        load_credentials,
        poll_for_token,
        save_credentials,
    )

    from beddel.domain.errors import BeddelError

    if show_status:
        creds = load_credentials()
        if creds is None:
            click.echo("Not authenticated. Run `beddel connect` to authenticate.")
            return
        click.echo(f"User: {creds['github_user']}")
        click.echo(f"Server: {creds.get('server_url') or 'https://connect.beddel.com.br'}")
        click.echo(f"Created: {creds['created_at']}")
        return

    if logout:
        removed = delete_credentials()
        if removed:
            click.echo("Credentials removed.")
        else:
            click.echo("No credentials found.")
        return

    if server is not None:
        creds = load_credentials()
        if creds is None:
            click.echo("Not authenticated. Run `beddel connect` first.", err=True)
            raise SystemExit(1)
        creds["server_url"] = server
        save_credentials(creds)
        click.echo(f"Server URL updated to {server}")
        return

    if listen:
        creds = load_credentials()
        if creds is None:
            click.echo("Not authenticated. Run `beddel connect` first.", err=True)
            raise SystemExit(1)
        pat = creds["access_token"]
        srv = creds.get("server_url") or "https://connect.beddel.com.br"
        asyncio.run(_listen_loop(srv, pat))
        return

    # Default: full Device Flow
    # Client ID is public (same pattern as GitHub CLI — safe to embed).
    # Override via env var for self-hosted GitHub Apps.
    client_id = os.environ.get("BEDDEL_GITHUB_CLIENT_ID", "Ov23lieA07aQzUjKcAHk")

    try:
        flow = asyncio.run(initiate_device_flow(client_id))
        click.echo(f"Enter code: {flow['user_code']}")
        click.echo(f"Open: {flow['verification_uri']}")

        token = asyncio.run(
            poll_for_token(
                client_id,
                flow["device_code"],
                interval=flow["interval"],
                expires_in=flow["expires_in"],
            )
        )

        user = asyncio.run(get_github_user(token))

        dashboard_url = "https://connect.beddel.com.br"
        save_credentials(
            CredentialData(
                access_token=token,
                github_user=user,
                server_url=dashboard_url,
                created_at=datetime.datetime.now(datetime.UTC).isoformat(),
            )
        )
        click.echo(f"Authenticated as {user}.")

        # Token exchange: establish browser session on dashboard
        browser_url = dashboard_url  # fallback: open dashboard root
        try:
            import httpx

            async def _exchange() -> str | None:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    resp = await http.post(
                        f"{dashboard_url}/api/auth/exchange",
                        json={"access_token": token},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return data.get("session_id")
                    return None

            session_id = asyncio.run(_exchange())
            if session_id:
                browser_url = f"{dashboard_url}/auth/callback?code={session_id}"
        except Exception as exc:
            click.echo(
                f"Warning: Could not establish browser session: {exc}",
                err=True,
            )

        import contextlib
        import webbrowser

        with contextlib.suppress(Exception):
            webbrowser.open(browser_url)
        click.echo(f"Dashboard: {dashboard_url}")
    except BeddelError as exc:
        click.echo(f"Error [{exc.code}]: {exc.message}", err=True)
        raise SystemExit(1) from None


# ---------------------------------------------------------------------------
# SSE listen-mode helpers (Task 6 — Epic D10)
# ---------------------------------------------------------------------------


async def _listen_loop(server_url: str, token: str) -> None:
    """Listen for commands from dashboard via SSE."""
    import signal

    import httpx

    stop_event = asyncio.Event()

    def _handle_signal(*_: object) -> None:
        click.echo("\nDisconnecting...")
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    backoff = 1.0
    max_backoff = 30.0

    while not stop_event.is_set():
        try:
            click.echo(f"Listening for commands from {server_url}...")
            async with httpx.AsyncClient(timeout=None) as client:  # noqa: SIM117
                async with client.stream(
                    "GET",
                    f"{server_url}/api/sse/connect",
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    if response.status_code != 200:
                        click.echo(
                            f"SSE connect failed: {response.status_code}",
                            err=True,
                        )
                        break

                    backoff = 1.0  # Reset on successful connect
                    buffer = ""
                    async for chunk in response.aiter_text():
                        if stop_event.is_set():
                            break
                        buffer += chunk
                        while "\n\n" in buffer:
                            event_str, buffer = buffer.split("\n\n", 1)
                            await _handle_sse_event(event_str, server_url, token)

        except (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.RemoteProtocolError,
        ) as exc:
            if stop_event.is_set():
                break
            click.echo(
                f"Connection lost: {exc}. Retrying in {backoff:.0f}s...",
                err=True,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        except Exception as exc:
            click.echo(f"Unexpected error: {exc}", err=True)
            break

    click.echo("Disconnected.")


async def _handle_sse_event(event_str: str, server_url: str, token: str) -> None:
    """Handle a single SSE event from the dashboard."""
    # Parse SSE data lines
    data_lines: list[str] = []
    for line in event_str.strip().split("\n"):
        if line.startswith("data: "):
            data_lines.append(line[6:])
    if not data_lines:
        return

    try:
        data = json.loads("".join(data_lines))
    except json.JSONDecodeError:
        return

    event_type = data.get("type")

    if event_type == "heartbeat":
        return  # Silent heartbeat

    if event_type == "connected":
        click.echo(f"Connected as {data.get('username', 'unknown')}.")
        return

    if event_type == "command" and data.get("action") == "run":
        workflow_id: str = data.get("workflow_id", "unknown")
        inputs: dict[str, Any] = data.get("inputs", {})
        click.echo(f"Received: run workflow {workflow_id}")
        await _execute_and_stream(workflow_id, inputs, server_url, token)


async def _execute_and_stream(
    workflow_id: str,
    inputs: dict[str, Any],
    server_url: str,
    token: str,
) -> None:
    """Execute a workflow and stream events back to dashboard."""
    import contextlib

    import httpx

    try:
        _ensure_kit_paths()
        from beddel.domain.executor import WorkflowExecutor
        from beddel.domain.parser import WorkflowParser
        from beddel.domain.registry import PrimitiveRegistry
        from beddel.primitives import register_builtins

        # Try to find the workflow file
        workflow_path = Path(workflow_id)
        if not workflow_path.exists():
            for prefix in [Path("."), Path("workflows"), Path("agents")]:
                candidate = prefix / f"{workflow_id}.yaml"
                if candidate.exists():
                    workflow_path = candidate
                    break
                candidate = prefix / f"{workflow_id}.yml"
                if candidate.exists():
                    workflow_path = candidate
                    break

        if not workflow_path.exists():
            click.echo(f"Workflow not found: {workflow_id}", err=True)
            return

        workflow = WorkflowParser.parse(workflow_path.read_text())
        registry = PrimitiveRegistry()
        register_builtins(registry)
        executor = WorkflowExecutor(registry)

        async with httpx.AsyncClient(timeout=10.0) as client:
            async for event in executor.execute_stream(workflow, inputs):
                payload: dict[str, Any] = {
                    "type": "event",
                    "event_type": (
                        event.event_type.value
                        if hasattr(event.event_type, "value")
                        else str(event.event_type)
                    ),
                    "payload": (
                        event.model_dump()
                        if hasattr(event, "model_dump")
                        else {"data": str(event)}
                    ),
                }
                with contextlib.suppress(httpx.HTTPError):
                    await client.post(
                        f"{server_url}/api/sse/events",
                        json=payload,
                        headers={"Authorization": f"Bearer {token}"},
                    )

        click.echo(f"Workflow {workflow_id} completed.")
    except Exception as exc:
        click.echo(f"Workflow execution error: {exc}", err=True)


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind host.")
@click.option("--port", default=8000, type=int, help="Bind port.")
@click.option(
    "--workflow",
    "-w",
    "workflow_paths",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Workflow YAML file to serve (repeatable).",
)
@click.option(
    "--tool",
    "-t",
    "tools",
    multiple=True,
    help="Register tool as name=module:function.",
)
@click.option(
    "--kit",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="Load kit from path.",
)
@click.option("--no-kits", is_flag=True, default=False, help="Disable kit discovery.")
@click.option(
    "--mcp",
    is_flag=True,
    default=False,
    help="Start as MCP server instead of FastAPI.",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    help="MCP transport (default: stdio).",
)
@click.option(
    "--name",
    "server_name",
    default="Beddel Workflows",
    help="MCP server name.",
)
def serve(
    host: str,
    port: int,
    workflow_paths: tuple[Path, ...],
    tools: tuple[str, ...],
    kit: tuple[Path, ...],
    *,
    mcp: bool,
    transport: str,
    server_name: str,
    no_kits: bool,
) -> None:
    """Start a FastAPI server exposing workflows as SSE endpoints."""
    # MCP mode — branch early, skip FastAPI
    if mcp:
        _ensure_kit_paths()
        from beddel_serve_mcp.server import BeddelMCPServer

        from beddel.domain.parser import WorkflowParser

        if workflow_paths:
            server = BeddelMCPServer(server_name)
            for wf_path in workflow_paths:
                workflow = WorkflowParser.parse(wf_path.read_text())
                server.register_workflow(workflow)
        else:
            from beddel_serve_mcp.server import create_mcp_server

            server = create_mcp_server(Path("."), name=server_name)

        click.echo(f"Beddel MCP Server: {server_name}", err=True)
        click.echo(f"  Workflows: {server.tool_count}", err=True)
        click.echo(f"  Transport: {transport}", err=True)
        if transport != "stdio":
            click.echo(f"  Listening: http://{host}:{port}", err=True)

        server.run(transport=transport, host=host, port=port)
        return

    try:
        import uvicorn
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        click.echo(
            "Missing dependencies. Install with: pip install beddel[cli]",
            err=True,
        )
        raise SystemExit(1) from None

    from beddel import __version__

    _ensure_kit_paths()
    from beddel_agent_kiro.adapter import KiroCLIAgentAdapter
    from beddel_provider_litellm.adapter import LiteLLMAdapter

    from beddel.domain.errors import BeddelError
    from beddel.domain.models import DefaultDependencies, Workflow
    from beddel.domain.parser import WorkflowParser
    from beddel.domain.registry import PrimitiveRegistry
    from beddel.integrations.fastapi import create_beddel_handler
    from beddel.primitives import register_builtins

    app = FastAPI(title="Beddel", version=__version__)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    registry = PrimitiveRegistry()
    register_builtins(registry)
    adapter = LiteLLMAdapter()
    parsed_tools = _parse_tool_flags(tools)

    loaded = 0
    all_workflows: dict[str, Workflow] = {}
    for wf_path in workflow_paths:
        yaml_str = wf_path.read_text()
        workflow = WorkflowParser.parse(yaml_str)

        wf_parent = wf_path.parent.resolve()

        def _make_workflow_loader(root: Path) -> Callable[[str], Workflow]:
            """Return a workflow loader scoped to *root*."""

            def _loader(name: str) -> Workflow:
                target = (root / name).resolve()
                if not target.is_relative_to(root):
                    raise BeddelError(
                        code="BEDDEL-CLI-001",
                        message=f"Workflow path escapes base directory: {name}",
                    )
                if not target.exists():
                    raise BeddelError(
                        code="BEDDEL-CLI-002",
                        message=(f"Sub-workflow not found: {name} (resolved: {target})"),
                    )
                return WorkflowParser.parse(target.read_text())

            return _loader

        deps = DefaultDependencies(
            llm_provider=adapter,
            agent_registry={"kiro-cli": KiroCLIAgentAdapter()},
            tool_registry=_build_tool_registry(
                workflow,
                parsed_tools,
                kit_paths=list(kit) if kit else None,
                no_kits=no_kits,
            ),
            workflow_loader=_make_workflow_loader(wf_parent),
            registry=registry,
        )
        router = create_beddel_handler(
            workflow,
            deps=deps,
        )
        app.include_router(router, prefix=f"/workflows/{workflow.id}")
        click.echo(f"  Mounted: /workflows/{workflow.id} ({wf_path.name})")
        all_workflows[workflow.id] = workflow
        loaded += 1

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    click.echo(f"Beddel v{__version__} — {loaded} workflow(s)")
    click.echo(f"Listening on http://{host}:{port}")
    click.echo(f"Health: http://{host}:{port}/health")

    uvicorn.run(app, host=host, port=port, log_level="info")


# ---------------------------------------------------------------------------
# Kit management commands
# ---------------------------------------------------------------------------


@cli.group()
def kit() -> None:
    """Manage solution kits."""


_OFFICIAL_REPO = "botanarede/beddel"
_OFFICIAL_BRANCH = "main"
_KITS_PREFIX = "kits"


def _resolve_kit_source(source: str) -> Path:
    """Resolve a kit source to a local directory path.

    Supports:
    - Local path: ``./my-kit/`` or ``/abs/path/to/kit``
    - GitHub explicit: ``github:owner/repo/kits/kit-name``
    - Short name: ``provider-litellm-kit`` (resolves to official repo)

    Returns:
        Path to a local directory containing ``kit.yaml``.
    """
    import shutil
    import subprocess
    import tempfile

    local = Path(source)
    if local.is_dir() and (local / "kit.yaml").is_file():
        return local

    # Parse GitHub source
    if source.startswith("github:"):
        # github:owner/repo/kits/kit-name[@branch]
        rest = source[len("github:") :]
        parts = rest.split("/")
        if len(parts) < 3:
            click.echo(
                f"Invalid github source: {source}\nExpected: github:owner/repo/path/to/kit",
                err=True,
            )
            raise SystemExit(1)
        owner_repo = f"{parts[0]}/{parts[1]}"
        kit_path = "/".join(parts[2:])
        branch = _OFFICIAL_BRANCH
        if "@" in parts[-1]:
            last, branch = parts[-1].rsplit("@", 1)
            kit_path = "/".join(parts[2:-1] + [last])
    else:
        # Short name: treat as official repo kit
        owner_repo = _OFFICIAL_REPO
        kit_path = f"{_KITS_PREFIX}/{source}"
        branch = _OFFICIAL_BRANCH

    # Download via git sparse checkout
    tmp = Path(tempfile.mkdtemp(prefix="beddel-kit-"))
    url = f"https://github.com/{owner_repo}.git"
    click.echo(f"Fetching {kit_path} from {owner_repo}@{branch}...")

    git = shutil.which("git")
    if git is None:
        click.echo("Error: git is required for remote kit install", err=True)
        raise SystemExit(1)

    try:
        subprocess.run(
            [
                git,
                "clone",
                "--depth=1",
                "--filter=blob:none",
                "--sparse",
                f"--branch={branch}",
                url,
                str(tmp / "repo"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [git, "sparse-checkout", "set", kit_path],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(tmp / "repo"),
        )
    except subprocess.CalledProcessError as exc:
        click.echo(f"Failed to fetch kit: {exc.stderr or exc.stdout}", err=True)
        raise SystemExit(1) from None

    result_dir = tmp / "repo" / kit_path
    if not (result_dir / "kit.yaml").is_file():
        click.echo(
            f"Kit not found at {kit_path} in {owner_repo}@{branch}",
            err=True,
        )
        raise SystemExit(1)

    return result_dir


@kit.command("install")
@click.argument("source")
@click.option("--global", "global_install", is_flag=True, help="Install to ~/.beddel/kits/")
def kit_install(source: str, *, global_install: bool) -> None:
    """Install a solution kit from a local directory or GitHub.

    SOURCE can be:

    \b
      Local path:    ./my-kit/
      Kit name:      provider-litellm-kit  (fetches from official repo)
      GitHub path:   github:owner/repo/kits/kit-name
    """
    import shutil
    import subprocess

    from beddel.domain.errors import KitManifestError
    from beddel.domain.kit import parse_kit_manifest

    # 1. Resolve source to local directory
    kit_dir = _resolve_kit_source(source)
    kit_yaml = kit_dir / "kit.yaml"

    # 2. Validate manifest
    try:
        manifest = parse_kit_manifest(kit_yaml)
    except KitManifestError as exc:
        click.echo(f"Invalid kit manifest: {exc.message}", err=True)
        raise SystemExit(1) from None

    # 3. Install pip dependencies
    deps = manifest.kit.dependencies
    if deps:
        click.echo(f"Installing dependencies: {', '.join(deps)}")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", *deps],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            click.echo(f"Failed to install dependencies: {exc}", err=True)
            raise SystemExit(1) from None

    # 4. Copy kit directory to target
    kit_name = manifest.kit.name
    if global_install:
        target = Path.home() / ".beddel" / "kits" / kit_name
    else:
        target = Path("./kits") / kit_name

    try:
        shutil.copytree(str(kit_dir), str(target), dirs_exist_ok=True)
    except shutil.Error as exc:
        click.echo(f"Failed to copy kit: {exc}", err=True)
        raise SystemExit(1) from None

    click.echo(f"Installed {kit_name} v{manifest.kit.version} to {target}")


@kit.command("list")
def kit_list() -> None:
    """List all discovered solution kits."""
    from beddel.domain.errors import KitDependencyError, KitManifestError
    from beddel.tools.kits import discover_kits, load_kit

    _ensure_kit_paths()
    result = discover_kits()

    if not result.manifests:
        click.echo("No kits found.")
        return

    rows: list[tuple[str, str, str, str, str]] = []
    for manifest in result.manifests:
        name = manifest.kit.name
        version = manifest.kit.version
        source = manifest.source
        path = str(manifest.root_path)
        try:
            load_kit(manifest)
            status = "loaded"
        except KitDependencyError:
            status = "missing-deps"
        except (KitManifestError, Exception):
            status = "error"
        rows.append((name, version, source, status, path))

    headers = ("NAME", "VERSION", "SOURCE", "STATUS", "PATH")
    widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    click.echo(fmt.format(*headers))
    click.echo(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        click.echo(fmt.format(*row))


@kit.command("export")
@click.argument("workflow_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format",
    "fmt",
    required=True,
    type=click.Choice(["skill", "kit", "mcp", "endpoint"]),
    help="Output format for the exported workflow.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    type=click.Path(path_type=Path),
    default=".",
    help="Output directory (default: current directory).",
)
def kit_export(workflow_path: Path, fmt: str, output_dir: Path) -> None:
    """Export a workflow as a skill, kit, MCP server, or endpoint."""
    import yaml

    from beddel.cli.export import export_endpoint, export_kit, export_mcp, export_skill

    raw = yaml.safe_load(workflow_path.read_text())
    if not isinstance(raw, dict):
        click.echo("Error: workflow file must be a YAML mapping.", err=True)
        raise SystemExit(1)

    workflow_meta: dict[str, Any] = {
        "name": raw.get("name", workflow_path.stem),
        "description": raw.get("description", ""),
        "version": raw.get("version", "1.0"),
        "id": raw.get("id", workflow_path.stem),
        "steps": raw.get("steps", []),
        "source_path": workflow_path.resolve(),
        "input_schema": raw.get("input_schema"),
    }

    generators = {
        "skill": export_skill,
        "kit": export_kit,
        "mcp": export_mcp,
        "endpoint": export_endpoint,
    }

    result_path = generators[fmt](workflow_meta, output_dir.resolve())
    click.echo(f"Exported {fmt}: {result_path}")
