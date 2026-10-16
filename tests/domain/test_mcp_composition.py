"""Tests for the pure MCP composition validation (Story 1.2b, Task 3).

Covers AC 1, 2, 3, 4, 8, 10 and 12.  The validation performs no I/O, so these
tests build ``Workflow`` and ``Step`` objects directly.  The fake client of
``tests/_mcp_fakes.py`` follows the kit construction contract; no network, no
SDK, no kit and no credential are used.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from _mcp_fakes import (
    FAKE_SECRET_MARKER,
    EventLog,
    FakeMCPClient,
    assert_marker_absent,
    assert_unchained,
    exception_texts,
)

from beddel.domain import mcp_composition
from beddel.domain.errors import BeddelError, ExecutionError
from beddel.domain.mcp_composition import (
    COMPOSITION_FAILED_MESSAGE,
    REASON_INVALID_NAME,
    REASON_MISSING_ALLOWLIST,
    REASON_NAME_COLLISION,
    REASON_TOOL_NOT_ALLOWED,
    REASON_UNDECLARED_SERVER,
    REASON_UNKNOWN_TRANSPORT,
    validate_mcp_composition,
    workflow_uses_mcp,
)
from beddel.domain.models import (
    DefaultDependencies,
    ExecutionContext,
    ExecutionStrategy,
    Step,
    StrategyType,
    Workflow,
)
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry
from beddel.error_codes import EXEC_COMPOSITION_FAILED
from beddel.primitives import register_builtins
from beddel.primitives.call_agent import CallAgentPrimitive

TRANSPORT = "mcp-streamable-http"
SERVER = "acme_srv"
OTHER = "other_srv"
TOOL = "echo"
QUALIFIED = f"{SERVER}:{TOOL}"
ENDPOINT = "https://fake.example/mcp"


def _decl(transport: str = TRANSPORT, endpoint: str = ENDPOINT) -> dict[str, str]:
    return {"transport": transport, "endpoint": endpoint, "authorization": "none"}


def _mcp(step_id: str = "m1", server: Any = SERVER, tool: Any = TOOL, **kwargs: Any) -> Step:
    return Step(
        id=step_id,
        primitive="tool",
        config={"mcp_server": server, "tool": tool},
        **kwargs,
    )


def _plain(step_id: str, **kwargs: Any) -> Step:
    return Step(id=step_id, primitive="noop", config={}, **kwargs)


def _wf(
    steps: list[Step],
    *,
    servers: dict[str, Any] | None,
    allowed: list[str] | None,
    tools: list[dict[str, str]] | None = None,
) -> Workflow:
    return Workflow(
        id="wf",
        name="wf",
        steps=steps,
        mcp_servers=servers,
        allowed_tools=allowed,
        tools=tools,  # type: ignore[arg-type]
    )


def _validate(
    workflow: Workflow,
    *,
    transports: tuple[str, ...] = (TRANSPORT,),
    tool_names: tuple[str, ...] = (),
    kit_names: tuple[str, ...] = (),
) -> tuple[str, ...]:
    return validate_mcp_composition(
        workflow, transports=transports, tool_names=tool_names, kit_names=kit_names
    )


def _reason(workflow: Workflow, **kwargs: Any) -> ExecutionError:
    with pytest.raises(ExecutionError) as exc_info:
        _validate(workflow, **kwargs)
    err = exc_info.value
    assert err.code == EXEC_COMPOSITION_FAILED == "BEDDEL-EXEC-050"
    assert err.message == COMPOSITION_FAILED_MESSAGE
    assert_unchained(err)
    return err


def _simple(steps: list[Step] | None = None, **kwargs: Any) -> Workflow:
    return _wf(
        steps if steps is not None else [_mcp()],
        servers=kwargs.pop("servers", {SERVER: _decl()}),
        allowed=kwargs.pop("allowed", [QUALIFIED]),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# AC 1: undeclared, named and unnamed servers
# ---------------------------------------------------------------------------


class TestServersNamedByTheWorkflow:
    def test_undeclared_server_is_a_composition_error(self) -> None:
        wf = _wf([_mcp(server="ghost_srv")], servers={SERVER: _decl()}, allowed=[QUALIFIED])

        err = _reason(wf)

        assert err.details["reason"] == REASON_UNDECLARED_SERVER
        assert err.details["field"] == "mcp_server"
        assert err.details["step_id"] == "m1"
        assert "ghost_srv" not in repr(err.details)

    def test_step_naming_a_server_when_none_is_declared_is_undeclared(self) -> None:
        wf = _wf([_mcp()], servers=None, allowed=[QUALIFIED])

        assert _reason(wf).details["reason"] == REASON_UNDECLARED_SERVER

    def test_named_and_declared_server_is_returned_once(self) -> None:
        wf = _simple([_mcp("a"), _mcp("b")])

        assert _validate(wf) == (SERVER,)

    def test_declared_but_unnamed_server_is_not_returned(self) -> None:
        wf = _wf(
            [_mcp()],
            servers={SERVER: _decl(), OTHER: _decl(endpoint="https://other.example/mcp")},
            allowed=[QUALIFIED],
        )

        assert _validate(wf) == (SERVER,)

    def test_result_follows_declaration_order(self) -> None:
        wf = _wf(
            [_mcp("a", server=OTHER), _mcp("b", server=SERVER)],
            servers={SERVER: _decl(), OTHER: _decl()},
            allowed=[QUALIFIED, f"{OTHER}:{TOOL}"],
        )

        assert _validate(wf) == (SERVER, OTHER)

    def test_nothing_named_and_nothing_declared_returns_empty(self) -> None:
        wf = _wf([_plain("p")], servers=None, allowed=None)

        assert _validate(wf) == ()

    def test_declared_unnamed_server_is_still_validated(self) -> None:
        wf = _wf([_plain("p")], servers={SERVER: _decl()}, allowed=[])

        assert _validate(wf) == ()

    def test_workflow_uses_mcp(self) -> None:
        assert not workflow_uses_mcp(_wf([_plain("p")], servers=None, allowed=None))
        assert workflow_uses_mcp(_wf([_plain("p")], servers={}, allowed=[]))
        assert workflow_uses_mcp(_wf([_mcp()], servers=None, allowed=None))
        nested = _plain("p", then_steps=[_mcp()])
        assert workflow_uses_mcp(_wf([nested], servers=None, allowed=None))
        local = Step(id="l", primitive="tool", config={"tool": "x"})
        assert not workflow_uses_mcp(_wf([local], servers=None, allowed=None))


# ---------------------------------------------------------------------------
# AC 2: nested steps, dynamic names, key presence
# ---------------------------------------------------------------------------


def _bad(step_id: str = "bad") -> Step:
    """An MCP step that names an undeclared server (fails the composition)."""
    return _mcp(step_id, server="ghost_srv")


def _fallback(inner: Step, step_id: str = "fb-owner") -> Step:
    return _plain(
        step_id,
        execution_strategy=ExecutionStrategy(type=StrategyType.FALLBACK, fallback_step=inner),
    )


class TestNestedStepsAreWalked:
    @pytest.mark.parametrize(
        "builder",
        [
            lambda inner: _plain("o", then_steps=[inner]),
            lambda inner: _plain("o", else_steps=[inner]),
            lambda inner: _fallback(inner, "o"),
        ],
        ids=["then", "else", "fallback_step"],
    )
    def test_each_nesting_construct_is_checked(self, builder: Callable[[Step], Step]) -> None:
        wf = _simple([builder(_bad())])

        err = _reason(wf)

        assert err.details["reason"] == REASON_UNDECLARED_SERVER
        assert err.details["step_id"] == "bad"

    def test_mix_at_depth_three_or_more(self) -> None:
        deep = _plain(
            "l1",
            then_steps=[
                _plain(
                    "l2",
                    else_steps=[_fallback(_plain("l4", then_steps=[_bad("deepest")]), "l3")],
                )
            ],
        )

        err = _reason(_simple([deep]))

        assert err.details["step_id"] == "deepest"

    def test_fallback_step_inside_a_then_branch(self) -> None:
        wf = _simple([_plain("o", then_steps=[_fallback(_bad("fb"))])])

        assert _reason(wf).details["step_id"] == "fb"

    def test_valid_nested_mcp_step_is_accepted_and_named(self) -> None:
        wf = _wf(
            [_plain("o", else_steps=[_fallback(_mcp("inner"))])],
            servers={SERVER: _decl(), OTHER: _decl()},
            allowed=[QUALIFIED],
        )

        assert _validate(wf) == (SERVER,)

    def test_depth_fifty(self) -> None:
        step = _bad("leaf")
        for i in range(50):
            step = _plain(f"n{i}", then_steps=[step])

        assert _reason(_simple([step])).details["step_id"] == "leaf"

    def test_depth_beyond_the_recursion_limit(self) -> None:
        # Built with model_construct: pydantic validation itself would recurse.
        step = _bad("leaf")
        for i in range(3000):
            step = Step.model_construct(id=f"n{i}", primitive="noop", config={}, then_steps=[step])

        wf = Workflow.model_construct(
            id="wf",
            name="wf",
            steps=[step],
            mcp_servers=None,
            allowed_tools=None,
            tools=None,
        )

        assert _reason(wf).details["step_id"] == "leaf"
        assert workflow_uses_mcp(wf)

    def test_a_step_graph_with_a_cycle_terminates(self) -> None:
        loop = _plain("loop")
        loop.then_steps = [loop]
        wf = _simple([loop, _mcp()])

        assert _validate(wf) == (SERVER,)

    def test_first_failing_step_in_document_order_wins(self) -> None:
        first = _plain("first", then_steps=[_bad("nested-first")])
        second = _bad("second")

        assert _reason(_simple([first, second])).details["step_id"] == "nested-first"


class TestNamesAreLiteral:
    @pytest.mark.parametrize(
        "value",
        ["$input.x", "$env.X", "a-$input.x", f"$input.{FAKE_SECRET_MARKER}", "$"],
        ids=["input", "env", "embedded", "marker", "bare-dollar"],
    )
    def test_variable_reference_in_mcp_server_is_rejected(self, value: str) -> None:
        err = _reason(_simple([_mcp(server=value)]))

        assert err.details["reason"] == REASON_INVALID_NAME
        assert err.details["field"] == "mcp_server"
        assert err.details["step_id"] == "m1"
        assert value not in repr(err.details)

    @pytest.mark.parametrize(
        "value",
        ["$input.x", "$env.X", "a-$input.x", f"$input.{FAKE_SECRET_MARKER}"],
        ids=["input", "env", "embedded", "marker"],
    )
    def test_variable_reference_in_tool_is_rejected(self, value: str) -> None:
        err = _reason(_simple([_mcp(tool=value)]))

        assert err.details["reason"] == REASON_INVALID_NAME
        assert err.details["field"] == "tool"
        assert value not in repr(err.details)

    @pytest.mark.parametrize("value", [None, 7, False, True, ["x"], {"a": 1}, ""])
    def test_non_string_or_empty_mcp_server_is_rejected_by_key_presence(self, value: Any) -> None:
        # ``false`` and "" are falsy: the run-time router would treat them as
        # local steps, so the composition must refuse them as invalid names.
        err = _reason(_simple([_mcp(server=value)]))

        assert err.details["reason"] == REASON_INVALID_NAME
        assert err.details["field"] == "mcp_server"

    @pytest.mark.parametrize("value", [None, 7, False, ["x"], ""])
    def test_non_string_or_empty_tool_is_rejected(self, value: Any) -> None:
        err = _reason(_simple([_mcp(tool=value)]))

        assert err.details["reason"] == REASON_INVALID_NAME
        assert err.details["field"] == "tool"

    def test_missing_tool_is_rejected(self) -> None:
        step = Step(id="m1", primitive="tool", config={"mcp_server": SERVER})

        err = _reason(_simple([step]))

        assert err.details["reason"] == REASON_INVALID_NAME
        assert err.details["field"] == "tool"

    def test_mcp_server_is_checked_before_tool(self) -> None:
        err = _reason(_simple([_mcp(server="$x", tool="$y")]))

        assert err.details["field"] == "mcp_server"

    def test_non_tool_primitive_carrying_mcp_server_is_ignored(self) -> None:
        step = Step(
            id="x",
            primitive="llm",
            config={"mcp_server": "$input.x", "tool": 3},
        )
        wf = _wf([step], servers=None, allowed=None)

        assert _validate(wf) == ()
        assert not workflow_uses_mcp(wf)

    def test_local_tool_step_without_mcp_server_is_ignored(self) -> None:
        step = Step(id="l", primitive="tool", config={"tool": "$input.x"})

        assert _validate(_wf([step], servers=None, allowed=None)) == ()


# ---------------------------------------------------------------------------
# AC 3: nested workflows never inherit MCP wiring
# ---------------------------------------------------------------------------


class _Recorder(IPrimitive):
    def __init__(self) -> None:
        self.contexts: list[ExecutionContext] = []

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        self.contexts.append(context)
        return "seen"


def _registry_with(recorder: _Recorder) -> PrimitiveRegistry:
    registry = PrimitiveRegistry()
    register_builtins(registry)
    registry.register("probe", recorder)
    return registry


def _child(steps: list[Step]) -> Workflow:
    return Workflow(id="child-wf", name="child", steps=steps)


def _kit_manifest() -> Any:
    declaration = MagicMock()
    declaration.name = "create-epic"
    declaration.path = "workflows/create-epic.yaml"
    kit = MagicMock()
    kit.name = "software-development-kit"
    kit.version = "0.2.0"
    kit.workflows = [declaration]
    manifest = MagicMock()
    manifest.kit = kit
    manifest.root_path = Path("/kits/sdk")
    return manifest


_SKILL_CONFIG = {
    "skill": {"kit": "software-development-kit", "workflow": "create-epic", "version": ">=0.1.0"}
}


def _parent_context(
    child: Workflow, registry: PrimitiveRegistry, client: FakeMCPClient
) -> ExecutionContext:
    ctx = ExecutionContext(
        workflow_id="parent",
        inputs={},
        current_step_id="step-1",
        metadata={"_workflow_allowed_tools": [QUALIFIED]},
    )
    ctx.deps = DefaultDependencies(
        workflow_loader=lambda _wf_id: child,
        registry=registry,
        tool_registry={},
        mcp_registry={SERVER: client},
        kit_manifests=[_kit_manifest()],
    )
    return ctx


@pytest.fixture(params=["workflow", "skill"])
def call_config(request: pytest.FixtureRequest) -> dict[str, Any]:
    if request.param == "workflow":
        return {"workflow": "child-wf"}
    return dict(_SKILL_CONFIG)


class TestNestedWorkflowsFailClosed:
    async def test_child_dependencies_have_no_mcp_registry_and_no_allowlist(
        self, call_config: dict[str, Any]
    ) -> None:
        recorder = _Recorder()
        client = FakeMCPClient(TRANSPORT, ENDPOINT, "none", log=EventLog())
        child = _child([Step(id="probe-step", primitive="probe", config={})])
        ctx = _parent_context(child, _registry_with(recorder), client)
        assert ctx.deps.mcp_registry == {SERVER: client}

        await CallAgentPrimitive().execute(call_config, ctx)

        assert len(recorder.contexts) == 1
        child_ctx = recorder.contexts[0]
        assert child_ctx.deps.mcp_registry is None
        assert "_workflow_allowed_tools" not in child_ctx.metadata
        assert "mcp_servers" not in child_ctx.metadata

    async def test_nested_mcp_step_fails_closed_and_touches_no_client(
        self, call_config: dict[str, Any]
    ) -> None:
        recorder = _Recorder()
        log = EventLog()
        client = FakeMCPClient(TRANSPORT, ENDPOINT, "none", log=log)
        child = _child([_mcp("nested-mcp")])
        ctx = _parent_context(child, _registry_with(recorder), client)

        with pytest.raises(BeddelError) as exc_info:
            await CallAgentPrimitive().execute(call_config, ctx)

        text = "\n".join(exception_texts(exc_info.value))
        assert "BEDDEL-PRIM-005" in text or "BEDDEL-PRIM-304" in text
        assert log.names() == ["constructed"]  # never connected, listed or called

    async def test_parent_allowlist_does_not_admit_the_nested_step(
        self, call_config: dict[str, Any]
    ) -> None:
        # Even with a registry handed over by hand the child has no allowlist:
        # the run-time MCP check refuses (PRIM-304) instead of running.
        recorder = _Recorder()
        log = EventLog()
        client = FakeMCPClient(TRANSPORT, ENDPOINT, "none", log=log)
        child = _child([_mcp("nested-mcp")])
        ctx = _parent_context(child, _registry_with(recorder), client)

        with pytest.raises(BeddelError):
            await CallAgentPrimitive().execute(call_config, ctx)

        assert "call_tool" not in log.names()
        assert "list_tools" not in log.names()

    def test_composition_walks_the_call_agent_step_but_not_the_child_workflow(self) -> None:
        # The child is loaded at run time; the composition cannot see it and
        # must not pretend to: the parent composes cleanly, the child fails closed.
        call = Step(id="call", primitive="call-agent", config={"workflow": "child-wf"})

        assert _validate(_wf([call], servers=None, allowed=None)) == ()
        assert not workflow_uses_mcp(_wf([call], servers=None, allowed=None))


# ---------------------------------------------------------------------------
# AC 4: transports
# ---------------------------------------------------------------------------


class TestTransports:
    def test_unknown_transport_on_a_named_declaration(self) -> None:
        wf = _simple(servers={SERVER: _decl(transport="mcp-carrier-pigeon")})

        err = _reason(wf)

        assert err.details["reason"] == REASON_UNKNOWN_TRANSPORT
        assert err.details["field"] == "transport"
        assert err.details["server"] == SERVER
        assert err.details["step_id"] == "m1"

    def test_unknown_transport_on_an_unnamed_declaration(self) -> None:
        wf = _wf(
            [_mcp()],
            servers={SERVER: _decl(), OTHER: _decl(transport="mcp-carrier-pigeon")},
            allowed=[QUALIFIED],
        )

        err = _reason(wf)

        assert err.details["reason"] == REASON_UNKNOWN_TRANSPORT
        assert err.details["server"] == OTHER
        assert "step_id" not in err.details

    @pytest.mark.parametrize("transport", ["mcp-stdio", "mcp-sse", "stdio", "sse"])
    def test_kit_supplied_names_the_root_does_not_register_are_rejected(
        self, transport: str
    ) -> None:
        wf = _simple(servers={SERVER: _decl(transport=transport)})

        assert _reason(wf).details["reason"] == REASON_UNKNOWN_TRANSPORT

    def test_no_registered_transport_rejects_every_declaration(self) -> None:
        err = _reason(_simple(), transports=())

        assert err.details["reason"] == REASON_UNKNOWN_TRANSPORT

    def test_only_the_registered_names_are_admissible(self) -> None:
        wf = _wf(
            [_mcp(), _mcp("b", server=OTHER)],
            servers={SERVER: _decl(), OTHER: _decl(transport="second-transport")},
            allowed=[QUALIFIED, f"{OTHER}:{TOOL}"],
        )

        assert _validate(wf, transports=(TRANSPORT, "second-transport")) == (SERVER, OTHER)


# ---------------------------------------------------------------------------
# AC 8: allowlist at composition, exact and qualified
# ---------------------------------------------------------------------------


class TestAllowlist:
    def test_excluded_tool_is_rejected(self) -> None:
        err = _reason(_simple(allowed=[f"{SERVER}:other_tool"]))

        assert err.details["reason"] == REASON_TOOL_NOT_ALLOWED
        assert err.details["field"] == "tool"
        assert err.details["server"] == SERVER
        assert err.details["step_id"] == "m1"

    def test_exact_qualified_name_is_admitted(self) -> None:
        assert _validate(_simple(allowed=[QUALIFIED])) == (SERVER,)

    @pytest.mark.parametrize(
        "allowed",
        [
            [TOOL],  # bare name never admits an MCP tool (suffix rule not reused)
            [f"{SERVER}:*"],  # no wildcard
            ["*"],
            [f"{SERVER}:{TOOL.upper()}"],  # no case folding
            [QUALIFIED.upper()],
            [f" {QUALIFIED}"],  # no trimming
            [f"{OTHER}:{TOOL}"],  # another server's tool
            [SERVER],  # server alone
            [],
        ],
        ids=[
            "bare",
            "server-wildcard",
            "star",
            "tool-case",
            "qualified-case",
            "leading-space",
            "other-server",
            "server-only",
            "empty",
        ],
    )
    def test_nothing_but_the_exact_qualified_name_admits(self, allowed: list[str]) -> None:
        err = _reason(_simple(allowed=allowed))

        assert err.details["reason"] == REASON_TOOL_NOT_ALLOWED

    def test_step_tool_case_variant_does_not_match_a_lower_case_entry(self) -> None:
        err = _reason(_simple([_mcp(tool="Echo")]))

        assert err.details["reason"] == REASON_TOOL_NOT_ALLOWED

    def test_tool_name_containing_a_colon_is_matched_whole(self) -> None:
        step = _mcp(tool="a:b")

        assert _validate(_simple([step], allowed=[f"{SERVER}:a:b"])) == (SERVER,)
        assert _reason(_simple([step], allowed=["a:b"])).details["reason"] == (
            REASON_TOOL_NOT_ALLOWED
        )
        assert _reason(_simple([step], allowed=[f"{SERVER}:a"])).details["reason"] == (
            REASON_TOOL_NOT_ALLOWED
        )
        assert _reason(_simple([step], allowed=[f"{SERVER}:b"])).details["reason"] == (
            REASON_TOOL_NOT_ALLOWED
        )

    def test_nested_step_is_subject_to_the_allowlist(self) -> None:
        wf = _simple([_plain("o", then_steps=[_mcp("inner", tool="forbidden")])])

        err = _reason(wf)

        assert err.details["reason"] == REASON_TOOL_NOT_ALLOWED
        assert err.details["step_id"] == "inner"

    def test_unknown_transport_is_reported_before_the_allowlist(self) -> None:
        wf = _simple(servers={SERVER: _decl(transport="nope")}, allowed=[])

        assert _reason(wf).details["reason"] == REASON_UNKNOWN_TRANSPORT


class TestServerKeyCollisions:
    def test_server_key_equal_to_a_kit_name(self) -> None:
        err = _reason(_simple(), kit_names=(SERVER,))

        assert err.details["reason"] == REASON_NAME_COLLISION
        assert err.details["server"] == SERVER
        assert err.details["field"] == "mcp_servers"

    def test_server_key_equal_to_the_prefix_of_a_registered_tool(self) -> None:
        err = _reason(_simple(), tool_names=(f"{SERVER}:search",))

        assert err.details["reason"] == REASON_NAME_COLLISION

    def test_prefix_is_the_part_before_the_first_colon(self) -> None:
        err = _reason(_simple(), tool_names=(f"{SERVER}:a:b",))

        assert err.details["reason"] == REASON_NAME_COLLISION
        # The part after the first colon is not a prefix.
        assert _validate(_simple(), tool_names=("kit:acme_srv:b",)) == (SERVER,)

    def test_server_key_equal_to_the_prefix_of_an_inline_tool(self) -> None:
        wf = _simple(tools=[{"name": f"{SERVER}:inline", "target": "mod:fn"}])

        assert _reason(wf).details["reason"] == REASON_NAME_COLLISION

    def test_server_key_equal_to_the_prefix_of_a_cli_tool_name(self) -> None:
        # ``--tool`` names reach the composition through the merged registry.
        err = _reason(_simple(), tool_names=(f"{SERVER}:from_cli_flag",))

        assert err.details["reason"] == REASON_NAME_COLLISION

    def test_unnamed_declaration_collisions_are_also_rejected(self) -> None:
        wf = _wf(
            [_mcp()],
            servers={SERVER: _decl(), OTHER: _decl()},
            allowed=[QUALIFIED],
        )

        err = _reason(wf, kit_names=(OTHER,))

        assert err.details["server"] == OTHER

    def test_unrelated_names_do_not_collide(self) -> None:
        wf = _simple(tools=[{"name": "kit:inline", "target": "mod:fn"}])

        assert _validate(wf, tool_names=("kit:x", "plain"), kit_names=("kit",)) == (SERVER,)

    def test_bare_tool_name_equal_to_the_key_has_no_prefix_and_does_not_collide(self) -> None:
        # Interpretation recorded in impl-progress: only names that contain a colon
        # have a "part before the first colon".
        assert _validate(_simple(), tool_names=(SERVER,)) == (SERVER,)


# ---------------------------------------------------------------------------
# AC 10: a declared server requires an allowlist
# ---------------------------------------------------------------------------


class TestMissingAllowlist:
    def test_servers_without_allowlist_is_rejected(self) -> None:
        err = _reason(_wf([_mcp()], servers={SERVER: _decl()}, allowed=None))

        assert err.details["reason"] == REASON_MISSING_ALLOWLIST
        assert err.details["field"] == "allowed_tools"

    def test_empty_servers_map_without_allowlist_is_rejected(self) -> None:
        err = _reason(_wf([_plain("p")], servers={}, allowed=None))

        assert err.details["reason"] == REASON_MISSING_ALLOWLIST

    def test_empty_servers_map_with_empty_allowlist_is_accepted(self) -> None:
        assert _validate(_wf([_plain("p")], servers={}, allowed=[])) == ()

    def test_empty_allowlist_excludes_everything(self) -> None:
        err = _reason(_wf([_mcp()], servers={SERVER: _decl()}, allowed=[]))

        assert err.details["reason"] == REASON_TOOL_NOT_ALLOWED

    def test_allowlist_enumerating_mcp_and_local_tools_is_accepted(self) -> None:
        local = Step(id="l", primitive="tool", config={"tool": "local_tool"})
        wf = _wf([local, _mcp()], servers={SERVER: _decl()}, allowed=["local_tool", QUALIFIED])

        assert _validate(wf) == (SERVER,)

    def test_missing_allowlist_is_checked_before_everything_else(self) -> None:
        wf = _wf(
            [_mcp(server="$bad")],
            servers={SERVER: _decl(transport="nope")},
            allowed=None,
        )

        assert _reason(wf, kit_names=(SERVER,)).details["reason"] == REASON_MISSING_ALLOWLIST

    def test_no_servers_declared_and_no_allowlist_is_not_an_error(self) -> None:
        assert _validate(_wf([_plain("p")], servers=None, allowed=None)) == ()


# ---------------------------------------------------------------------------
# AC 12: one fixed message, stable reasons, no values in details
# ---------------------------------------------------------------------------


def _every_failing_workflow() -> dict[str, tuple[Workflow, dict[str, Any]]]:
    marker_tool = f"tool-{FAKE_SECRET_MARKER}"
    marker_endpoint = f"https://{FAKE_SECRET_MARKER.lower()}.example/mcp"
    marker_args = {"token": FAKE_SECRET_MARKER}
    secret_step = Step(
        id="s",
        primitive="tool",
        config={
            "mcp_server": f"srv-{FAKE_SECRET_MARKER}",
            "tool": marker_tool,
            "arguments": marker_args,
        },
    )
    declared = {SERVER: _decl(endpoint=marker_endpoint)}
    named = Step(
        id="s",
        primitive="tool",
        config={"mcp_server": SERVER, "tool": marker_tool, "arguments": marker_args},
    )
    return {
        REASON_MISSING_ALLOWLIST: (_wf([named], servers=declared, allowed=None), {}),
        REASON_INVALID_NAME: (
            _wf(
                [
                    Step(
                        id="s",
                        primitive="tool",
                        config={
                            "mcp_server": f"$input.{FAKE_SECRET_MARKER}",
                            "tool": marker_tool,
                            "arguments": marker_args,
                        },
                    )
                ],
                servers=declared,
                allowed=[],
            ),
            {},
        ),
        REASON_UNDECLARED_SERVER: (_wf([secret_step], servers=declared, allowed=[]), {}),
        REASON_UNKNOWN_TRANSPORT: (_wf([named], servers=declared, allowed=[]), {"transports": ()}),
        REASON_TOOL_NOT_ALLOWED: (_wf([named], servers=declared, allowed=[]), {}),
        REASON_NAME_COLLISION: (
            _wf([named], servers=declared, allowed=[f"{SERVER}:{marker_tool}"]),
            {"kit_names": (SERVER,)},
        ),
    }


class TestCompositionErrorShape:
    def test_every_reason_is_reachable_with_the_same_code_and_message(self) -> None:
        for expected, (workflow, kwargs) in _every_failing_workflow().items():
            err = _reason(workflow, **kwargs)
            assert err.details["reason"] == expected

    def test_message_is_identical_across_inputs(self) -> None:
        messages = {
            _reason(workflow, **kwargs).message
            for workflow, kwargs in _every_failing_workflow().values()
        }

        assert messages == {COMPOSITION_FAILED_MESSAGE}

    def test_details_never_hold_input_values(self) -> None:
        for workflow, kwargs in _every_failing_workflow().values():
            err = _reason(workflow, **kwargs)
            assert_marker_absent(err)
            assert FAKE_SECRET_MARKER.lower() not in repr(err.details).lower()
            assert set(err.details) <= {"reason", "field", "step_id", "server"}

    def test_details_keys_are_value_free_names(self) -> None:
        err = _reason(_simple(servers={SERVER: _decl(transport="nope")}))

        assert err.details == {
            "reason": REASON_UNKNOWN_TRANSPORT,
            "field": "transport",
            "step_id": "m1",
            "server": SERVER,
        }

    def test_errors_are_not_chained(self) -> None:
        for workflow, kwargs in _every_failing_workflow().values():
            assert_unchained(_reason(workflow, **kwargs))

    def test_reason_constants_are_distinct_strings(self) -> None:
        names = [n for n in dir(mcp_composition) if n.startswith("REASON_")]
        values = [getattr(mcp_composition, n) for n in names]

        assert len(values) == len(set(values)) >= 12
        assert all(isinstance(v, str) and v == v.lower() for v in values)


# ---------------------------------------------------------------------------
# Domain rule: stdlib, pydantic and domain imports only; pure
# ---------------------------------------------------------------------------


class TestModuleStaysPure:
    def test_imports_are_stdlib_or_domain_only(self) -> None:
        tree = ast.parse(inspect.getsource(mcp_composition))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module)

        for module in modules:
            top = module.split(".")[0]
            assert top in {"__future__", "collections", "typing", "beddel"}, module
            if top == "beddel":
                assert module in {
                    "beddel.domain.errors",
                    "beddel.domain.models",
                    "beddel.error_codes",
                }, module

    def test_validation_does_no_io_and_builds_no_client(self) -> None:
        log = EventLog()
        client = FakeMCPClient(TRANSPORT, ENDPOINT, "none", log=log)
        before = list(log.events)

        _validate(_simple())

        assert log.events == before == [("constructed", ENDPOINT)]
        assert client.connected is False
