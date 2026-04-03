"""Unit tests for approval gate adapters (Story 6.1, Tasks 6.2, 6.5, 6.6).

Tests: InMemoryApprovalGate, ConfigurableApprovalGate, CIBA async flow,
timeout escalation, lifecycle hooks.
"""

from __future__ import annotations

import asyncio

from beddel.adapters.approval import ConfigurableApprovalGate, InMemoryApprovalGate
from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.models import (
    ApprovalPolicy,
    ApprovalResult,
    ApprovalStatus,
    RiskLevel,
)
from beddel.domain.ports import ILifecycleHook

# ---------------------------------------------------------------------------
# InMemoryApprovalGate
# ---------------------------------------------------------------------------


class TestInMemoryApprovalGate:
    """InMemoryApprovalGate auto-approves all requests."""

    async def test_auto_approves(self) -> None:
        gate = InMemoryApprovalGate()
        result = await gate.request_approval("read_file", RiskLevel.LOW)
        assert result.status == ApprovalStatus.APPROVED

    async def test_stores_history(self) -> None:
        gate = InMemoryApprovalGate()
        await gate.request_approval("read_file", RiskLevel.LOW)
        await gate.request_approval("delete_db", RiskLevel.HIGH)
        assert len(gate.history) == 2

    async def test_check_status_returns_approved(self) -> None:
        gate = InMemoryApprovalGate()
        result = await gate.request_approval("read_file", RiskLevel.LOW)
        status = await gate.check_status(result.request_id)
        assert status == ApprovalStatus.APPROVED

    async def test_check_status_unknown_id_returns_pending(self) -> None:
        gate = InMemoryApprovalGate()
        status = await gate.check_status("nonexistent")
        assert status == ApprovalStatus.PENDING

    async def test_result_has_metadata(self) -> None:
        gate = InMemoryApprovalGate()
        result = await gate.request_approval("write_config", RiskLevel.MEDIUM)
        assert result.metadata["action"] == "write_config"
        assert result.metadata["risk_level"] == "medium"

    async def test_result_has_approver(self) -> None:
        gate = InMemoryApprovalGate()
        result = await gate.request_approval("read_file", RiskLevel.LOW)
        assert result.approver == "auto"

    async def test_result_has_timestamp(self) -> None:
        gate = InMemoryApprovalGate()
        result = await gate.request_approval("read_file", RiskLevel.LOW)
        assert result.timestamp > 0

    async def test_request_approval_async_returns_request_id(self) -> None:
        gate = InMemoryApprovalGate()
        request_id = await gate.request_approval_async("read_file", RiskLevel.LOW)
        assert isinstance(request_id, str)
        assert len(request_id) > 0

    async def test_request_approval_async_auto_approves(self) -> None:
        gate = InMemoryApprovalGate()
        request_id = await gate.request_approval_async("read_file", RiskLevel.LOW)
        status = await gate.check_status(request_id)
        assert status == ApprovalStatus.APPROVED


# ---------------------------------------------------------------------------
# ConfigurableApprovalGate — basic risk-based logic
# ---------------------------------------------------------------------------


class TestConfigurableApprovalGate:
    """ConfigurableApprovalGate applies risk-based auto-approve logic."""

    async def test_auto_approve_for_low_risk(self) -> None:
        policy = ApprovalPolicy(auto_approve_levels=[RiskLevel.LOW])
        gate = ConfigurableApprovalGate(policy=policy)
        result = await gate.request_approval("read_file", RiskLevel.LOW)
        assert result.status == ApprovalStatus.APPROVED

    async def test_pending_for_high_risk(self) -> None:
        policy = ApprovalPolicy(auto_approve_levels=[RiskLevel.LOW])
        gate = ConfigurableApprovalGate(policy=policy)
        result = await gate.request_approval("delete_db", RiskLevel.HIGH)
        assert result.status == ApprovalStatus.PENDING

    async def test_pending_for_medium_risk_default_policy(self) -> None:
        gate = ConfigurableApprovalGate()
        result = await gate.request_approval("write_config", RiskLevel.MEDIUM)
        assert result.status == ApprovalStatus.PENDING

    async def test_auto_approve_multiple_levels(self) -> None:
        policy = ApprovalPolicy(
            auto_approve_levels=[RiskLevel.LOW, RiskLevel.MEDIUM],
        )
        gate = ConfigurableApprovalGate(policy=policy)
        low = await gate.request_approval("read_file", RiskLevel.LOW)
        med = await gate.request_approval("write_config", RiskLevel.MEDIUM)
        assert low.status == ApprovalStatus.APPROVED
        assert med.status == ApprovalStatus.APPROVED

    async def test_approved_has_policy_approver(self) -> None:
        gate = ConfigurableApprovalGate()
        result = await gate.request_approval("read_file", RiskLevel.LOW)
        assert result.approver == "policy"

    async def test_pending_has_no_approver(self) -> None:
        gate = ConfigurableApprovalGate()
        result = await gate.request_approval("delete_db", RiskLevel.HIGH)
        assert result.approver is None


