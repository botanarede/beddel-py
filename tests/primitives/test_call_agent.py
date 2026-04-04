"""Unit tests for beddel.primitives.call_agent module."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from _helpers import make_context

from beddel.constants import CALL_DEPTH_KEY
from beddel.domain.errors import PrimitiveError, SkillError
from beddel.domain.models import (
    DefaultDependencies,
    ExecutionContext,
    Step,
    Workflow,
)
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins
from beddel.primitives.call_agent import CallAgentPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow(
    *,
    workflow_id: str = "child-wf",
    steps: list[Step] | None = None,
) -> Workflow:
    """Build a minimal Workflow for testing."""
    return Workflow(
        id=workflow_id,
        name="Child Workflow",
        steps=steps or [],
    )


class _RecorderPrimitive(IPrimitive):
    """Test primitive that records what it receives and stores a result."""

    def __init__(self, result: Any = "recorded") -> None:
        self.calls: list[tuple[dict[str, Any], ExecutionContext]] = []
        self._result = result

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Record the call and return the configured result."""
        self.calls.append((config, context))
        return self._result


def _make_registry(*primitives: tuple[str, IPrimitive]) -> PrimitiveRegistry:
    """Build a PrimitiveRegistry pre-loaded with given primitives."""
    reg = PrimitiveRegistry()
    for name, prim in primitives:
        reg.register(name, prim)
    return reg


# ---------------------------------------------------------------------------
# Tests: Successful nested workflow execution (subtask 4.2)
# ---------------------------------------------------------------------------


