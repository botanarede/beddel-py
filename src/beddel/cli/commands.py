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
    """Add all kit ``src/`` directories to ``sys.path`` if not already present."""
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
    """Build a merged tool registry using the 4-layer override pattern.

    Merge order (later layers override earlier ones):
      1. ``discover_builtin_tools()`` — built-in tools from ``beddel.tools.*``
      2. Kit tools — discovered via ``discover_kits()`` / ``load_kit()``
      3. ``workflow.metadata["_inline_tools"]`` — inline YAML ``tools:`` section
      4. ``parsed_tools`` — CLI ``--tool`` flags

    Args:
        workflow: Parsed :class:`~beddel.domain.models.Workflow` instance.
        parsed_tools: Dict of tools resolved from ``--tool`` CLI flags.
        kit_paths: Directories to scan for kits. *None* uses defaults.
        no_kits: When *True*, skip kit discovery entirely.

    Returns:
        Merged dict mapping tool names to callables.
    """
    from beddel.tools import discover_builtin_tools

    merged = discover_builtin_tools()

    # Layer 2: kit tools (between builtins and inline YAML)
    if not no_kits:
        import os
        import warnings

        from beddel.domain.errors import KitManifestError
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

        # Track which builtin names exist before kit merging
        builtin_names: set[str] = set(merged.keys())

        for manifest in discovery_result.manifests:
            kit_name = manifest.kit.name
            try:
                kit_tools = load_kit(manifest)
            except KitManifestError as exc:
                logger.warning("Skipping kit '%s': %s", kit_name, exc.message)
                continue
            for tool_name, tool_fn in kit_tools.items():
                # Always register namespaced form
                merged[f"{kit_name}:{tool_name}"] = tool_fn
                # Emit deprecation warning when kit tool shadows a builtin
                if tool_name in builtin_names:
                    warnings.warn(
                        f"Kit tool '{kit_name}:{tool_name}' shadows builtin"
                        f" tool '{tool_name}'. Use namespaced form.",
                        DeprecationWarning,
                        stacklevel=2,
                    )
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
    from beddel_auth_github.provider import check_token_validity, load_credentials

    creds = load_credentials()
    if creds is None:
        click.echo("Not connected to any remote server.")
        return

    click.echo(f"Server: {creds.get('server_url') or '(not set)'}")
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
def connect(*, show_status: bool, logout: bool, server: str | None) -> None:
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
    "--kit",
    multiple=True,
    type=click.Path(exists=False, path_type=Path),
    help="Load kit from path.",
)
@click.option("--no-kits", is_flag=True, default=False, help="Disable kit discovery.")
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
    kit: tuple[Path, ...],
    *,
    dashboard: bool,
    remote: bool,
    no_kits: bool,
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

    _ensure_kit_paths()
    from beddel_agent_kiro.adapter import KiroCLIAgentAdapter
    from beddel_provider_litellm.adapter import LiteLLMAdapter

    from beddel.domain.errors import BeddelError
    from beddel.domain.models import DefaultDependencies, Workflow
    from beddel.domain.parser import WorkflowParser
    from beddel.domain.registry import PrimitiveRegistry
    from beddel.integrations.fastapi import create_beddel_handler
    from beddel.primitives import register_builtins

    if allowed_users and not remote:
        click.echo("Warning: --allowed-users ignored without --remote.", err=True)

    if remote and not tunnel_domain:
        click.echo(
            "Error: --tunnel-domain is required when --remote is set.",
            err=True,
        )
        raise SystemExit(1)

    app = FastAPI(title="Beddel", version=__version__)

    # Determine CORS origins based on mode
    cors_origins = [f"https://{tunnel_domain}"] if remote else ["http://localhost:3000"]

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


# ---------------------------------------------------------------------------
# Kit management commands
# ---------------------------------------------------------------------------


@cli.group()
def kit() -> None:
    """Manage solution kits."""


@kit.command("install")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--global", "global_install", is_flag=True, help="Install to ~/.beddel/kits/")
def kit_install(path: str, *, global_install: bool) -> None:
    """Install a solution kit from a local directory."""
    import shutil
    import subprocess

    from beddel.domain.errors import KitManifestError
    from beddel.domain.kit import parse_kit_manifest

    kit_yaml = Path(path) / "kit.yaml"

    # 1. Validate manifest
    try:
        manifest = parse_kit_manifest(kit_yaml)
    except KitManifestError as exc:
        click.echo(f"Invalid kit manifest: {exc.message}", err=True)
        raise SystemExit(1) from None

    # 2. Install pip dependencies
    deps = manifest.kit.dependencies
    if deps:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", *deps],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            click.echo(f"Failed to install dependencies: {exc}", err=True)
            raise SystemExit(1) from None

    # 3. Copy kit directory to target
    kit_name = manifest.kit.name
    if global_install:
        target = Path.home() / ".beddel" / "kits" / kit_name
    else:
        target = Path("./kits") / kit_name

    try:
        shutil.copytree(path, target, dirs_exist_ok=True)
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

    rows: list[tuple[str, str, str, str]] = []
    for manifest in result.manifests:
        name = manifest.kit.name
        version = manifest.kit.version
        path = str(manifest.root_path)
        try:
            load_kit(manifest)
            status = "loaded"
        except KitDependencyError:
            status = "missing-deps"
        except (KitManifestError, Exception):
            status = "error"
        rows.append((name, version, status, path))

    headers = ("NAME", "VERSION", "STATUS", "PATH")
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
    }

    generators = {
        "skill": export_skill,
        "kit": export_kit,
        "mcp": export_mcp,
        "endpoint": export_endpoint,
    }

    result_path = generators[fmt](workflow_meta, output_dir.resolve())
    click.echo(f"Exported {fmt}: {result_path}")
