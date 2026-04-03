"""In-memory approval gate adapters for HOTL approval flows.

Implements :class:`~beddel.domain.ports.IApprovalGate` with two variants:

- :class:`InMemoryApprovalGate` — auto-approves every request immediately.
  Designed for testing and development where human approval is not needed.
- :class:`ConfigurableApprovalGate` — applies risk-based auto-approve logic
  using an :class:`~beddel.domain.models.ApprovalPolicy`.  Requests whose
  risk level is in ``policy.auto_approve_levels`` are auto-approved; all
  others are stored as PENDING for later resolution (CIBA async flow).

Both adapters use ``uuid.uuid4().hex`` for request IDs and ``time.time()``
for timestamps.
"""

from __future__ import annotations

import time
import uuid

from beddel.domain.models import (
    ApprovalPolicy,
    ApprovalResult,
    ApprovalStatus,
    RiskLevel,
)

__all__ = [
    "ConfigurableApprovalGate",
    "InMemoryApprovalGate",
]


class InMemoryApprovalGate:
    """Auto-approving approval gate for testing and development.

    Satisfies the :class:`~beddel.domain.ports.IApprovalGate` protocol
    via structural subtyping.  Every request is immediately approved and
    stored in an internal history list for test assertions.

    Example::

        gate = InMemoryApprovalGate()
        result = await gate.request_approval("read_file", RiskLevel.LOW)
        assert result.status == ApprovalStatus.APPROVED
        assert len(gate.history) == 1
    """

    def __init__(self) -> None:
        self._history: list[ApprovalResult] = []

    async def request_approval(self, action: str, risk_level: RiskLevel) -> ApprovalResult:
        """Auto-approve the request immediately and record it in history.

        Args:
            action: Description of the action requiring approval.
            risk_level: The classified risk level of the action.

        Returns:
            An :class:`ApprovalResult` with status ``APPROVED``.
        """
        result = ApprovalResult(
            request_id=uuid.uuid4().hex,
            status=ApprovalStatus.APPROVED,
            approver="auto",
            timestamp=time.time(),
            metadata={"action": action, "risk_level": risk_level.value},
        )
        self._history.append(result)
        return result

    async def check_status(self, request_id: str) -> ApprovalStatus:
        """Look up the status of a previously submitted request.

        Args:
            request_id: The unique identifier from a prior approval result.

        Returns:
            The :class:`ApprovalStatus` of the matching request, or
            ``PENDING`` if the request ID is not found.
        """
        for entry in self._history:
            if entry.request_id == request_id:
                return entry.status
        return ApprovalStatus.PENDING

    @property
    def history(self) -> list[ApprovalResult]:
        """Return the list of all approval results for test assertions."""
        return list(self._history)


class ConfigurableApprovalGate:
    """Risk-based approval gate driven by an :class:`ApprovalPolicy`.

    Satisfies the :class:`~beddel.domain.ports.IApprovalGate` protocol
    via structural subtyping.  Requests whose risk level appears in
    ``policy.auto_approve_levels`` are auto-approved immediately.  All
    other requests are stored as ``PENDING`` for later resolution via
    the CIBA async flow (Task 5).

    Args:
        policy: The approval policy controlling auto-approve behaviour.
            Defaults to ``ApprovalPolicy()`` when ``None``.

    Example::

        policy = ApprovalPolicy(auto_approve_levels=[RiskLevel.LOW])
        gate = ConfigurableApprovalGate(policy=policy)

        low = await gate.request_approval("read_file", RiskLevel.LOW)
        assert low.status == ApprovalStatus.APPROVED

        high = await gate.request_approval("delete_db", RiskLevel.HIGH)
        assert high.status == ApprovalStatus.PENDING
    """

    def __init__(self, policy: ApprovalPolicy | None = None) -> None:
        self._policy = policy or ApprovalPolicy()
        self._requests: dict[str, ApprovalResult] = {}

    async def request_approval(self, action: str, risk_level: RiskLevel) -> ApprovalResult:
        """Evaluate the request against the policy and return a result.

        If ``risk_level`` is in ``policy.auto_approve_levels``, the request
        is auto-approved immediately.  Otherwise it is stored as ``PENDING``
        for later resolution.

        Args:
            action: Description of the action requiring approval.
            risk_level: The classified risk level of the action.

        Returns:
            An :class:`ApprovalResult` with status ``APPROVED`` or
            ``PENDING`` depending on the policy.
        """
        request_id = uuid.uuid4().hex
        if risk_level in self._policy.auto_approve_levels:
            status = ApprovalStatus.APPROVED
            approver: str | None = "policy"
        else:
            status = ApprovalStatus.PENDING
            approver = None

        result = ApprovalResult(
            request_id=request_id,
            status=status,
            approver=approver,
            timestamp=time.time(),
            metadata={"action": action, "risk_level": risk_level.value},
        )
        self._requests[request_id] = result
        return result

    async def check_status(self, request_id: str) -> ApprovalStatus:
        """Return the current status of a pending or resolved request.

        Args:
            request_id: The unique identifier from a prior approval result.

        Returns:
            The :class:`ApprovalStatus` of the matching request, or
            ``PENDING`` if the request ID is not found.
        """
        if request_id in self._requests:
            return self._requests[request_id].status
        return ApprovalStatus.PENDING

    @property
    def policy(self) -> ApprovalPolicy:
        """Return the configured approval policy."""
        return self._policy

    @property
    def pending_requests(self) -> dict[str, ApprovalResult]:
        """Return a copy of all stored requests (for test assertions)."""
        return dict(self._requests)