# ---------------------------------------------------------------------------
# ConfigurableApprovalGate.resolve()
# ---------------------------------------------------------------------------


class TestConfigurableResolve:
    """External resolution of pending requests via resolve()."""

    async def test_resolve_pending_to_approved(self) -> None:
        gate = ConfigurableApprovalGate()
        result = await gate.request_approval("delete_db", RiskLevel.HIGH)
        updated = await gate.resolve(result.request_id, ApprovalStatus.APPROVED, "alice")
        assert updated is not None
        assert updated.status == ApprovalStatus.APPROVED
        assert updated.approver == "alice"

    async def test_resolve_pending_to_denied(self) -> None:
        gate = ConfigurableApprovalGate()
        result = await gate.request_approval("delete_db", RiskLevel.HIGH)
        updated = await gate.resolve(result.request_id, ApprovalStatus.DENIED, "bob")
        assert updated is not None
        assert updated.status == ApprovalStatus.DENIED

    async def test_resolve_already_resolved_is_noop(self) -> None:
        gate = ConfigurableApprovalGate()
        result = await gate.request_approval("read_file", RiskLevel.LOW)
        # Already APPROVED by policy
        updated = await gate.resolve(result.request_id, ApprovalStatus.DENIED, "bob")
        assert updated is not None
        assert updated.status == ApprovalStatus.APPROVED  # unchanged

    async def test_resolve_unknown_id_returns_none(self) -> None:
        gate = ConfigurableApprovalGate()
        updated = await gate.resolve("nonexistent", ApprovalStatus.APPROVED, "alice")
        assert updated is None

    async def test_check_status_after_resolve(self) -> None:
        gate = ConfigurableApprovalGate()
        result = await gate.request_approval("delete_db", RiskLevel.HIGH)
        await gate.resolve(result.request_id, ApprovalStatus.APPROVED, "alice")
        status = await gate.check_status(result.request_id)
        assert status == ApprovalStatus.APPROVED


# ---------------------------------------------------------------------------
# Timeout escalation
# ---------------------------------------------------------------------------


class TestTimeoutEscalation:
    """Timeout triggers escalation policy on pending requests."""

    async def test_auto_deny_escalation(self) -> None:
        policy = ApprovalPolicy(
            auto_approve_levels=[RiskLevel.LOW],
            timeout_seconds=0.05,
            escalation_policy="auto-deny",
        )
        gate = ConfigurableApprovalGate(policy=policy)
        result = await gate.request_approval("delete_db", RiskLevel.HIGH)
        assert result.status == ApprovalStatus.PENDING
        await asyncio.sleep(0.15)
        status = await gate.check_status(result.request_id)
        assert status == ApprovalStatus.DENIED

    async def test_auto_approve_escalation(self) -> None:
        policy = ApprovalPolicy(
            auto_approve_levels=[RiskLevel.LOW],
            timeout_seconds=0.05,
            escalation_policy="auto-approve",
        )
        gate = ConfigurableApprovalGate(policy=policy)
        result = await gate.request_approval("delete_db", RiskLevel.HIGH)
        await asyncio.sleep(0.15)
        status = await gate.check_status(result.request_id)
        assert status == ApprovalStatus.APPROVED

    async def test_delegate_escalation(self) -> None:
        policy = ApprovalPolicy(
            auto_approve_levels=[RiskLevel.LOW],
            timeout_seconds=0.05,
            escalation_policy="delegate",
        )
        gate = ConfigurableApprovalGate(policy=policy)
        result = await gate.request_approval("delete_db", RiskLevel.HIGH)
        await asyncio.sleep(0.15)
        status = await gate.check_status(result.request_id)
        assert status == ApprovalStatus.ESCALATED

    async def test_resolved_before_timeout_not_escalated(self) -> None:
        """If resolved before timeout, escalation does not overwrite."""
        policy = ApprovalPolicy(
            auto_approve_levels=[RiskLevel.LOW],
            timeout_seconds=0.05,
            escalation_policy="auto-deny",
        )
        gate = ConfigurableApprovalGate(policy=policy)
        result = await gate.request_approval("delete_db", RiskLevel.HIGH)
        await gate.resolve(result.request_id, ApprovalStatus.APPROVED, "alice")
        await asyncio.sleep(0.15)
        status = await gate.check_status(result.request_id)
        assert status == ApprovalStatus.APPROVED  # not overwritten


