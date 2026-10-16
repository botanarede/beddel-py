"""Surface-side composition of declared MCP servers for ``beddel run`` (AD-21).

``beddel run`` is its own explicit composition root (AD-4, AD-14).  After the
workflow is parsed and before the first step runs, :func:`compose_mcp`

1. decides whether the run needs MCP at all (the workflow declares
   ``mcp_servers`` or a step names a server); if not, it does nothing and the
   MCP kit is never imported;
2. locates the one ``protocol-mcp-kit`` directory named by the surface's
   configuration (the ``--kit`` paths plus the configured ``kits_paths``, as
   ``_resolve_all_kit_paths`` returns them) and loads the kit module from
   there, refusing a module that comes from anywhere else;
3. registers the MCP client adapters by **static enumeration**, as
   per-transport constructors, taking the client adapters and the schema
   validator from that one module object;
4. runs the pure validation of :mod:`beddel.domain.mcp_composition`;
5. builds one client per **named** server with ``transport=``, ``endpoint=``
   and ``authorization=`` keywords.  Construction performs no I/O; the core
   never calls ``connect`` (the client connects on its first use).

:class:`MCPWiring` owns the clients that were built and disconnects each of
them once, with every ``disconnect`` isolated and bounded by a 5 second
timeout, when the run ends.  The bound relies on cooperative cancellation: a
``disconnect`` that swallows the cancellation and keeps running is not
interrupted.

Nothing here touches ``load_kit_adapters``, ``_build_adapter_registries`` or
kit discovery (D-5 is not decided here), edits ``sys.path``, or deletes or
reloads a module that was already imported.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from beddel.domain.errors import MCPError
from beddel.domain.mcp_composition import (
    REASON_ADAPTER_CONSTRUCTION_FAILED,
    REASON_ADAPTER_UNAVAILABLE,
    REASON_KIT_AMBIGUOUS,
    REASON_KIT_LOCATION_MISMATCH,
    REASON_KIT_UNAVAILABLE,
    REASON_KITS_DISABLED,
    composition_error,
    validate_mcp_composition,
    workflow_uses_mcp,
)
from beddel.domain.models import MCPServerDeclaration, Workflow
from beddel.domain.ports import IMCPClient
from beddel.primitives.tool import SchemaValidator

__all__ = [
    "KIT_DIR_NAME",
    "KIT_MODULE",
    "MCP_CLIENT_ADAPTERS",
    "MCPWiring",
    "compose_mcp",
    "execute_and_close",
    "load_kit_module",
    "locate_kit_source",
]

logger = logging.getLogger(__name__)

#: Directory name of the MCP protocol kit inside a kits directory.
KIT_DIR_NAME: Final = "protocol-mcp-kit"

#: Importable name of the kit's Python package (``module`` in its manifest).
KIT_MODULE: Final = "beddel_protocol_mcp"

#: AD-21 static enumeration: transport name (the adapter ``name`` the kit
#: manifest declares) -> attribute of the kit module that constructs it.  The
#: stdio and SSE adapters are deliberately absent (stdio is not declarable;
#: SSE is not brought to the construction contract).  Nothing is discovered.
MCP_CLIENT_ADAPTERS: Final[tuple[tuple[str, str], ...]] = (
    ("mcp-streamable-http", "StreamableHTTPMCPClient"),
)

#: Attribute of the kit module that validates tool arguments against a schema.
_SCHEMA_VALIDATOR_ATTRIBUTE: Final = "validate_tool_arguments"

MCPClientConstructor = Callable[..., IMCPClient]

#: Seconds one client is given to ``disconnect`` during cleanup before it is
#: abandoned (and logged) so the next client can still be closed.
_DISCONNECT_TIMEOUT: Final = 5  # seconds


class MCPWiring:
    """The MCP clients built for one run, and the validator that goes with them.

    Created empty by the surface before :func:`compose_mcp` runs, so that a
    failure half-way through construction still leaves every client that was
    built reachable for :meth:`aclose`.
    """

    def __init__(self) -> None:
        self._built: list[tuple[str, IMCPClient]] = []
        self._registry: dict[str, IMCPClient] = {}
        self._closed = False
        #: Validator taken from the same kit module as the adapters, or ``None``.
        self.schema_validator: SchemaValidator | None = None

    @property
    def registry(self) -> dict[str, IMCPClient] | None:
        """The ``mcp_registry`` for the dependencies; ``None`` when no client was built."""
        return dict(self._registry) if self._registry else None

    @property
    def has_clients(self) -> bool:
        """Whether at least one client was built and not yet closed."""
        return bool(self._built) and not self._closed

    def add(self, server: str, client: IMCPClient) -> None:
        """Record a built client under its declared server key."""
        self._built.append((server, client))
        self._registry[server] = client

    async def aclose(self) -> None:
        """Disconnect every built client exactly once, each within a time bound.

        Each ``disconnect`` is isolated and bounded by ``_DISCONNECT_TIMEOUT``
        (5 seconds): a failure or a timeout is logged (server key and
        exception class name only, never exception text) and neither masks
        the error that ended the run nor skips the remaining clients.  A
        cancellation that reaches a ``disconnect`` is re-raised only after
        the remaining clients were given their ``disconnect`` as well.

        The bound relies on cancellation: a ``disconnect`` that swallows the
        cancellation and keeps running is not interrupted.
        """
        if self._closed:
            return
        self._closed = True
        cancelled: asyncio.CancelledError | None = None
        for server, client in self._built:
            failure: str | None = None
            try:
                await asyncio.wait_for(client.disconnect(), timeout=_DISCONNECT_TIMEOUT)
            except asyncio.CancelledError as exc:
                cancelled = exc
            except Exception as exc:
                failure = type(exc).__name__
            if failure is not None:
                logger.warning(
                    "MCP client for server '%s' failed to disconnect (%s)", server, failure
                )
        if cancelled is not None:
            raise cancelled


async def execute_and_close(
    executor: Any,
    workflow: Workflow,
    inputs: dict[str, Any],
    wiring: MCPWiring,
) -> dict[str, Any]:
    """Execute the workflow and, in ``finally``, disconnect every built client.

    One coroutine owns both the run and the cleanup, so the clients are
    closed on success, on step failure and on cancellation alike.
    """
    try:
        result: dict[str, Any] = await executor.execute(workflow, inputs)
        return result
    finally:
        await wiring.aclose()


def locate_kit_source(kit_paths: Sequence[Path] | None) -> Path:
    """Find the one ``protocol-mcp-kit`` source directory the configuration names.

    Args:
        kit_paths: Kits directories as ``_resolve_all_kit_paths`` returns them
            (``--kit`` paths plus configured ``kits_paths``), or ``None``.

    Returns:
        The resolved source directory of the kit (``python/``, else ``src/``).

    Raises:
        ExecutionError: ``kit_unavailable`` when no location is found, a
            directory cannot be read or the kit has no source directory;
            ``kit_location_ambiguous`` when more than one distinct location
            is found.
    """
    from beddel.setup import _resolve_kit_src_dir

    candidates: dict[Path, Path] = {}
    for base in kit_paths or ():
        scan_error: str | None = None
        try:
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                if child.name == KIT_DIR_NAME and child.is_dir():
                    candidates.setdefault(child.resolve(), child)
        except OSError as exc:
            scan_error = type(exc).__name__
        if scan_error is not None:
            raise composition_error(REASON_KIT_UNAVAILABLE, extra={"error_type": scan_error})
    if not candidates:
        raise composition_error(REASON_KIT_UNAVAILABLE)
    if len(candidates) > 1:
        raise composition_error(REASON_KIT_AMBIGUOUS)
    (kit_dir,) = candidates
    source_dir = _resolve_kit_src_dir(kit_dir)
    if source_dir is None:
        raise composition_error(REASON_KIT_UNAVAILABLE)
    return source_dir.resolve()


def _origin_is_under(module: ModuleType, source_dir: Path) -> bool:
    """Whether the module's resolved ``__file__`` lies under ``source_dir``."""
    origin = getattr(module, "__file__", None)
    if not isinstance(origin, str):
        return False
    try:
        return Path(origin).resolve().is_relative_to(source_dir)
    except (OSError, RuntimeError, ValueError):
        return False