class TestNestedExecution:
    """Tests for successful nested workflow invocation."""

    async def test_calls_workflow_loader_with_workflow_id(self) -> None:
        """Verify workflow_loader is called with the workflow ID from config."""
        recorder = _RecorderPrimitive(result="child-result")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={"msg": "hi"})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader, registry=registry)

        result = await CallAgentPrimitive().execute({"workflow": "child-wf"}, ctx)

        assert "s1" in result
        assert result["s1"] == "child-result"

    async def test_returns_child_step_results(self) -> None:
        """Verify the primitive returns the child workflow's full step_results dict."""
        recorder = _RecorderPrimitive(result={"answer": 42})
        registry = _make_registry(("compute", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="calc", primitive="compute", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader, registry=registry)

        result = await CallAgentPrimitive().execute({"workflow": "math-wf"}, ctx)

        assert result == {"calc": {"answer": 42}}

    async def test_single_step_workflow_result_propagated(self) -> None:
        """Verify a single-step nested workflow propagates its result."""
        recorder = _RecorderPrimitive(result="propagated")
        registry = _make_registry(("prim-a", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="only-step", primitive="prim-a", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader, registry=registry)

        result = await CallAgentPrimitive().execute({"workflow": "single-wf"}, ctx)

        assert result == {"only-step": "propagated"}

    async def test_multi_step_nested_workflow(self) -> None:
        """Verify multiple steps in nested workflow all execute and return results."""
        rec1 = _RecorderPrimitive(result="first")
        rec2 = _RecorderPrimitive(result="second")
        registry = _make_registry(("prim-a", rec1), ("prim-b", rec2))
        child_wf = _make_workflow(
            steps=[
                Step(id="s1", primitive="prim-a", config={}),
                Step(id="s2", primitive="prim-b", config={}),
            ],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader, registry=registry)

        result = await CallAgentPrimitive().execute({"workflow": "multi-wf"}, ctx)

        assert result == {"s1": "first", "s2": "second"}


# ---------------------------------------------------------------------------
# Tests: Context passing (subtask 4.3)
# ---------------------------------------------------------------------------


class TestContextPassing:
    """Tests for child context receiving resolved inputs and inherited deps."""

    async def test_child_context_receives_resolved_inputs(self) -> None:
        """Verify inputs from config are passed to the child context."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader, registry=registry)

        await CallAgentPrimitive().execute({"workflow": "wf", "inputs": {"name": "Alice"}}, ctx)

        assert len(recorder.calls) == 1
        _, child_ctx = recorder.calls[0]
        assert child_ctx.inputs["name"] == "Alice"

    async def test_child_context_inherits_deps_from_parent(self) -> None:
        """Verify child context inherits workflow_loader and registry from parent."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        tool_reg: dict[str, Callable[..., Any]] = {"my_tool": lambda: None}
        ctx = make_context(
            workflow_id="wf-parent",
            workflow_loader=loader,
            registry=registry,
            tool_registry=tool_reg,
        )

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.deps.workflow_loader is loader
        assert child_ctx.deps.registry is registry
        assert child_ctx.deps.tool_registry is tool_reg

    async def test_child_context_gets_incremented_call_depth(self) -> None:
        """Verify _call_depth is incremented in child context metadata."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader, registry=registry)

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.metadata[CALL_DEPTH_KEY] == 1


# ---------------------------------------------------------------------------
# Tests: Max depth enforcement (subtask 4.4)
# ---------------------------------------------------------------------------


class TestMaxDepthEnforcement:
    """Tests for BEDDEL-PRIM-200 when max depth is exceeded."""

    async def test_raises_prim_200_when_depth_equals_max(self) -> None:
        """Verify error when _call_depth == max_depth (default 5)."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            workflow_loader=loader,
            registry=registry,
            metadata={CALL_DEPTH_KEY: 5},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-200") as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-200"

    async def test_raises_prim_200_when_depth_exceeds_max(self) -> None:
        """Verify error when _call_depth > max_depth."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            workflow_loader=loader,
            registry=registry,
            metadata={CALL_DEPTH_KEY: 6},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-200") as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-200"

    async def test_error_details_contain_depth_info(self) -> None:
        """Verify error details include current_depth, max_depth, primitive, step_id."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            workflow_loader=loader,
            registry=registry,
            metadata={CALL_DEPTH_KEY: 5},
        )

        with pytest.raises(PrimitiveError) as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        details = exc_info.value.details
        assert details["current_depth"] == 5
        assert details["max_depth"] == 5
        assert details["primitive"] == "call-agent"
        assert details["step_id"] == "step-1"

    async def test_executes_at_depth_below_max(self) -> None:
        """Verify execution proceeds when _call_depth < max_depth."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            workflow_loader=loader,
            registry=registry,
            metadata={CALL_DEPTH_KEY: 4},
        )

        result = await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert result == {"s1": "ok"}


# ---------------------------------------------------------------------------
# Tests: Missing workflow_loader (subtask 4.5)
# ---------------------------------------------------------------------------


class TestMissingWorkflowLoader:
    """Tests for BEDDEL-PRIM-001 when workflow_loader is None."""

    async def test_raises_prim_001_when_workflow_loader_none(self) -> None:
        """Verify BEDDEL-PRIM-001 when workflow_loader is None."""
        registry = _make_registry()
        ctx = make_context(workflow_id="wf-parent", registry=registry)

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-001") as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-001"

    async def test_error_message_mentions_workflow_loader(self) -> None:
        """Verify error message references workflow_loader."""
        registry = _make_registry()
        ctx = make_context(workflow_id="wf-parent", registry=registry)

        with pytest.raises(PrimitiveError) as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert "workflow_loader" in exc_info.value.message
        assert exc_info.value.details["primitive"] == "call-agent"


# ---------------------------------------------------------------------------
# Tests: Missing registry (subtask 4.6)
# ---------------------------------------------------------------------------


class TestMissingRegistry:
    """Tests for BEDDEL-PRIM-002 when registry is None."""

    async def test_raises_prim_002_when_registry_none(self) -> None:
        """Verify BEDDEL-PRIM-002 when registry is None."""
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader)

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-002") as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-002"

    async def test_error_message_mentions_registry(self) -> None:
        """Verify error message references registry."""
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader)

        with pytest.raises(PrimitiveError) as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert "registry" in exc_info.value.message
        assert exc_info.value.details["primitive"] == "call-agent"


# ---------------------------------------------------------------------------
# Tests: Missing workflow config key (subtask 4.7)
# ---------------------------------------------------------------------------


class TestMissingWorkflowConfig:
    """Tests for BEDDEL-PRIM-201 when 'workflow' key is missing from config."""

    async def test_raises_prim_201_when_workflow_key_missing(self) -> None:
        """Verify BEDDEL-PRIM-201 when config has no 'workflow' key."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader, registry=registry)

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-201") as exc_info:
            await CallAgentPrimitive().execute({}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-201"
        assert "workflow" in exc_info.value.message.lower()

    async def test_error_details_contain_primitive_and_step_id(self) -> None:
        """Verify error details include primitive and step_id."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            workflow_loader=loader,
            registry=registry,
            step_id="my-step",
        )

        with pytest.raises(PrimitiveError) as exc_info:
            await CallAgentPrimitive().execute({}, ctx)

        assert exc_info.value.details["primitive"] == "call-agent"
        assert exc_info.value.details["step_id"] == "my-step"


# ---------------------------------------------------------------------------
# Tests: Custom max_depth (subtask 4.8)
# ---------------------------------------------------------------------------


class TestCustomMaxDepth:
    """Tests for configurable max_depth limit."""

    async def test_custom_max_depth_allows_deeper_nesting(self) -> None:
        """Verify custom max_depth=10 allows _call_depth=7 to proceed."""
        recorder = _RecorderPrimitive(result="deep")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            workflow_loader=loader,
            registry=registry,
            metadata={CALL_DEPTH_KEY: 7},
        )

        result = await CallAgentPrimitive().execute({"workflow": "wf", "max_depth": 10}, ctx)

        assert result == {"s1": "deep"}

    async def test_custom_max_depth_enforced(self) -> None:
        """Verify custom max_depth=2 blocks _call_depth=2."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            workflow_loader=loader,
            registry=registry,
            metadata={CALL_DEPTH_KEY: 2},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-200"):
            await CallAgentPrimitive().execute({"workflow": "wf", "max_depth": 2}, ctx)


# ---------------------------------------------------------------------------
# Tests: Depth tracking across nested calls (subtask 4.9)
# ---------------------------------------------------------------------------


class TestDepthTracking:
    """Tests for _call_depth increment tracking."""

    async def test_initial_depth_is_zero_when_no_metadata(self) -> None:
        """Verify child gets _call_depth=1 when parent has no _call_depth."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader, registry=registry)

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.metadata[CALL_DEPTH_KEY] == 1

    async def test_depth_increments_from_parent(self) -> None:
        """Verify child _call_depth is parent + 1."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            workflow_loader=loader,
            registry=registry,
            metadata={CALL_DEPTH_KEY: 3},
        )

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.metadata[CALL_DEPTH_KEY] == 4

    async def test_depth_propagated_to_child_context_metadata(self) -> None:
        """Verify child_context.metadata['_call_depth'] == parent + 1."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            workflow_loader=loader,
            registry=registry,
            metadata={CALL_DEPTH_KEY: 2},
        )

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.metadata[CALL_DEPTH_KEY] == 3


# ---------------------------------------------------------------------------
# Tests: register_builtins (subtask 4.10)
# ---------------------------------------------------------------------------


class TestRegisterBuiltins:
    """Tests for call-agent registration via register_builtins."""

    def test_registers_call_agent_primitive(self) -> None:
        """Verify registry.get('call-agent') is not None after register_builtins."""
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert registry.get("call-agent") is not None

    def test_registered_is_call_agent_instance(self) -> None:
        """Verify the registered primitive is a CallAgentPrimitive instance."""
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert isinstance(registry.get("call-agent"), CallAgentPrimitive)


# ---------------------------------------------------------------------------
# Tests: Variable resolution on inputs
# ---------------------------------------------------------------------------


class TestVariableResolution:
    """Tests for $input and $stepResult resolution in config inputs."""

    async def test_resolves_input_ref_in_nested_inputs(self) -> None:
        """Verify $input refs in config.inputs are resolved before passing to child."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            inputs={"user": "Bob"},
            workflow_loader=loader,
            registry=registry,
        )

        await CallAgentPrimitive().execute(
            {"workflow": "wf", "inputs": {"name": "$input.user"}}, ctx
        )

        _, child_ctx = recorder.calls[0]
        assert child_ctx.inputs["name"] == "Bob"

    async def test_resolves_step_result_ref_in_nested_inputs(self) -> None:
        """Verify $stepResult refs in config.inputs are resolved."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(
            workflow_id="wf-parent",
            step_results={"prev": {"data": "resolved-value"}},
            workflow_loader=loader,
            registry=registry,
        )

        await CallAgentPrimitive().execute(
            {"workflow": "wf", "inputs": {"val": "$stepResult.prev.data"}},
            ctx,
        )

        _, child_ctx = recorder.calls[0]
        assert child_ctx.inputs["val"] == "resolved-value"

    async def test_no_inputs_passes_empty_dict(self) -> None:
        """Verify empty inputs when config has no 'inputs' key."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = make_context(workflow_id="wf-parent", workflow_loader=loader, registry=registry)

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.inputs == {}


