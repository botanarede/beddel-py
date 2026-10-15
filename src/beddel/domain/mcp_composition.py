"""Pure composition validation for declared MCP servers (AD-21, AR-3, AR-6).

The execution surface calls :func:`validate_mcp_composition` after the
workflow is parsed and before the first step runs.  The function performs no
I/O, imports no kit and builds no client: it only decides whether the
declarations, the steps that name servers, the allowlist and the registered
transports are consistent, and it returns the ordered keys of the servers a
step actually names (the only servers the surface may wire).

Only stdlib, pydantic and domain imports are allowed in this module (domain
core rule).

Check order (fixed, so ``details["reason"]`` is deterministic):

1. ``missing_allowlist`` -- the workflow declares ``mcp_servers`` (even an
   empty map) and has no ``allowed_tools``.
2. For every step in document order (a step, then its ``then`` steps, its
   ``else`` steps and its ``fallback_step``, depth first, any depth), only
   for a ``tool`` step whose config has the key ``mcp_server``:
   ``invalid_name`` (``mcp_server`` or ``tool`` is not a non-empty string
   free of ``$``), ``undeclared_server``, ``unknown_transport`` (the
   declaration the step names), ``tool_not_allowed`` (exact qualified
   ``<mcp_server>:<tool>`` match against ``allowed_tools``).
3. ``unknown_transport`` for every declaration, in declaration order (this
   covers declarations that no step names).
4. ``name_collision`` for every declared key, in declaration order.

A composition error is one :class:`~beddel.domain.errors.ExecutionError`
with code ``EXEC_COMPOSITION_FAILED``, a fixed message and
``details["reason"]``.  Its details may hold the step id, the field name and
a *declared* server key (shape-validated by the workflow model); they never
hold the value of ``mcp_server``, ``tool``, ``endpoint`` or ``arguments``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from typing import Any, Final

from beddel.domain.errors import ExecutionError
from beddel.domain.models import Step, Workflow
from beddel.error_codes import EXEC_COMPOSITION_FAILED

__all__ = [
    "COMPOSITION_FAILED_MESSAGE",
    "REASON_ADAPTER_CONSTRUCTION_FAILED",
    "REASON_ADAPTER_UNAVAILABLE",
    "REASON_INVALID_NAME",
    "REASON_KITS_DISABLED",
    "REASON_KIT_AMBIGUOUS",
    "REASON_KIT_LOCATION_MISMATCH",
    "REASON_KIT_UNAVAILABLE",
    "REASON_MISSING_ALLOWLIST",
    "REASON_NAME_COLLISION",
    "REASON_TOOL_NOT_ALLOWED",
    "REASON_UNDECLARED_SERVER",
    "REASON_UNKNOWN_TRANSPORT",
    "composition_error",
    "validate_mcp_composition",
    "workflow_uses_mcp",
]

#: Fixed message of every composition error.  It never varies with the input.
COMPOSITION_FAILED_MESSAGE: Final = "MCP server composition failed before execution"

# Reasons produced by the pure validation in this module.
REASON_MISSING_ALLOWLIST: Final = "missing_allowlist"
REASON_INVALID_NAME: Final = "invalid_name"
REASON_UNDECLARED_SERVER: Final = "undeclared_server"
REASON_UNKNOWN_TRANSPORT: Final = "unknown_transport"
REASON_TOOL_NOT_ALLOWED: Final = "tool_not_allowed"
REASON_NAME_COLLISION: Final = "name_collision"

# Reasons produced by the execution surface when it wires the kit and the
# clients.  They live here so the whole vocabulary has one home.
REASON_KITS_DISABLED: Final = "kits_disabled"
REASON_KIT_UNAVAILABLE: Final = "kit_unavailable"
REASON_KIT_AMBIGUOUS: Final = "kit_location_ambiguous"
REASON_KIT_LOCATION_MISMATCH: Final = "kit_location_mismatch"
REASON_ADAPTER_UNAVAILABLE: Final = "adapter_unavailable"
REASON_ADAPTER_CONSTRUCTION_FAILED: Final = "adapter_construction_failed"

_STEP_PRIMITIVE_TOOL: Final = "tool"
_KEY_MCP_SERVER: Final = "mcp_server"
_KEY_TOOL: Final = "tool"


def composition_error(
    reason: str,
    *,
    field: str | None = None,
    step_id: str | None = None,
    server: str | None = None,
    extra: dict[str, Any] | None = None,
) -> ExecutionError:
    """Build the one composition error.

    Args:
        reason: Stable machine-readable cause.
        field: Name of the offending field (never its value).
        step_id: Id of the offending step.
        server: A *declared* server key.  Never pass a value taken from a
            step config: only keys of ``workflow.mcp_servers`` are safe.
        extra: Further fixed, value-free details (for example an exception
            class name).

    Returns:
        An :class:`ExecutionError` with the registered composition code and
        the fixed message.  The caller raises it.
    """
    details: dict[str, Any] = {"reason": reason}
    if field is not None:
        details["field"] = field
    if step_id is not None:
        details["step_id"] = step_id
    if server is not None:
        details["server"] = server
    if extra:
        details.update(extra)
    return ExecutionError(EXEC_COMPOSITION_FAILED, COMPOSITION_FAILED_MESSAGE, details)


def _iter_steps(steps: Iterable[Step]) -> Iterator[Step]:
    """Yield every step in document order, at any depth, without recursion.

    Walks ``then_steps``, ``else_steps`` and
    ``execution_strategy.fallback_step`` with an explicit stack, so the depth
    of the graph is not bounded by the interpreter recursion limit.  A step
    object reachable twice is yielded once.
    """
    stack: list[Step] = list(steps)
    stack.reverse()
    seen: set[int] = set()
    while stack:
        step = stack.pop()
        if id(step) in seen:
            continue
        seen.add(id(step))
        yield step
        children: list[Step] = []
        if step.then_steps:
            children.extend(step.then_steps)
        if step.else_steps:
            children.extend(step.else_steps)
        fallback = step.execution_strategy.fallback_step
        if fallback is not None:
            children.append(fallback)
        children.reverse()
        stack.extend(children)


def _names_mcp_server(step: Step) -> bool:
    """Whether ``step`` names an MCP server (presence of the key, whatever the value)."""
    return step.primitive == _STEP_PRIMITIVE_TOOL and _KEY_MCP_SERVER in step.config


def _is_literal_name(value: object) -> bool:
    """A literal name is a non-empty string without ``$`` (no variable reference)."""
    return isinstance(value, str) and value != "" and "$" not in value


def workflow_uses_mcp(workflow: Workflow) -> bool:
    """Whether the run needs MCP wiring at all.

    True when the workflow declares ``mcp_servers`` (even an empty map) or any
    step, at any depth, names an MCP server.  The surface imports the MCP kit
    only when this is true.
    """
    if workflow.mcp_servers is not None:
        return True
    return any(_names_mcp_server(step) for step in _iter_steps(workflow.steps))


def validate_mcp_composition(
    workflow: Workflow,
    *,
    transports: Collection[str],
    tool_names: Collection[str],
    kit_names: Collection[str],
) -> tuple[str, ...]:
    """Validate the MCP part of a parsed workflow before execution.

    Args:
        workflow: The parsed workflow.
        transports: Transport names the composition root registered a client
            adapter for (the only admissible ``transport`` values).
        tool_names: Names in the merged tool registry of the surface
            (kit tools, ``--tool`` tools and inline tools).  Inline tools
            declared by the workflow itself are also read from it.
        kit_names: Names of the kits whose tools the surface registers.

    Returns:
        The keys of the declared servers that at least one step names, in
        declaration order.  A declared server no step names is validated but
        not returned: it is not wired.

    Raises:
        ExecutionError: ``EXEC_COMPOSITION_FAILED`` with a stable
            ``details["reason"]`` (see the module docstring for the order).
    """
    declarations = workflow.mcp_servers
    allowed = workflow.allowed_tools

    if declarations is not None and allowed is None:
        raise composition_error(REASON_MISSING_ALLOWLIST, field="allowed_tools")

    named: set[str] = set()
    for step in _iter_steps(workflow.steps):
        if not _names_mcp_server(step):
            continue
        server = step.config[_KEY_MCP_SERVER]
        if not _is_literal_name(server):
            raise composition_error(REASON_INVALID_NAME, field=_KEY_MCP_SERVER, step_id=step.id)
        tool = step.config.get(_KEY_TOOL)
        if not _is_literal_name(tool):
            raise composition_error(REASON_INVALID_NAME, field=_KEY_TOOL, step_id=step.id)
        if declarations is None or server not in declarations:
            # The step value is NOT echoed: it is not a declared (validated) key.
            raise composition_error(
                REASON_UNDECLARED_SERVER, field=_KEY_MCP_SERVER, step_id=step.id
            )
        if declarations[server].transport not in transports:
            raise composition_error(
                REASON_UNKNOWN_TRANSPORT, field="transport", step_id=step.id, server=server
            )
        # Exact match of the qualified name; no bare name, wildcard, case
        # folding or suffix rule (unlike the local tool path).
        if allowed is None or f"{server}:{tool}" not in allowed:
            raise composition_error(
                REASON_TOOL_NOT_ALLOWED, field=_KEY_TOOL, step_id=step.id, server=server
            )
        named.add(server)

    if declarations is None:
        return ()

    for key, declaration in declarations.items():
        if declaration.transport not in transports:
            raise composition_error(REASON_UNKNOWN_TRANSPORT, field="transport", server=key)

    # Only a name that contains ``:`` has a part before the first ``:``.
    reserved = set(kit_names)
    for name in (*tool_names, *(tool.name for tool in workflow.tools or ())):
        if ":" in name:
            reserved.add(name.split(":", 1)[0])
    for key in declarations:
        if key in reserved:
            raise composition_error(REASON_NAME_COLLISION, field="mcp_servers", server=key)

    return tuple(key for key in declarations if key in named)