def load_kit_module(source_dir: Path) -> ModuleType:
    """Return the kit module, loaded from ``source_dir`` and nowhere else.

    A module already present in ``sys.modules`` (Beddel's own adapter loader
    normally imports the kit before the composition runs) is accepted only
    when its resolved ``__file__`` is under ``source_dir``; it is never
    deleted, reloaded or replaced.  Otherwise the package is loaded from the
    chosen directory explicitly, without consulting or editing ``sys.path``.

    Raises:
        ExecutionError: ``kit_location_mismatch`` for a module from another
            location; ``kit_unavailable`` when the package is missing or its
            import fails (the exception class name is the only detail).
    """
    preloaded = sys.modules.get(KIT_MODULE)
    if preloaded is not None:
        if not _origin_is_under(preloaded, source_dir):
            raise composition_error(REASON_KIT_LOCATION_MISMATCH)
        return preloaded

    package_init = source_dir / KIT_MODULE / "__init__.py"
    if not package_init.is_file():
        raise composition_error(REASON_KIT_UNAVAILABLE)
    spec = importlib.util.spec_from_file_location(
        KIT_MODULE,
        package_init,
        submodule_search_locations=[str(package_init.parent)],
    )
    if spec is None or spec.loader is None:
        raise composition_error(REASON_KIT_UNAVAILABLE)
    module = importlib.util.module_from_spec(spec)
    # The kit's own absolute imports (``import beddel_protocol_mcp.x``) need the
    # package registered while it executes, exactly as a normal import does.
    sys.modules[KIT_MODULE] = module
    import_error: str | None = None
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        import_error = type(exc).__name__
    if import_error is not None:
        # Remove only the half-initialized entry this function inserted.
        if sys.modules.get(KIT_MODULE) is module:
            del sys.modules[KIT_MODULE]
        raise composition_error(REASON_KIT_UNAVAILABLE, extra={"error_type": import_error})
    if not _origin_is_under(module, source_dir):
        raise composition_error(REASON_KIT_LOCATION_MISMATCH)
    return module