# ---------------------------------------------------------------------------
# Story 3.5 / Task 3 — Public API usage (no _execute_step access)
# ---------------------------------------------------------------------------


class TestPublicAPIUsage:
    """AST-based check that call_agent.py uses the public API."""

    def test_call_agent_does_not_access_private_execute_step(self) -> None:
        """call_agent.py source must not contain any _execute_step references."""
        import ast
        from pathlib import Path

        call_agent_path = (
            Path(__file__).resolve().parents[2] / "src" / "beddel" / "primitives" / "call_agent.py"
        )
        source = call_agent_path.read_text()
        tree = ast.parse(source)

        private_refs: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "_execute_step":
                private_refs.append(f"line {node.lineno}: .{node.attr}")

        assert private_refs == [], (
            "call_agent.py still accesses private _execute_step:\n" + "\n".join(private_refs)
        )


# ---------------------------------------------------------------------------
# Tests: Skill invocation via call-agent (Story 7.4, Task 3)
# ---------------------------------------------------------------------------


def _make_kit_manifest(
    *,
    kit_name: str = "software-development-kit",
    kit_version: str = "0.2.0",
    workflow_name: str = "create-epic",
    workflow_path: str = "workflows/create-epic.yaml",
    root_path: Path | None = None,
) -> Any:
    """Build a mock KitManifest for skill resolution tests."""
    wf_decl = MagicMock()
    wf_decl.name = workflow_name
    wf_decl.path = workflow_path

    kit = MagicMock()
    kit.name = kit_name
    kit.version = kit_version
    kit.workflows = [wf_decl]

    manifest = MagicMock()
    manifest.kit = kit
    manifest.root_path = root_path or Path("/kits/sdk")
    return manifest


