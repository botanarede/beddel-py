"""Unit tests for IApprovalGate protocol conformance and wiring (Story 6.1, Tasks 6.3, 6.4).

Tests: Protocol conformance, ExecutionDependencies wiring, pause/resume integration.
"""

from __future__ import annotations

from beddel.adapters.approval import ConfigurableApprovalGate, InMemoryApprovalGate
from beddel.domain.models import (
    DefaultDependencies,
    ExecutionContext,
)
from beddel.domain.ports import ExecutionDependencies, IApprovalGate

# ---------------------------------------------------------------------------
# IApprovalGate protocol conformance (Task 6.3)
# ---------------------------------------------------------------------------


class TestIApprovalGateProtocol:
    """InMemoryApprovalGate and ConfigurableApprovalGate satisfy IApprovalGate."""

    def test_in_memory_gate_has_request_approval(self) -> None:
        gate = InMemoryApprovalGate()
        assert hasattr(gate, "request_approval")
        assert callable(gate.request_approval)

    def test_in_memory_gate_has_check_status(self) -> None:
        gate = InMemoryApprovalGate()
        assert hasattr(gate, "check_status")
        assert callable(gate.check_status)

    def test_in_memory_gate_has_request_approval_async(self) -> None:
        gate = InMemoryApprovalGate()
        assert hasattr(gate, "request_approval_async")
        assert callable(gate.request_approval_async)

    def test_configurable_gate_has_request_approval(self) -> None:
        gate = ConfigurableApprovalGate()
        assert hasattr(gate, "request_approval")
        assert callable(gate.request_approval)

    def test_configurable_gate_has_check_status(self) -> None:
        gate = ConfigurableApprovalGate()
        assert hasattr(gate, "check_status")
        assert callable(gate.check_status)

    def test_configurable_gate_has_request_approval_async(self) -> None:
        gate = ConfigurableApprovalGate()
        assert hasattr(gate, "request_approval_async")
        assert callable(gate.request_approval_async)

    def test_protocol_has_request_approval(self) -> None:
        assert hasattr(IApprovalGate, "request_approval")

    def test_protocol_has_check_status(self) -> None:
        assert hasattr(IApprovalGate, "check_status")

    def test_protocol_has_request_approval_async(self) -> None:
        assert hasattr(IApprovalGate, "request_approval_async")

    def test_protocol_in_ports_all(self) -> None:
        from beddel.domain import ports

        assert "IApprovalGate" in ports.__all__


# ---------------------------------------------------------------------------
# ExecutionDependencies wiring (Task 6.3)
# ---------------------------------------------------------------------------


class TestExecutionDependenciesWiring:
    """DefaultDependencies accepts and exposes approval_gate."""

    def test_default_dependencies_accepts_approval_gate(self) -> None:
        gate = InMemoryApprovalGate()
        deps = DefaultDependencies(approval_gate=gate)
        assert deps.approval_gate is gate

    def test_default_dependencies_approval_gate_defaults_to_none(self) -> None:
        deps = DefaultDependencies()
        assert deps.approval_gate is None

    def test_execution_dependencies_protocol_has_approval_gate(self) -> None:
        attrs = ExecutionDependencies.__protocol_attrs__
        assert "approval_gate" in attrs

    def test_default_dependencies_satisfies_protocol(self) -> None:
        """DefaultDependencies structurally satisfies ExecutionDependencies."""
        deps = DefaultDependencies()
        assert hasattr(deps, "approval_gate")
        assert hasattr(deps, "llm_provider")
        assert hasattr(deps, "lifecycle_hooks")


# ---------------------------------------------------------------------------
# Pause/resume integration (Task 6.4)
# ---------------------------------------------------------------------------


class TestPauseResumeIntegration:
    """InterruptibleContext serialize/restore captures suspended state."""

    def test_context_suspended_default_false(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-1")
        assert ctx.suspended is False

    def test_set_suspended_true(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-1")
        ctx.suspended = True
        assert ctx.suspended is True

    def test_serialize_captures_suspended_state(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-1")
        ctx.suspended = True
        data = ctx.serialize()
        assert data["suspended"] is True

    def test_serialize_captures_suspended_false(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-1")
        data = ctx.serialize()
        assert data["suspended"] is False

    def test_restore_restores_suspended_true(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-1")
        ctx.suspended = True
        data = ctx.serialize()

        ctx2 = ExecutionContext(workflow_id="wf-2")
        ctx2.restore(data)
        assert ctx2.suspended is True

    def test_restore_restores_suspended_false(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-1")
        data = ctx.serialize()

        ctx2 = ExecutionContext(workflow_id="wf-2")
        ctx2.suspended = True  # set to True first
        ctx2.restore(data)
        assert ctx2.suspended is False

    def test_serialize_preserves_workflow_id(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-1", inputs={"key": "val"})
        ctx.suspended = True
        data = ctx.serialize()
        assert data["workflow_id"] == "wf-1"
        assert data["inputs"] == {"key": "val"}

    def test_restore_round_trip_with_step_results(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-1")
        ctx.step_results["step-1"] = "result-1"
        ctx.suspended = True
        data = ctx.serialize()

        ctx2 = ExecutionContext(workflow_id="wf-new")
        ctx2.restore(data)
        assert ctx2.step_results["step-1"] == "result-1"
        assert ctx2.suspended is True
        assert ctx2.workflow_id == "wf-1"