def _registered_constructors(module: ModuleType) -> dict[str, MCPClientConstructor]:
    """Static enumeration of the MCP client adapters (AD-21), keyed by transport name."""
    constructors: dict[str, MCPClientConstructor] = {}
    for transport, attribute in MCP_CLIENT_ADAPTERS:
        constructor = getattr(module, attribute, None)
        if callable(constructor):
            constructors[transport] = constructor
    return constructors


def _build_client(
    constructor: MCPClientConstructor,
    server: str,
    declaration: MCPServerDeclaration,
) -> IMCPClient:
    """Construct one client from the declaration's fields, by keyword, with no I/O.

    An ``MCPError`` from the kit constructor propagates unchanged.  Any other
    exception becomes a composition error that carries only its class name,
    raised after leaving the ``except`` block so neither ``__cause__`` nor
    ``__context__`` points at the original exception.
    """
    error_type: str | None = None
    try:
        return constructor(
            transport=declaration.transport,
            endpoint=declaration.endpoint,
            authorization=declaration.authorization,
        )
    except MCPError:
        raise
    except Exception as exc:
        error_type = type(exc).__name__
    raise composition_error(
        REASON_ADAPTER_CONSTRUCTION_FAILED,
        field="transport",
        server=server,
        extra={"error_type": error_type},
    )


def compose_mcp(
    workflow: Workflow,
    wiring: MCPWiring,
    *,
    kit_paths: Sequence[Path] | None,
    no_kits: bool,
    tool_names: Collection[str],
    kit_names: Collection[str],
) -> None:
    """Compose the declared MCP servers of ``workflow`` into ``wiring``.

    Does nothing (and imports no kit) when the workflow neither declares
    ``mcp_servers`` nor has a step that names a server.

    Args:
        workflow: The parsed workflow.
        wiring: Empty wiring to fill; clients are added as they are built.
        kit_paths: Kits directories from ``_resolve_all_kit_paths``.
        no_kits: ``--no-kits`` was given; the kit is not imported and any MCP
            use is a composition error.
        tool_names: Names in the merged tool registry of the run.
        kit_names: Names of the kits the surface registers tools from.

    Raises:
        ExecutionError: ``EXEC_COMPOSITION_FAILED`` with a stable
            ``details["reason"]`` for every composition failure.
        MCPError: unchanged, when a kit constructor raises one.
    """
    if not workflow_uses_mcp(workflow):
        return
    if no_kits:
        raise composition_error(REASON_KITS_DISABLED)

    module = load_kit_module(locate_kit_source(kit_paths))
    constructors = _registered_constructors(module)

    declarations = workflow.mcp_servers or {}
    enumerated = {transport for transport, _ in MCP_CLIENT_ADAPTERS}
    for server, declaration in declarations.items():
        if declaration.transport in enumerated and declaration.transport not in constructors:
            raise composition_error(REASON_ADAPTER_UNAVAILABLE, field="transport", server=server)

    named = validate_mcp_composition(
        workflow,
        transports=constructors.keys(),
        tool_names=tool_names,
        kit_names=kit_names,
    )

    validator = getattr(module, _SCHEMA_VALIDATOR_ATTRIBUTE, None)
    wiring.schema_validator = validator if callable(validator) else None

    for server in named:
        declaration = declarations[server]
        wiring.add(server, _build_client(constructors[declaration.transport], server, declaration))
