"""Beddel CLI commands."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click


def _build_tool_registry(
    workflow: Any,
    parsed_tools: dict[str, Callable[..., Any]],
) -> dict[str, Callable[..., Any]]:
    """Build a merged tool registry using the 3-layer override pattern.

    Merge order (later layers override earlier ones):
      1. ``discover_builtin_tools()`` — built-in tools from ``beddel.tools.*``
      2. ``workflow.metadata["_inline_tools"]`` — inline YAML ``tools:`` section
      3. ``parsed_tools`` — CLI ``--tool`` flags

    Args:
        workflow: Parsed :class:`~beddel.domain.models.Workflow` instance.
        parsed_tools: Dict of tools resolved from ``--tool`` CLI flags.

    Returns:
        Merged dict mapping tool names to callables.
    """
    from beddel.tools import discover_builtin_tools

    merged = discover_builtin_tools()
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
def run(
    workflow_path: Path,
    inputs: tuple[str, ...],
    tools: tuple[str, ...],
    *,
    as_json: bool,
) -> None:
    """Execute a workflow and print results."""
    from beddel.adapters.kiro_cli import KiroCLIAgentAdapter
    from beddel.adapters.litellm_adapter import LiteLLMAdapter
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
    merged_tools = _build_tool_registry(workflow, parsed_tools)
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
@click.option("--status", "show_status", is_flag=True, help="Show auth status.")
@click.option("--logout", is_flag=True, help="Remove stored credentials.")
@click.option("--server", type=str, default=None, help="Set dashboard server URL.")
def connect(*, show_status: bool, logout: bool, server: str | None) -> None:
    """Authenticate with GitHub for remote dashboard access."""
    import datetime
    import os

    from beddel.adapters.github_auth import (
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
        click.echo(f"Server: {creds.get('server_url') or '(not set)'}")
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

    # Default: full Device Flow
    client_id = os.environ.get("BEDDEL_GITHUB_CLIENT_ID")
    if not client_id:
        click.echo(
            "BEDDEL_GITHUB_CLIENT_ID environment variable is required.",
            err=True,
        )
        raise SystemExit(1)

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

        save_credentials(
            CredentialData(
                access_token=token,
                github_user=user,
                server_url=None,
                created_at=datetime.datetime.now(datetime.UTC).isoformat(),
            )
        )
        click.echo(f"Authenticated as {user}.")
    except BeddelError as exc:
        click.echo(f"Error [{exc.code}]: {exc.message}", err=True)
        raise SystemExit(1) from None


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
    "--dashboard",
    is_flag=True,
    default=False,
    help="Mount Dashboard Server Protocol endpoints at /api.",
)
@click.option(
    "--remote",
    is_flag=True,
    default=False,
    help="Enable token validation middleware for remote access.",
)
@click.option(
    "--allowed-users",
    type=str,
    default=None,
    help="Comma-separated list of allowed GitHub usernames.",
)
@click.option(
    "--tunnel-domain",
    type=str,
    default=None,
    help="Cloudflare tunnel domain for CORS.",
)
def serve(
    host: str,
    port: int,
    workflow_paths: tuple[Path, ...],
    tools: tuple[str, ...],
    *,
    dashboard: bool,
    remote: bool,
    allowed_users: str | None,
    tunnel_domain: str | None,
) -> None:
    """Start a FastAPI server exposing workflows as SSE endpoints."""
    try:
        import uvicorn  # type: ignore[import-not-found]
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        click.echo(
            "Missing dependencies. Install with: pip install beddel[cli]",
            err=True,
        )
        raise SystemExit(1) from None

    from beddel import __version__
    from beddel.adapters.kiro_cli import KiroCLIAgentAdapter
    from beddel.adapters.litellm_adapter import LiteLLMAdapter
    from beddel.domain.errors import BeddelError
    from beddel.domain.models import DefaultDependencies, Workflow
    from beddel.domain.parser import WorkflowParser
    from beddel.domain.registry import PrimitiveRegistry
    from beddel.integrations.fastapi import create_beddel_handler
    from beddel.primitives import register_builtins

    if allowed_users and not remote:
        click.echo("Warning: --allowed-users ignored without --remote.", err=True)

    app = FastAPI(title="Beddel", version=__version__)

    # Determine CORS origins based on mode
    if remote:
        cors_origins = [f"https://{tunnel_domain}"] if tunnel_domain else ["*"]
    else:
        cors_origins = ["http://localhost:3000"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add auth middleware AFTER CORS (Starlette LIFO: auth runs first)
    if remote:
        from beddel.integrations.dashboard.auth_middleware import (
            create_auth_middleware,
        )

        parsed_users: list[str] | None = None
        if allowed_users:
            parsed_users = [u.strip() for u in allowed_users.split(",") if u.strip()]
        middleware_cls = create_auth_middleware(allowed_users=parsed_users)
        app.add_middleware(middleware_cls)
        click.echo("Remote mode enabled — token validation active")

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
            tool_registry=_build_tool_registry(workflow, parsed_tools),
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

    if dashboard and all_workflows:
        from beddel.domain.executor import WorkflowExecutor
        from beddel.integrations.dashboard import create_dashboard_router

        dashboard_deps = DefaultDependencies(
            llm_provider=adapter,
            agent_registry={"kiro-cli": KiroCLIAgentAdapter()},
            registry=registry,
        )
        shared_executor = WorkflowExecutor(registry, deps=dashboard_deps)
        dashboard_router = create_dashboard_router(all_workflows, shared_executor)
        app.include_router(dashboard_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    click.echo(f"Beddel v{__version__} — {loaded} workflow(s)")
    click.echo(f"Listening on http://{host}:{port}")
    click.echo(f"Health: http://{host}:{port}/health")
    if dashboard:
        click.echo(f"Dashboard API: http://{host}:{port}/api")

    uvicorn.run(app, host=host, port=port, log_level="info")