# ---------------------------------------------------------------------------
# CIBA async flow (Task 6.5)
# ---------------------------------------------------------------------------


class TestCIBAAsyncFlow:
    """CIBA non-blocking pattern: request_approval_async + check_status polling."""

    async def test_request_approval_async_returns_request_id(self) -> None:
        gate = ConfigurableApprovalGate()
        request_id = await gate.request_approval_async("delete_db", RiskLevel.HIGH)
        assert isinstance(request_id, str)
        assert len(request_id) > 0

    async def test_check_status_pending_initially(self) -> None:
        gate = ConfigurableApprovalGate()
        request_id = await gate.request_approval_async("delete_db", RiskLevel.HIGH)
        status = await gate.check_status(request_id)
        assert status == ApprovalStatus.PENDING

    async def test_timeout_triggers_escalation(self) -> None:
        policy = ApprovalPolicy(
            auto_approve_levels=[RiskLevel.LOW],
            timeout_seconds=0.05,
            escalation_policy="auto-deny",
        )
        gate = ConfigurableApprovalGate(policy=policy)
        request_id = await gate.request_approval_async("delete_db", RiskLevel.HIGH)
        status_before = await gate.check_status(request_id)
        assert status_before == ApprovalStatus.PENDING
        await asyncio.sleep(0.15)
        status_after = await gate.check_status(request_id)
        assert status_after == ApprovalStatus.DENIED

    async def test_auto_approve_low_risk_async(self) -> None:
        gate = ConfigurableApprovalGate()
        request_id = await gate.request_approval_async("read_file", RiskLevel.LOW)
        status = await gate.check_status(request_id)
        assert status == ApprovalStatus.APPROVED


# ---------------------------------------------------------------------------
# Lifecycle hooks (Task 6.6)
# ---------------------------------------------------------------------------


class _ApprovalRecordingHook(ILifecycleHook):
    """Custom hook that records approval lifecycle calls."""

    def __init__(self) -> None:
        self.approval_requested: list[tuple[str, str, RiskLevel]] = []
        self.approval_received: list[tuple[str, ApprovalResult]] = []

    async def on_approval_requested(
        self, step_id: str, action: str, risk_level: RiskLevel
    ) -> None:
        self.approval_requested.append((step_id, action, risk_level))

    async def on_approval_received(self, step_id: str, result: ApprovalResult) -> None:
        self.approval_received.append((step_id, result))


class TestLifecycleHooks:
    """Lifecycle hooks fire correctly for approval events."""

    async def test_on_approval_requested_fires(self) -> None:
        hook = _ApprovalRecordingHook()
        manager = LifecycleHookManager([hook])
        await manager.on_approval_requested("step-1", "delete_db", RiskLevel.HIGH)
        assert len(hook.approval_requested) == 1
        step_id, action, risk = hook.approval_requested[0]
        assert step_id == "step-1"
        assert action == "delete_db"
        assert risk == RiskLevel.HIGH

    async def test_on_approval_received_fires(self) -> None:
        hook = _ApprovalRecordingHook()
        manager = LifecycleHookManager([hook])
        result = ApprovalResult(
            request_id="req-1",
            status=ApprovalStatus.APPROVED,
            approver="alice",
        )
        await manager.on_approval_received("step-1", result)
        assert len(hook.approval_received) == 1
        step_id, received_result = hook.approval_received[0]
        assert step_id == "step-1"
        assert received_result.status == ApprovalStatus.APPROVED
        assert received_result.approver == "alice"

    async def test_multiple_hooks_receive_approval_events(self) -> None:
        hook_a = _ApprovalRecordingHook()
        hook_b = _ApprovalRecordingHook()
        manager = LifecycleHookManager([hook_a, hook_b])
        await manager.on_approval_requested("step-1", "write_config", RiskLevel.MEDIUM)
        assert len(hook_a.approval_requested) == 1
        assert len(hook_b.approval_requested) == 1

    async def test_default_hook_noop_does_not_raise(self) -> None:
        """Default ILifecycleHook methods are no-ops."""
        hook = ILifecycleHook()
        await hook.on_approval_requested("step-1", "read_file", RiskLevel.LOW)
        await hook.on_approval_received(
            "step-1",
            ApprovalResult(request_id="req-1", status=ApprovalStatus.APPROVED),
        )
