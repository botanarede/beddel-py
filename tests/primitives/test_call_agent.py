"""Unit tests for beddel.primitives.call_agent module."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from beddel.domain.errors import PrimitiveError
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


def _make_context(
    *,
    inputs: dict[str, Any] | None = None,
    step_results: dict[str, Any] | None = None,
    step_id: str | None = "step-1",
    metadata: dict[str, Any] | None = None,
    workflow_loader: Callable[[str], Workflow] | None = None,
    registry: PrimitiveRegistry | None = None,
    tool_registry: dict[str, Callable[..., Any]] | None = None,
) -> ExecutionContext:
    """Build an ExecutionContext with optional deps for call-agent tests."""
    ctx = ExecutionContext(
        workflow_id="wf-parent",
        inputs=inputs or {},
        step_results=step_results or {},
        current_step_id=step_id,
        metadata=metadata or {},
    )
    ctx.deps = DefaultDependencies(
        workflow_loader=workflow_loader,
        registry=registry,
        tool_registry=tool_registry,
    )
    return ctx


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
        ctx = _make_context(workflow_loader=loader, registry=registry)

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
        ctx = _make_context(workflow_loader=loader, registry=registry)

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
        ctx = _make_context(workflow_loader=loader, registry=registry)

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
        ctx = _make_context(workflow_loader=loader, registry=registry)

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
        ctx = _make_context(workflow_loader=loader, registry=registry)

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
        ctx = _make_context(workflow_loader=loader, registry=registry, tool_registry=tool_reg)

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
        ctx = _make_context(workflow_loader=loader, registry=registry)

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.metadata["_call_depth"] == 1


# ---------------------------------------------------------------------------
# Tests: Max depth enforcement (subtask 4.4)
# ---------------------------------------------------------------------------


class TestMaxDepthEnforcement:
    """Tests for BEDDEL-PRIM-200 when max depth is exceeded."""

    async def test_raises_prim_200_when_depth_equals_max(self) -> None:
        """Verify error when _call_depth == max_depth (default 5)."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = _make_context(
            workflow_loader=loader,
            registry=registry,
            metadata={"_call_depth": 5},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-200") as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-200"

    async def test_raises_prim_200_when_depth_exceeds_max(self) -> None:
        """Verify error when _call_depth > max_depth."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = _make_context(
            workflow_loader=loader,
            registry=registry,
            metadata={"_call_depth": 6},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-200") as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-200"

    async def test_error_details_contain_depth_info(self) -> None:
        """Verify error details include current_depth, max_depth, primitive, step_id."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = _make_context(
            workflow_loader=loader,
            registry=registry,
            metadata={"_call_depth": 5},
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
        ctx = _make_context(
            workflow_loader=loader,
            registry=registry,
            metadata={"_call_depth": 4},
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
        ctx = _make_context(registry=registry)

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-001") as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-001"

    async def test_error_message_mentions_workflow_loader(self) -> None:
        """Verify error message references workflow_loader."""
        registry = _make_registry()
        ctx = _make_context(registry=registry)

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
        ctx = _make_context(workflow_loader=loader)

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-002") as exc_info:
            await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-002"

    async def test_error_message_mentions_registry(self) -> None:
        """Verify error message references registry."""
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = _make_context(workflow_loader=loader)

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
        ctx = _make_context(workflow_loader=loader, registry=registry)

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-201") as exc_info:
            await CallAgentPrimitive().execute({}, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-201"
        assert "workflow" in exc_info.value.message.lower()

    async def test_error_details_contain_primitive_and_step_id(self) -> None:
        """Verify error details include primitive and step_id."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = _make_context(workflow_loader=loader, registry=registry, step_id="my-step")

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
        ctx = _make_context(
            workflow_loader=loader,
            registry=registry,
            metadata={"_call_depth": 7},
        )

        result = await CallAgentPrimitive().execute({"workflow": "wf", "max_depth": 10}, ctx)

        assert result == {"s1": "deep"}

    async def test_custom_max_depth_enforced(self) -> None:
        """Verify custom max_depth=2 blocks _call_depth=2."""
        registry = _make_registry()
        loader = lambda wf_id: _make_workflow()  # noqa: E731
        ctx = _make_context(
            workflow_loader=loader,
            registry=registry,
            metadata={"_call_depth": 2},
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
        ctx = _make_context(workflow_loader=loader, registry=registry)

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.metadata["_call_depth"] == 1

    async def test_depth_increments_from_parent(self) -> None:
        """Verify child _call_depth is parent + 1."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = _make_context(
            workflow_loader=loader,
            registry=registry,
            metadata={"_call_depth": 3},
        )

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.metadata["_call_depth"] == 4

    async def test_depth_propagated_to_child_context_metadata(self) -> None:
        """Verify child_context.metadata['_call_depth'] == parent + 1."""
        recorder = _RecorderPrimitive(result="ok")
        registry = _make_registry(("echo", recorder))
        child_wf = _make_workflow(
            steps=[Step(id="s1", primitive="echo", config={})],
        )
        loader = lambda wf_id: child_wf  # noqa: E731
        ctx = _make_context(
            workflow_loader=loader,
            registry=registry,
            metadata={"_call_depth": 2},
        )

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.metadata["_call_depth"] == 3


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
        ctx = _make_context(
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
        ctx = _make_context(
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
        ctx = _make_context(workflow_loader=loader, registry=registry)

        await CallAgentPrimitive().execute({"workflow": "wf"}, ctx)

        _, child_ctx = recorder.calls[0]
        assert child_ctx.inputs == {}