def _make_skill_context(
    *,
    kit_manifests: list[Any] | None = None,
    workflow_loader: Callable[[str], Any] | None = None,
    registry: PrimitiveRegistry | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExecutionContext:
    """Build an ExecutionContext with kit_manifests for skill tests."""
    ctx = ExecutionContext(
        workflow_id="wf-parent",
        inputs={},
        current_step_id="step-1",
        metadata=metadata or {},
    )
    ctx.deps = DefaultDependencies(
        workflow_loader=workflow_loader,
        registry=registry,
        kit_manifests=kit_manifests,
    )
    return ctx


class TestSkillInvocationHappyPath:
    """Tests for successful skill invocation via call-agent."""

    async def test_skill_resolves_and_executes_sub_workflow(self) -> None:
        """Verify skill config resolves to kit workflow and executes it."""
        recorder = _RecorderPrimitive(result="skill-result")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={"msg": "from-skill"})],
        )
        manifest = _make_kit_manifest()
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = _make_skill_context(
            kit_manifests=[manifest],
            workflow_loader=loader,
            registry=registry,
        )

        config = {
            "skill": {
                "kit": "software-development-kit",
                "workflow": "create-epic",
                "version": ">=0.1.0",
            },
        }
        result = await CallAgentPrimitive().execute(config, ctx)

        assert result == {"s1": "skill-result"}

    async def test_skill_loader_receives_resolved_path(self) -> None:
        """Verify workflow_loader is called with the resolved path string."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        calls: list[str] = []

        def tracking_loader(wf_id: str) -> Workflow:
            calls.append(wf_id)
            return child_wf

        manifest = _make_kit_manifest(root_path=Path("/kits/sdk"))
        ctx = _make_skill_context(
            kit_manifests=[manifest],
            workflow_loader=tracking_loader,
            registry=registry,
        )

        config = {
            "skill": {
                "kit": "software-development-kit",
                "workflow": "create-epic",
                "version": ">=0.1.0",
            },
        }
        await CallAgentPrimitive().execute(config, ctx)

        assert len(calls) == 1
        assert calls[0] == str(Path("/kits/sdk/workflows/create-epic.yaml"))

    async def test_skill_passes_inputs_to_child(self) -> None:
        """Verify inputs from config are passed to the skill sub-workflow."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        manifest = _make_kit_manifest()
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = _make_skill_context(
            kit_manifests=[manifest],
            workflow_loader=loader,
            registry=registry,
        )

        config = {
            "skill": {
                "kit": "software-development-kit",
                "workflow": "create-epic",
                "version": ">=0.1.0",
            },
            "inputs": {"name": "test-epic"},
        }
        await CallAgentPrimitive().execute(config, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.inputs["name"] == "test-epic"

    async def test_skill_child_inherits_kit_manifests(self) -> None:
        """Verify child context inherits kit_manifests for nested skill calls."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        manifest = _make_kit_manifest()
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = _make_skill_context(
            kit_manifests=[manifest],
            workflow_loader=loader,
            registry=registry,
        )

        config = {
            "skill": {
                "kit": "software-development-kit",
                "workflow": "create-epic",
                "version": ">=0.1.0",
            },
        }
        await CallAgentPrimitive().execute(config, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.deps.kit_manifests is not None
        assert len(child_ctx.deps.kit_manifests) == 1


class TestSkillNotFound:
    """Tests for skill resolution failures — kit not found."""

    async def test_raises_skill_error_when_kit_not_found(self) -> None:
        """Verify SkillError with BEDDEL-SKILL-1201 when kit is missing."""
        registry = _make_registry()
        manifest = _make_kit_manifest(kit_name="other-kit")
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = _make_skill_context(
            kit_manifests=[manifest],
            workflow_loader=loader,
            registry=registry,
        )

        config = {
            "skill": {
                "kit": "nonexistent-kit",
                "workflow": "create-epic",
                "version": ">=0.1.0",
            },
        }
        with pytest.raises(SkillError, match="BEDDEL-SKILL-1201"):
            await CallAgentPrimitive().execute(config, ctx)

    async def test_raises_skill_error_when_workflow_not_found(self) -> None:
        """Verify SkillError with BEDDEL-SKILL-1202 when workflow is missing."""
        registry = _make_registry()
        manifest = _make_kit_manifest(workflow_name="other-workflow")
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = _make_skill_context(
            kit_manifests=[manifest],
            workflow_loader=loader,
            registry=registry,
        )

        config = {
            "skill": {
                "kit": "software-development-kit",
                "workflow": "nonexistent-workflow",
                "version": ">=0.1.0",
            },
        }
        with pytest.raises(SkillError, match="BEDDEL-SKILL-1202"):
            await CallAgentPrimitive().execute(config, ctx)


class TestSkillVersionMismatch:
    """Tests for skill version constraint failures."""

    async def test_raises_skill_error_on_version_mismatch(self) -> None:
        """Verify SkillError with BEDDEL-SKILL-1203 on version mismatch."""
        registry = _make_registry()
        manifest = _make_kit_manifest(kit_version="0.1.0")
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = _make_skill_context(
            kit_manifests=[manifest],
            workflow_loader=loader,
            registry=registry,
        )

        config = {
            "skill": {
                "kit": "software-development-kit",
                "workflow": "create-epic",
                "version": ">=1.0.0",
            },
        }
        with pytest.raises(SkillError, match="BEDDEL-SKILL-1203"):
            await CallAgentPrimitive().execute(config, ctx)


class TestSkillGovernanceBlock:
    """Tests for skill governance enforcement via call-agent."""

    async def test_raises_skill_error_when_blocked_by_governance(self) -> None:
        """Verify SkillError with BEDDEL-SKILL-1204 when kit is blocked."""
        registry = _make_registry()
        manifest = _make_kit_manifest()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        governance = {
            "policy": "permissive",
            "blocked": ["software-development-kit"],
        }
        ctx = _make_skill_context(
            kit_manifests=[manifest],
            workflow_loader=loader,
            registry=registry,
            metadata={"_skill_governance": governance},
        )

        config = {
            "skill": {
                "kit": "software-development-kit",
                "workflow": "create-epic",
                "version": ">=0.1.0",
            },
        }
        with pytest.raises(SkillError, match="BEDDEL-SKILL-1204"):
            await CallAgentPrimitive().execute(config, ctx)

    async def test_raises_skill_error_when_not_in_allowed_list(self) -> None:
        """Verify SkillError with BEDDEL-SKILL-1205 when kit not in allowed list."""
        registry = _make_registry()
        manifest = _make_kit_manifest()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        governance = {
            "policy": "strict",
            "allowed": ["other-kit-only"],
        }
        ctx = _make_skill_context(
            kit_manifests=[manifest],
            workflow_loader=loader,
            registry=registry,
            metadata={"_skill_governance": governance},
        )

        config = {
            "skill": {
                "kit": "software-development-kit",
                "workflow": "create-epic",
                "version": ">=0.1.0",
            },
        }
        with pytest.raises(SkillError, match="BEDDEL-SKILL-1205"):
            await CallAgentPrimitive().execute(config, ctx)

    async def test_governance_propagated_to_child_context(self) -> None:
        """Verify governance is stored in child context metadata for nested calls."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        manifest = _make_kit_manifest()
        loader = lambda wf_id: child_wf  # noqa: E731
        governance = {
            "policy": "strict",
            "allowed": ["software-development-kit"],
        }
        ctx = _make_skill_context(
            kit_manifests=[manifest],
            workflow_loader=loader,
            registry=registry,
            metadata={"_skill_governance": governance},
        )

        config = {
            "skill": {
                "kit": "software-development-kit",
                "workflow": "create-epic",
                "version": ">=0.1.0",
            },
        }
        await CallAgentPrimitive().execute(config, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.metadata["_skill_governance"] == governance

    async def test_missing_kit_manifests_raises_prim_error(self) -> None:
        """Verify PrimitiveError when kit_manifests is None."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = _make_skill_context(
            kit_manifests=None,
            workflow_loader=loader,
            registry=registry,
        )

        config = {
            "skill": {
                "kit": "software-development-kit",
                "workflow": "create-epic",
                "version": ">=0.1.0",
            },
        }
        with pytest.raises(PrimitiveError, match="kit_manifests"):
            await CallAgentPrimitive().execute(config, ctx)
